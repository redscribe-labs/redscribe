from types import SimpleNamespace

from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.crypto.access import engagement_access_required
from apps.engagements.breadcrumbs import engagement_crumbs

from . import assembly, docx_export, html_export, md_export, pdf_export
from .job_limiter import report_job_slot
from .models import ReportExportLog
from .services import PUBLISHABLE_STATUSES

_IR_FORMATS = {"md", "pdf", "html"}
_DOCX_FORMATS = {"docx"}
_ALL_FORMATS = _IR_FORMATS | _DOCX_FORMATS

_LIMITED_FORMATS = {"pdf", "md", "html", "docx"}

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _report_filename(engagement, fmt: str) -> str:
    base = slugify(engagement.reference_number or engagement.client_name) or "report"
    date = timezone.localdate().isoformat()
    return f"{base}-report-{date}.{fmt}"


@engagement_access_required
def export_options(request, engagement_id):
    engagement = request.engagement
    config = assembly.get_draft_config(engagement)
    content = assembly.seeded_content(engagement, config)
    included_count = len(assembly._select_findings(engagement, content.get("findings", {})))
    excluded_count = engagement.findings.exclude(workflow_status__in=PUBLISHABLE_STATUSES).count()
    profile = assembly.get_effective_profile(config)
    return render(
        request, "reports/export_options.html",
        {
            "engagement": engagement,
            "included_count": included_count,
            "excluded_count": excluded_count,
            "export_logs": engagement.report_export_logs.select_related("exported_by")[:20],
            "docx_available": bool(profile and profile.docx_template),
            "breadcrumbs": engagement_crumbs(engagement) + [{"label": "Export report"}],
        },
    )


def _build_document(request, engagement):
    config = assembly.get_draft_config(engagement)
    content = assembly.seeded_content(engagement, config)
    return assembly.build_report_document(
        config=SimpleNamespace(
            content=content, is_remediation_report=config.is_remediation_report, profile=config.profile,
        ),
        engagement=engagement, project_key=request.project_key, user=request.user,
    )


def _generate_export(request, engagement, fmt):
    if fmt == "md":
        return "application/zip", md_export.build_markdown_zip(_build_document(request, engagement))
    if fmt == "pdf":
        return "application/pdf", pdf_export.build_pdf(_build_document(request, engagement))
    if fmt == "docx":
        config = assembly.get_draft_config(engagement)
        content = assembly.seeded_content(engagement, config)
        return _DOCX_CONTENT_TYPE, docx_export.build_docx(
            config=SimpleNamespace(
                content=content, is_remediation_report=config.is_remediation_report, profile=config.profile,
            ),
            engagement=engagement, project_key=request.project_key, user=request.user,
        )
    return "text/html; charset=utf-8", html_export.build_html(_build_document(request, engagement))


@require_POST
@engagement_access_required
def export_download(request, engagement_id, fmt):
    if fmt not in _ALL_FORMATS:
        return HttpResponseBadRequest("Unknown export format.")

    engagement = request.engagement

    if fmt == "docx":
        config = assembly.get_draft_config(engagement)
        profile = assembly.get_effective_profile(config)
        if not (profile and profile.docx_template):
            messages.error(request, "This report profile has no Word (.docx) template configured.")
            return redirect("reports:options", engagement_id=engagement.pk)

    pdf_password = request.POST.get("pdf_password", "").strip() if fmt == "pdf" else ""

    try:
        if fmt in _LIMITED_FORMATS:
            with report_job_slot(engagement, fmt) as acquired:
                if not acquired:
                    messages.warning(
                        request,
                        "The server is currently generating other reports — please try again in a moment.",
                    )
                    return redirect("reports:options", engagement_id=engagement.pk)
                content_type, content = _generate_export(request, engagement, fmt)
                if pdf_password:
                    content = pdf_export.encrypt_pdf(content, pdf_password)
        else:
            content_type, content = _generate_export(request, engagement, fmt)
    except docx_export.DocxExportError as exc:
        messages.error(request, str(exc))
        return redirect("reports:options", engagement_id=engagement.pk)

    ReportExportLog.objects.create(
        engagement=engagement, fmt=fmt, comment=request.POST.get("comment", "").strip(),
        exported_by=request.user,
    )

    response = HttpResponse(content, content_type=content_type)
    filename = _report_filename(engagement, "markdown.zip" if fmt == "md" else fmt)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
