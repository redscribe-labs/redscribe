from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.crypto.access import engagement_access_required
from apps.engagements.breadcrumbs import engagement_crumbs
from apps.feature_flags.models import FeatureFlags

from .forms import ScanImportForm, selected_import_rows
from .scan_import import FORMAT_LABELS, import_scan, import_target_section, parse_scan, preview_rows


def _preview(request, form):
    """The rows a scan file would create, as a fragment the import page shows
    before anything is saved. The file stays in the browser; nothing is kept."""
    context = {"noun": "result", "noun_plural": "results"}
    if form.is_valid():
        try:
            items = parse_scan(form.cleaned_data["file"].read(), form.cleaned_data["format"])
            context["rows"] = preview_rows(request.engagement, items)
            context["duplicate_label"] = "Already in this engagement"
        except ValueError as exc:
            context["error"] = str(exc)
    else:
        context["error"] = " ".join(e for errors in form.errors.values() for e in errors)
    return render(request, "base/_import_preview.html", context, status=200 if "rows" in context else 400)


@engagement_access_required
def finding_import(request, engagement_id):
    if not FeatureFlags.get_solo().scan_import:
        raise PermissionDenied("Scan import is currently disabled.")

    if request.method == "POST":
        form = ScanImportForm(request.POST, request.FILES)
        if request.POST.get("preview") == "1":
            return _preview(request, form)
        only = selected_import_rows(request.POST)
        if only is not None and not only:
            form.add_error(None, "Tick at least one result to import.")
        if form.is_valid():
            fmt = form.cleaned_data["format"]
            try:
                count = import_scan(
                    only=only,
                    engagement=request.engagement, project_key=request.project_key,
                    raw=form.cleaned_data["file"].read(), fmt=fmt, imported_by=request.user,
                    filename=form.cleaned_data["file"].name,
                )
                messages.success(
                    request,
                    f"Imported {count} finding{'s' if count != 1 else ''} from {FORMAT_LABELS[fmt]} as Draft.",
                )
                return redirect("findings:list", engagement_id=engagement_id)
            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        form = ScanImportForm()

    return render(
        request, "findings/import.html",
        {
            "engagement": request.engagement, "form": form, "import_target": import_target_section(),
            "breadcrumbs": engagement_crumbs(request.engagement) + [
                {"label": "Findings", "url": reverse("findings:list", args=[request.engagement.pk])},
                {"label": "Import scan"},
            ],
        },
    )
