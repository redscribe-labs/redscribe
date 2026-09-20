from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.engagements.access import visible_engagements

from . import catalogue_io
from .classifications import (
    classification_rows_for,
    classification_suggestions,
    parse_classification_rows,
    save_classification_rows,
    validate_classification_rows,
)
from .forms import CatalogueImportForm, VulnerabilityTemplateForm
from .models import (
    ClassificationTag,
    ContentSectionDefinition,
    VulnerabilityTemplate,
    VulnerabilityTemplateApprovedVersion,
    document_sections,
)
from .permissions import (
    can_approve_catalogue_entry,
    can_bulk_manage_catalogue,
    can_create_catalogue_entry,
    can_delete_catalogue_entry,
    can_edit_catalogue_entry,
    can_submit_catalogue_qa,
)

DEFAULT_PAGE_SIZE = 10
PAGE_SIZE_CHOICES = [10, 25, 50, 100]


@login_required
def template_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    severity = request.GET.get("severity", "").strip()
    taxonomy = request.GET.get("taxonomy", "").strip()
    created_by = request.GET.get("created_by", "").strip()
    date_from = parse_date(request.GET.get("from", "").strip())
    date_to = parse_date(request.GET.get("to", "").strip())

    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
    except ValueError:
        page_size = DEFAULT_PAGE_SIZE
    if page_size not in PAGE_SIZE_CHOICES:
        page_size = DEFAULT_PAGE_SIZE

    status_choices = VulnerabilityTemplate.Status.choices
    severity_choices = VulnerabilityTemplate._meta.get_field("default_severity").choices

    templates = VulnerabilityTemplate.objects.select_related("created_by").prefetch_related("classifications")
    if query:
        templates = templates.filter(
            Q(title__icontains=query)
            | Q(classifications__taxonomy__icontains=query)
            | Q(classifications__value__icontains=query)
        )
    if status in dict(status_choices):
        templates = templates.filter(status=status)
    if severity in dict(severity_choices):
        templates = templates.filter(default_severity=severity)
    if taxonomy:
        templates = templates.filter(classifications__taxonomy=taxonomy)
    if created_by:
        templates = templates.filter(created_by_id=created_by)
    if date_from:
        templates = templates.filter(created_at__date__gte=date_from)
    if date_to:
        templates = templates.filter(created_at__date__lte=date_to)
    templates = templates.distinct().order_by("-created_at")

    page_obj = Paginator(templates, page_size).get_page(request.GET.get("page"))
    page_range = [
        p if isinstance(p, int) else None
        for p in page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    ]

    taxonomy_choices = sorted(
        ClassificationTag.objects.order_by().values_list("taxonomy", flat=True).distinct()
    )
    creator_choices = list(
        get_user_model().objects.filter(vulnerability_templates_created__isnull=False)
        .distinct().order_by("username").values_list("id", "username")
    )

    carry_params = request.GET.copy()
    carry_params.pop("page", None)
    carry_querystring = carry_params.urlencode()

    return render(
        request, "catalogue/list.html",
        {
            "page_obj": page_obj,
            "page_range": page_range,
            "query": query,
            "status": status,
            "severity": severity,
            "taxonomy": taxonomy,
            "created_by": created_by,
            "date_from": request.GET.get("from", ""),
            "date_to": request.GET.get("to", ""),
            "page_size": page_size,
            "page_size_choices": PAGE_SIZE_CHOICES,
            "status_choices": status_choices,
            "severity_choices": severity_choices,
            "taxonomy_choices": taxonomy_choices,
            "creator_choices": creator_choices,
            "carry_querystring": carry_querystring,
            "breadcrumbs": [{"label": "Catalogue"}],
        },
    )


