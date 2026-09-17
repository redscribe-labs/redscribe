import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET
from PIL import Image, UnidentifiedImageError

from apps.accounts.permissions import require_permission

from .forms import FirmBrandingForm
from .models import ReportSettings

_PIL_FORMAT_TO_CONTENT_TYPE = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def _detect_image_content_type(plaintext):
    try:
        with Image.open(io.BytesIO(plaintext)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(plaintext)) as probe:
            return _PIL_FORMAT_TO_CONTENT_TYPE.get(probe.format)
    except (UnidentifiedImageError, OSError, ValueError):
        return None


@login_required
def branding_edit(request):
    require_permission(request.user, "branding.manage", "manage firm branding")
    settings_obj = ReportSettings.get_solo()

    if request.method == "POST":
        form = FirmBrandingForm(request.POST, request.FILES)
        if form.is_valid():
            logo = form.cleaned_data.get("logo")
            logo_plaintext, logo_content_type = None, None
            if logo:
                logo_plaintext = logo.read()
                logo_content_type = _detect_image_content_type(logo_plaintext)
                if logo_content_type is None:
                    form.add_error("logo", "File content doesn't match a supported image format.")

            if not form.errors:
                settings_obj.firm_name = form.cleaned_data["firm_name"]
                if logo:
                    settings_obj.firm_logo = logo_plaintext
                    settings_obj.firm_logo_content_type = logo_content_type
                elif form.cleaned_data.get("remove_logo"):
                    settings_obj.firm_logo = None
                    settings_obj.firm_logo_content_type = ""
                settings_obj.updated_by = request.user
                settings_obj.save()
                messages.success(request, "Firm branding updated.")
                return redirect("branding:edit")
    else:
        form = FirmBrandingForm(initial={"firm_name": settings_obj.firm_name})

    return render(
        request, "reports/branding_edit.html",
        {
            "form": form,
            "has_logo": bool(settings_obj.firm_logo),
            "breadcrumbs": [{"label": "Firm branding"}],
        },
    )


@require_GET
@cache_control(max_age=3600)
def logo(request):
    settings_obj = ReportSettings.get_solo()
    if not settings_obj.firm_logo:
        return HttpResponseNotFound()
    response = HttpResponse(
        bytes(settings_obj.firm_logo), content_type=settings_obj.firm_logo_content_type or "application/octet-stream"
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
