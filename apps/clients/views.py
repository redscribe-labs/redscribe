from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, IntegerField, When
from django.shortcuts import get_object_or_404, render

from apps.crypto.services import decrypt_or_blank, record_aad
from apps.findings.models import ContentSectionDefinition, Finding, document_sections

from .access import (
    portal_engagement_access_required,
    record_client_finding_view,
    visible_client_engagements,
    visible_client_findings,
)

_SEVERITY_RANK = {severity: rank for rank, (severity, _label) in enumerate(Finding.Severity.choices)}


def _severity_breakdown(findings_qs):
    # Clear any inherited ordering/annotations first — an incoming queryset
    # already .order_by()'d (e.g. by a display-ordering annotation) would
    # otherwise drag those extra fields into the GROUP BY here, splitting
    # each severity into one group per finding instead of one group total.
    counts = {
        row["severity"]: row["n"]
        for row in findings_qs.order_by().values("severity").annotate(n=Count("id"))
    }
    return [
        {"value": severity, "label": label, "count": counts[severity]}
        for severity, label in Finding.Severity.choices
        if counts.get(severity)
    ]

@login_required
def portal_dashboard(request):
    if not request.user.is_client_role:
        raise PermissionDenied("This page is only available to client-portal users.")

    engagements = list(visible_client_engagements(request.user))

    approved_findings = Finding.objects.filter(
        engagement__in=engagements, workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=False,
    )
    counts_by_engagement = {}
    for row in approved_findings.values("engagement_id", "severity").annotate(n=Count("id")):
        counts_by_engagement.setdefault(row["engagement_id"], {})[row["severity"]] = row["n"]

    for engagement in engagements:
        counts = counts_by_engagement.get(engagement.pk, {})
        engagement.severity_breakdown = [
            {"value": severity, "label": label, "count": counts[severity]}
            for severity, label in Finding.Severity.choices
            if counts.get(severity)
        ]
        engagement.finding_total = sum(counts.values())

    attention_total = sum(
        row["count"]
        for engagement in engagements
        for row in engagement.severity_breakdown
        if row["value"] in (Finding.Severity.CRITICAL, Finding.Severity.HIGH)
    )

    return render(
        request, "clients_portal/dashboard.html",
        {
            "engagements": engagements,
            "finding_total": sum(e.finding_total for e in engagements),
            "attention_total": attention_total,
        },
    )


@portal_engagement_access_required
def portal_engagement_detail(request, engagement_id):
    findings = visible_client_findings(request.engagement)

    severity_rank = Case(
        *[When(severity=severity, then=rank) for severity, rank in _SEVERITY_RANK.items()],
        output_field=IntegerField(),
    )
    findings = findings.annotate(_severity_rank=severity_rank).order_by("_severity_rank", "title")

    return render(
        request, "clients_portal/engagement_detail.html",
        {
            "engagement": request.engagement, "findings": findings,
            "severity_breakdown": _severity_breakdown(findings),
        },
    )


@portal_engagement_access_required
def portal_finding_detail(request, engagement_id, pk):
    finding = get_object_or_404(
        Finding, pk=pk, engagement=request.engagement,
        workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=False,
    )

    if request.user.is_client_role:
        record_client_finding_view(finding, request.user)

    sections = list(ContentSectionDefinition.objects.filter(is_active=True, portal_visible=True).narrative())
    existing_sections = {fs.definition_id: fs for fs in finding.sections.all()}
    section_values = {}
    for definition in sections:
        finding_section = existing_sections.get(definition.id)
        section_values[definition.slug] = decrypt_or_blank(
            finding_section.content_ciphertext if finding_section else None, request.project_key,
            associated_data=record_aad("finding", finding.pk, definition.slug),
        )

    return render(
        request, "clients_portal/finding_detail.html",
        {
            "engagement": request.engagement, "finding": finding,
            "document_sections": document_sections(sections, section_values, encrypted=True),
        },
    )
