from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.crypto.access import engagement_access_required
from apps.crypto.services import decrypt_or_blank, encrypt_bytes, record_aad
from apps.engagements.breadcrumbs import engagement_crumbs
from apps.engagements.permissions import is_engagement_manager
from apps.feature_flags.models import FeatureFlags

from . import recurrence, retest
from .classifications import (
    classification_rows_for,
    classification_suggestions,
    parse_classification_rows,
    save_classification_rows,
    validate_classification_rows,
)
from .forms import FindingForm, RetestRecordForm
from .models import (
    ContentSectionDefinition,
    Finding,
    FindingSection,
    VulnerabilityTemplate,
    VulnerabilityTemplateApprovedVersion,
    document_sections,
)
from .permissions import can_archive_finding, can_delete_finding, can_edit_finding_content
from .review import (
    auto_assign_reviewer_if_configured,
    bulk_eligible_qa_candidates,
    bulk_eligible_reviewer_candidates,
    eligible_qa_candidates,
    eligible_reviewer_candidates,
)

PAGE_SIZE = 10

PLAIN_FIELDS = ["title", "cvss_score", "cvss_vector", "severity", "cve_id", "status", "affects"]


def _save_finding(form, engagement, project_key, *, classification_tags, instance=None, created_by=None, sections=None):
    sections = list(ContentSectionDefinition.objects.filter(is_active=True)) if sections is None else sections
    finding = instance or Finding(engagement=engagement, created_by=created_by)
    for field in PLAIN_FIELDS:
        setattr(finding, field, form.cleaned_data[field])
    finding.save()

    for definition in sections:
        if definition.is_protected:
            # "affects" (PLAIN_FIELDS, above) is the only protected section
            # today — it's stored on Finding directly, not as a generic
            # FindingSection.
            continue
        content = form.section_content(definition.slug)
        ciphertext = encrypt_bytes(
            content.encode("utf-8"), project_key,
            associated_data=record_aad("finding", finding.pk, definition.slug),
        )
        FindingSection.objects.update_or_create(
            finding=finding, definition=definition, defaults={"content_ciphertext": ciphertext},
        )

    finding.classifications.set(classification_tags)
    return finding


def _cvss_sort_key(finding):
    try:
        return (0, -float(finding.cvss_score))
    except (TypeError, ValueError):
        return (1, 0.0)


@engagement_access_required
def finding_list(request, engagement_id):
    query = request.GET.get("q", "").strip()
    show_archived = request.GET.get("archived") == "1"
    all_findings = request.engagement.findings.select_related(
        "created_by", "assigned_reviewer", "assigned_qa"
    ).prefetch_related("classifications")
    archived_count = all_findings.filter(archived=True).count()
    findings = all_findings if show_archived else all_findings.filter(archived=False)
    if query:
        findings = findings.filter(Q(title__icontains=query) | Q(cve_id__icontains=query))
    findings = sorted(findings, key=_cvss_sort_key)

    page_obj = Paginator(findings, PAGE_SIZE).get_page(request.GET.get("page"))

    Status = Finding.WorkflowStatus
    user = request.user
    is_manager = is_engagement_manager(user, request.engagement)
    non_archived = request.engagement.findings.filter(archived=False)
    awaiting_review_count = non_archived.filter(
        workflow_status__in=[Status.DRAFT, Status.REVIEW_CHANGES_REQUESTED]
    ).count()
    awaiting_qa_count = non_archived.filter(
        workflow_status__in=[Status.REVIEWED, Status.QA_CHANGES_REQUESTED]
    ).count()
    my_review_count = non_archived.filter(
        workflow_status__in=[Status.DRAFT, Status.REVIEW_CHANGES_REQUESTED],
    ).filter(Q(assigned_reviewer=user) if not user.has_permission("findings.act_any_assignment") else Q()).count()
    my_qa_count = non_archived.filter(
        workflow_status__in=[Status.REVIEWED, Status.QA_CHANGES_REQUESTED],
    ).filter(Q(assigned_qa=user) if not user.has_permission("findings.act_any_assignment") else Q()).count()

    return render(
        request, "findings/list.html",
        {
            "engagement": request.engagement,
            "page_obj": page_obj,
            "findings": page_obj.object_list,
            "query": query,
            "show_archived": show_archived,
            "archived_count": archived_count,
            "is_manager": is_manager,
            "bulk_reviewer_candidates": bulk_eligible_reviewer_candidates() if is_manager else None,
            "bulk_qa_candidates": bulk_eligible_qa_candidates() if is_manager else None,
            "awaiting_review_count": awaiting_review_count,
            "awaiting_qa_count": awaiting_qa_count,
            "my_review_count": my_review_count,
            "my_qa_count": my_qa_count,
            "breadcrumbs": engagement_crumbs(request.engagement) + [{"label": "Findings"}],
        },
    )