@login_required
def template_export(request):
    if not can_bulk_manage_catalogue(request.user):
        raise PermissionDenied("Only a Superadmin can export the catalogue.")

    payload = catalogue_io.export_templates(VulnerabilityTemplate.objects.all())
    response = HttpResponse(payload, content_type="application/json")
    filename = timezone.now().strftime("redscribe-catalogue-%Y%m%d-%H%M%S.json")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def template_import(request):
    if not can_bulk_manage_catalogue(request.user):
        raise PermissionDenied("Only a Superadmin can import into the catalogue.")

    if request.method == "POST":
        form = CatalogueImportForm(request.POST, request.FILES)
        if form.is_valid():
            raw_text = form.cleaned_data["file"].read().decode("utf-8", errors="replace")
            try:
                created = catalogue_io.import_templates(raw_text, created_by=request.user)
            except catalogue_io.CatalogueImportError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    f"Imported {len(created)} catalogue entr{'y' if len(created) == 1 else 'ies'} as Draft — "
                    "review and approve each one individually.",
                )
                return redirect("catalogue:list")
    else:
        form = CatalogueImportForm()

    return render(
        request, "catalogue/import.html",
        {
            "form": form,
            "breadcrumbs": [{"label": "Catalogue", "url": reverse("catalogue:list")}, {"label": "Import"}],
        },
    )


@login_required
def template_detail(request, pk):
    template = get_object_or_404(VulnerabilityTemplate, pk=pk)
    sections = list(ContentSectionDefinition.objects.filter(is_active=True).narrative())
    values = {ts.definition.slug: ts.content for ts in template.sections.select_related("definition")}
    approved_version = getattr(template, "approved_version", None)
    return render(
        request, "catalogue/detail.html",
        {
            "template": template,
            "document_sections": document_sections(sections, values),
            "can_approve": can_approve_catalogue_entry(request.user),
            "can_edit": can_edit_catalogue_entry(request.user, template),
            "can_delete": can_delete_catalogue_entry(request.user, template),
            "can_submit_qa": (
                template.status == VulnerabilityTemplate.Status.DRAFT
                and can_submit_catalogue_qa(request.user, template)
            ),
            "is_importable": (
                template.status == VulnerabilityTemplate.Status.APPROVED or approved_version is not None
            ),
            "importing_stale_version": (
                template.status != VulnerabilityTemplate.Status.APPROVED and approved_version is not None
            ),
            "approved_version": approved_version,
            "engagements": visible_engagements(request.user),
            "breadcrumbs": [
                {"label": "Catalogue", "url": reverse("catalogue:list")},
                {"label": template.title},
            ],
        },
    )


@login_required
def template_create(request):
    if not can_create_catalogue_entry(request.user):
        raise PermissionDenied("You must be signed in to add to the vulnerability catalogue.")

    sections = list(ContentSectionDefinition.objects.filter(is_active=True).narrative())
    if request.method == "POST":
        form = VulnerabilityTemplateForm(request.POST, sections=sections)
        classification_rows = parse_classification_rows(request.POST)
        classification_errors = validate_classification_rows(classification_rows)
        if form.is_valid() and not classification_errors:
            template = form.save(
                created_by=request.user, classification_tags=save_classification_rows(classification_rows),
            )
            messages.success(request, f"Template '{template.title}' created as Draft.")
            return redirect("catalogue:detail", pk=template.pk)
    else:
        form = VulnerabilityTemplateForm(sections=sections)
        classification_rows = []
        classification_errors = []

    return render(
        request, "catalogue/create.html",
        {
            "form": form,
            "classification_rows": classification_rows, "classification_errors": classification_errors,
            "classification_suggestions": classification_suggestions(),
            "breadcrumbs": [
                {"label": "Catalogue", "url": reverse("catalogue:list")},
                {"label": "New Template"},
            ],
        },
    )


