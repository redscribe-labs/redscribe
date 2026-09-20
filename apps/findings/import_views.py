from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.crypto.access import engagement_access_required
from apps.engagements.breadcrumbs import engagement_crumbs
from apps.feature_flags.models import FeatureFlags

from .forms import ScanImportForm
from .scan_import import FORMAT_LABELS, import_scan


@engagement_access_required
def finding_import(request, engagement_id):
    if not FeatureFlags.get_solo().scan_import:
        raise PermissionDenied("Scan import is currently disabled.")

    if request.method == "POST":
        form = ScanImportForm(request.POST, request.FILES)
        if form.is_valid():
            fmt = form.cleaned_data["format"]
            try:
                count = import_scan(
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
            "engagement": request.engagement, "form": form,
            "breadcrumbs": engagement_crumbs(request.engagement) + [
                {"label": "Findings", "url": reverse("findings:list", args=[request.engagement.pk])},
                {"label": "Import scan"},
            ],
        },
    )