_TEMPLATE_TO_FORM_FIELD = {
    "title": "title",
    "default_cvss_score": "cvss_score",
    "default_cvss_vector": "cvss_vector",
    "default_severity": "severity",
}


def _importable_catalogue_source(template: VulnerabilityTemplate):
    """The content to actually copy from when importing a catalogue entry into a finding.

    Only approved content is importable. If the live entry has since been edited (and so
    dropped back to Draft/Pending QA — see catalogue_views.template_edit), fall back to the
    frozen snapshot of its last approved version rather than exposing unvetted edits.
    """
    if template.status == VulnerabilityTemplate.Status.APPROVED:
        return template
    return getattr(template, "approved_version", None)


def _initial_from_template(source) -> dict:
    initial = {
        form_field: getattr(source, template_field)
        for template_field, form_field in _TEMPLATE_TO_FORM_FIELD.items()
    }
    if isinstance(source, VulnerabilityTemplateApprovedVersion):
        for slug, content in source.sections.items():
            initial[f"section__{slug}"] = content
    else:
        for template_section in source.sections.select_related("definition"):
            initial[f"section__{template_section.definition.slug}"] = template_section.content
    return initial


@engagement_access_required
def finding_create(request, engagement_id):
    sections = list(ContentSectionDefinition.objects.filter(is_active=True))
    if request.method == "POST":
        form = FindingForm(request.POST, sections=sections)
        classification_rows = parse_classification_rows(request.POST)
        classification_errors = validate_classification_rows(classification_rows)
        if form.is_valid() and not classification_errors:
            finding = _save_finding(
                form, request.engagement, request.project_key, created_by=request.user,
                classification_tags=save_classification_rows(classification_rows), sections=sections,
            )
            auto_assign_reviewer_if_configured(finding)
            messages.success(request, f"Finding '{finding.title}' created as Draft.")
            return redirect("findings:detail", engagement_id=engagement_id, pk=finding.pk)
    else:
        template_source = None
        template_id = request.GET.get("from_template")
        if template_id:
            catalogue_entry = get_object_or_404(VulnerabilityTemplate, pk=template_id)
            template_source = _importable_catalogue_source(catalogue_entry)
            if template_source is None:
                messages.error(
                    request,
                    f"'{catalogue_entry.title}' isn't approved yet and can't be imported into a finding.",
                )
        form = FindingForm(
            initial=_initial_from_template(template_source) if template_source else None, sections=sections,
        )
        classification_rows = classification_rows_for(template_source) if template_source else []
        classification_errors = []

    return render(
        request, "findings/create.html",
        {
            "engagement": request.engagement, "form": form,
            "classification_rows": classification_rows, "classification_errors": classification_errors,
            "classification_suggestions": classification_suggestions(),
            "breadcrumbs": engagement_crumbs(request.engagement) + [
                {"label": "Findings", "url": reverse("findings:list", args=[request.engagement.pk])},
                {"label": "New Finding"},
            ],
        },
    )


