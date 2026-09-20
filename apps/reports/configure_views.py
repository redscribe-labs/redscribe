import json
from types import SimpleNamespace

from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.crypto.access import engagement_access_required
from apps.engagements.breadcrumbs import engagement_crumbs
from apps.findings.models import Finding

from . import assembly, ir_render
from .models import ReportProfile


def _empty_preview_message(profile) -> str:
    if profile is not None and profile.docx_template:
        return (
            "This profile exports via an uploaded Word (.docx) template, and its Document "
            "tab has no content of its own configured — there's nothing to show a live "
            "HTML preview of here. Save this configuration, then use “Export report” → "
            "Word (.docx) to see the actual result."
        )
    return "This report profile's Document tab has no content configured yet — nothing to preview."


def _preview_html(document, profile) -> str:
    if document.sections:
        return ir_render.render_document_html(document)
    from django.utils.html import escape

    return f'<p class="text-sm text-slate-500 italic p-3">{escape(_empty_preview_message(profile))}</p>'


def _publishable_findings(engagement):
    return sorted(
        (f for f in engagement.findings.all() if f.workflow_status in assembly.PUBLISHABLE_STATUSES),
        key=lambda f: (
            assembly._SEVERITY_ORDER.index(f.severity) if f.severity in assembly._SEVERITY_ORDER else 99,
            f.title.lower(),
        ),
    )


@engagement_access_required
def report_configure(request, engagement_id):
    engagement = request.engagement
    config = assembly.get_draft_config(engagement)

    if request.method == "POST":
        try:
            content = json.loads(request.POST.get("content_json") or "{}")
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Malformed configuration payload.")
        config.content = content
        config.is_remediation_report = request.POST.get("is_remediation_report") == "on"
        profile_id = request.POST.get("report_profile") or None
        config.profile_id = profile_id if profile_id and ReportProfile.objects.filter(pk=profile_id).exists() else None
        config.created_by = config.created_by or request.user
        config.save()
        messages.success(request, "Report configuration saved.")
        return redirect("reports:configure", engagement_id=engagement.pk)

    content = assembly.seeded_content(engagement, config)
    effective_profile = assembly.get_effective_profile(config)
    document = assembly.build_report_document(
        config=SimpleNamespace(
            content=content, is_remediation_report=config.is_remediation_report, profile=config.profile,
        ),
        engagement=engagement, project_key=request.project_key, user=request.user,
    )
    preview_html = _preview_html(document, effective_profile)

    return render(
        request, "reports/configure.html",
        {
            "engagement": engagement,
            "config": config,
            "content": content,
            "is_remediation_report": config.is_remediation_report,
            "report_profiles": ReportProfile.objects.all(),
            "selected_profile_id": config.profile_id,
            "selected_profile_cover_title": effective_profile.cover_title if effective_profile else "",
            "selected_profile_classification_label": effective_profile.classification_label if effective_profile else "",
            "selected_profile_has_docx_template": bool(effective_profile and effective_profile.docx_template),
            "publishable_findings": _publishable_findings(engagement),
            "severity_choices": Finding.Severity.choices,
            "status_choices": Finding.Status.choices,
            "dynamic_section_fields": [
                (block.slug, block.label, assembly.dynamic_tag_value(content, block.slug, effective_profile))
                for block in assembly.visible_dynamic_blocks(effective_profile)
            ],
            "preview_html": preview_html,
            "preview_css": ir_render.build_preview_css(document.meta),
            "preview_url": reverse("reports:preview", args=[engagement.pk]),
            "breadcrumbs": engagement_crumbs(engagement) + [{"label": "Configure report"}],
        },
    )


@engagement_access_required
def report_preview(request, engagement_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    engagement = request.engagement
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Malformed preview payload.")

    config = SimpleNamespace(
        content=assembly.sanitize_content(payload.get("content")),
        is_remediation_report=bool(payload.get("is_remediation_report")),
        profile=assembly.get_draft_config(engagement).profile,
    )
    document = assembly.build_report_document(
        config=config, engagement=engagement, project_key=request.project_key, user=request.user,
    )
    html = _preview_html(document, assembly.get_effective_profile(config))
    return JsonResponse({"html": html})