@login_required
def template_edit(request, pk):
    template = get_object_or_404(VulnerabilityTemplate, pk=pk)
    if not can_edit_catalogue_entry(request.user, template):
        raise PermissionDenied("You don't have permission to edit this catalogue entry.")

    sections = list(ContentSectionDefinition.objects.filter(is_active=True).narrative())
    if request.method == "POST":
        form = VulnerabilityTemplateForm(request.POST, sections=sections)
        classification_rows = parse_classification_rows(request.POST)
        classification_errors = validate_classification_rows(classification_rows, require_at_least_one=False)
        if form.is_valid() and not classification_errors:
            needs_reset = template.status != VulnerabilityTemplate.Status.DRAFT
            was_approved = template.status == VulnerabilityTemplate.Status.APPROVED
            form.save(
                instance=template, classification_tags=save_classification_rows(classification_rows),
            )
            if needs_reset:
                template.status = VulnerabilityTemplate.Status.DRAFT
                template.save(update_fields=["status"])
                messages.success(
                    request,
                    "Template updated — since it was "
                    + ("approved" if was_approved else "pending QA")
                    + ", it's been reset to Draft and will need to be approved again.",
                )
            else:
                messages.success(request, "Template updated.")
            return redirect("catalogue:detail", pk=template.pk)
    else:
        initial = {
            "title": template.title,
            "default_cvss_score": template.default_cvss_score,
            "default_cvss_vector": template.default_cvss_vector,
            "default_severity": template.default_severity,
        }
        for template_section in template.sections.select_related("definition"):
            initial[f"section__{template_section.definition.slug}"] = template_section.content
        form = VulnerabilityTemplateForm(initial=initial, sections=sections)
        classification_rows = classification_rows_for(template)
        classification_errors = []

    return render(
        request, "catalogue/edit.html",
        {
            "form": form, "template": template,
            "classification_rows": classification_rows, "classification_errors": classification_errors,
            "classification_suggestions": classification_suggestions(),
            "breadcrumbs": [
                {"label": "Catalogue", "url": reverse("catalogue:list")},
                {"label": template.title, "url": reverse("catalogue:detail", args=[template.pk])},
                {"label": "Edit"},
            ],
        },
    )


@login_required
def template_delete(request, pk):
    template = get_object_or_404(VulnerabilityTemplate, pk=pk)
    if not can_delete_catalogue_entry(request.user, template):
        raise PermissionDenied("You don't have permission to delete this catalogue entry.")

    if request.method == "POST":
        title = template.title
        template.delete()
        messages.success(request, f"Template '{title}' deleted.")
        return redirect("catalogue:list")

    return render(request, "catalogue/delete_confirm.html", {"template": template})


@login_required
def template_submit_qa(request, pk):
    template = get_object_or_404(VulnerabilityTemplate, pk=pk)
    if not can_submit_catalogue_qa(request.user, template):
        raise PermissionDenied("You don't have permission to submit this catalogue entry for QA.")

    if request.method == "POST":
        if template.status != VulnerabilityTemplate.Status.DRAFT:
            messages.info(request, f"'{template.title}' is not a Draft.")
        else:
            template.status = VulnerabilityTemplate.Status.PENDING_QA
            template.save(update_fields=["status"])
            messages.success(request, f"'{template.title}' submitted for QA.")

    return redirect("catalogue:detail", pk=template.pk)


@login_required
def template_approve(request, pk):
    template = get_object_or_404(VulnerabilityTemplate, pk=pk)
    if not can_approve_catalogue_entry(request.user):
        raise PermissionDenied("You don't have permission to approve catalogue entries.")

    if request.method == "POST":
        if template.status == VulnerabilityTemplate.Status.APPROVED:
            messages.info(request, f"'{template.title}' is already approved.")
        else:
            template.status = VulnerabilityTemplate.Status.APPROVED
            template.save(update_fields=["status"])
            VulnerabilityTemplateApprovedVersion.snapshot(template, approved_by=request.user)
            messages.success(request, f"'{template.title}' approved.")

    return redirect("catalogue:detail", pk=template.pk)


@login_required
def template_unapprove(request, pk):
    template = get_object_or_404(VulnerabilityTemplate, pk=pk)
    if not can_approve_catalogue_entry(request.user):
        raise PermissionDenied("You don't have permission to change catalogue approval status.")

    if request.method == "POST":
        if template.status == VulnerabilityTemplate.Status.DRAFT:
            messages.info(request, f"'{template.title}' is already a Draft.")
        else:
            template.status = VulnerabilityTemplate.Status.DRAFT
            template.save(update_fields=["status"])
            # An explicit revert is an approver saying "don't use this content" — unlike an
            # edit-triggered reset (template_edit), it also revokes the importable snapshot.
            VulnerabilityTemplateApprovedVersion.objects.filter(template=template).delete()
            messages.success(request, f"'{template.title}' reverted to Draft.")

    return redirect("catalogue:detail", pk=template.pk)