@engagement_access_required
def finding_detail(request, engagement_id, pk):
    finding = get_object_or_404(Finding, pk=pk, engagement=request.engagement)
    # "Affects" is shown separately, near the finding's other metadata badges
    # (see templates/findings/detail.html) — excluded here, same as the
    # client portal's equivalent detail view.
    sections = list(ContentSectionDefinition.objects.filter(is_active=True).narrative())
    existing_sections = {fs.definition_id: fs for fs in finding.sections.all()}
    section_values = {}
    for definition in sections:
        finding_section = existing_sections.get(definition.id)
        section_values[definition.slug] = decrypt_or_blank(
            finding_section.content_ciphertext if finding_section else None, request.project_key,
            associated_data=record_aad("finding", finding.pk, definition.slug),
        )

    is_manager = is_engagement_manager(request.user, request.engagement)
    user = request.user
    Status = Finding.WorkflowStatus

    is_assigned_reviewer = bool(
        user.has_permission("findings.act_any_assignment") or (finding.assigned_reviewer_id and user.pk == finding.assigned_reviewer_id)
    )
    is_assigned_qa = bool(
        user.has_permission("findings.act_any_assignment") or (finding.assigned_qa_id and user.pk == finding.assigned_qa_id)
    )
    is_author = bool(finding.created_by_id and user.pk == finding.created_by_id)
    can_assign_reviewer_here = is_manager or is_author
    can_assign_qa_here = is_manager or is_assigned_reviewer or is_author
    awaiting_review = finding.workflow_status in {Status.DRAFT, Status.REVIEW_CHANGES_REQUESTED}
    awaiting_qa = finding.workflow_status in {Status.REVIEWED, Status.QA_CHANGES_REQUESTED}
    recurrence_enabled = FeatureFlags.get_solo().recurrence_and_trends

    return render(
        request, "findings/detail.html",
        {
            "engagement": request.engagement, "finding": finding,
            "document_sections": document_sections(sections, section_values, encrypted=True),
            "can_edit_content": can_edit_finding_content(user, finding),
            "is_manager": is_manager,
            "reviewer_candidates": eligible_reviewer_candidates(finding, assigned_by=user) if can_assign_reviewer_here else None,
            "qa_candidates": eligible_qa_candidates(finding, assigned_by=user) if can_assign_qa_here else None,
            "is_assigned_reviewer": is_assigned_reviewer,
            "is_assigned_qa": is_assigned_qa,
            "can_assign_reviewer": can_assign_reviewer_here and awaiting_review,
            "can_submit_review": is_assigned_reviewer and bool(finding.assigned_reviewer_id) and awaiting_review,
            "can_assign_qa": can_assign_qa_here and awaiting_qa,
            "can_submit_qa": is_assigned_qa and bool(finding.assigned_qa_id) and awaiting_qa,
            "can_reopen": is_manager and finding.workflow_status != Status.DRAFT,
            "can_archive": is_manager,
            "can_delete": can_delete_finding(user, finding),
            "linked_checklist_items": finding.checklist_items.all(),
            "can_log_retest": retest.can_log_retest_result(user, finding),
            "retest_workflow_enabled": FeatureFlags.get_solo().retest_workflow,
            "retest_form": RetestRecordForm(),
            "retest_records": [
                {
                    "status": r.status, "status_display": r.get_status_display(),
                    "tested_by": r.tested_by, "created_at": r.created_at,
                    "notes": decrypt_or_blank(
                        r.notes_ciphertext, request.project_key,
                        associated_data=record_aad("retestrecord", r.pk, "notes"),
                    ),
                }
                for r in finding.retest_records.select_related("tested_by")
            ],
            "similar_catalogue_entries": (
                recurrence.similar_catalogue_entries(finding) if recurrence_enabled else []
            ),
            "repeat_findings_for_client": (
                recurrence.repeat_findings_for_client(finding) if recurrence_enabled else []
            ),
            "client_views": finding.client_views.select_related("client_user", "client_user__client"),
            "breadcrumbs": engagement_crumbs(request.engagement) + [
                {"label": "Findings", "url": reverse("findings:list", args=[request.engagement.pk])},
                {"label": finding.title},
            ],
        },
    )


_REOPEN_TO_STATUS = {
    Finding.WorkflowStatus.REVIEWED: Finding.WorkflowStatus.DRAFT,
    Finding.WorkflowStatus.QA_APPROVED: Finding.WorkflowStatus.REVIEWED,
}
_LOCKED_WORKFLOW_STATUSES = set(_REOPEN_TO_STATUS)


@engagement_access_required
def finding_edit(request, engagement_id, pk):
    finding = get_object_or_404(Finding, pk=pk, engagement=request.engagement)
    if not can_edit_finding_content(request.user, finding):
        raise PermissionDenied("You don't have permission to edit this finding.")

    edit_version = finding.updated_at.isoformat()
    sections = list(ContentSectionDefinition.objects.filter(is_active=True))

    if request.method == "POST":
        form = FindingForm(request.POST, sections=sections)
        posted_version = request.POST.get("_version", "")
        classification_rows = parse_classification_rows(request.POST)
        classification_errors = validate_classification_rows(classification_rows, require_at_least_one=False)
        if form.is_valid() and posted_version and posted_version != edit_version:
            messages.error(
                request,
                "This finding was updated by someone else while you were editing. "
                "Your changes below have NOT been saved — review the current version "
                "first, then press Save again to overwrite it, or reload the page to "
                "start fresh.",
            )
        elif form.is_valid() and not classification_errors:
            reopen_to = _REOPEN_TO_STATUS.get(finding.workflow_status)
            _save_finding(
                form, request.engagement, request.project_key, instance=finding,
                classification_tags=save_classification_rows(classification_rows), sections=sections,
            )
            auto_assign_reviewer_if_configured(finding)
            if reopen_to is not None:
                finding.workflow_status = reopen_to
                finding.save(update_fields=["workflow_status"])
                messages.success(
                    request,
                    "Finding updated — since it had already been reviewed/QA approved, "
                    "it's been reopened for re-review/re-QA (existing reviewer/QA "
                    "assignment kept).",
                )
            else:
                messages.success(request, "Finding updated.")
            return redirect("findings:detail", engagement_id=engagement_id, pk=finding.pk)
    else:
        initial = {field: getattr(finding, field) for field in PLAIN_FIELDS}
        existing_sections = {fs.definition_id: fs for fs in finding.sections.all()}
        for definition in sections:
            finding_section = existing_sections.get(definition.id)
            initial[f"section__{definition.slug}"] = decrypt_or_blank(
                finding_section.content_ciphertext if finding_section else None, request.project_key,
                associated_data=record_aad("finding", finding.pk, definition.slug),
            )
        form = FindingForm(initial=initial, sections=sections)
        classification_rows = classification_rows_for(finding)
        classification_errors = []

    return render(
        request, "findings/edit.html",
        {
            "engagement": request.engagement, "finding": finding, "form": form,
            "edit_version": edit_version,
            "classification_rows": classification_rows, "classification_errors": classification_errors,
            "classification_suggestions": classification_suggestions(),
            "breadcrumbs": engagement_crumbs(request.engagement) + [
                {"label": "Findings", "url": reverse("findings:list", args=[request.engagement.pk])},
                {
                    "label": finding.title,
                    "url": reverse("findings:detail", args=[request.engagement.pk, finding.pk]),
                },
                {"label": "Edit"},
            ],
        },
    )


@engagement_access_required
def finding_archive(request, engagement_id, pk):
    finding = get_object_or_404(Finding, pk=pk, engagement=request.engagement)
    if not can_delete_finding(request.user, finding):
        raise PermissionDenied("Only a Superadmin, Team Lead, or this finding's creator can archive it.")

    if finding.archived:
        messages.info(request, f"'{finding.title}' is already archived.")
        return redirect("findings:detail", engagement_id=engagement_id, pk=finding.pk)

    if request.method == "POST":
        finding.archived = True
        finding.archived_at = timezone.now()
        finding.save(update_fields=["archived", "archived_at"])
        messages.success(request, f"'{finding.title}' archived.")
        return redirect("findings:detail", engagement_id=engagement_id, pk=finding.pk)

    return render(
        request, "findings/archive_confirm.html",
        {"engagement": request.engagement, "finding": finding},
    )


@engagement_access_required
def finding_unarchive(request, engagement_id, pk):
    finding = get_object_or_404(Finding, pk=pk, engagement=request.engagement)
    if not can_archive_finding(request.user, finding):
        raise PermissionDenied("Only a Superadmin or Team Lead can unarchive this finding.")

    if request.method == "POST":
        finding.archived = False
        finding.archived_at = None
        finding.save(update_fields=["archived", "archived_at"])
        messages.success(request, f"'{finding.title}' unarchived.")
    return redirect("findings:detail", engagement_id=engagement_id, pk=finding.pk)
