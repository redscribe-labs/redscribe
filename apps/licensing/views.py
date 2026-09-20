from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.accounts.permissions import require_permission

from .forms import LicenseKeyForm
from .models import LicenseKey
from .status import license_status
from .verify import verify_license_key


@login_required
def license_edit(request):
    require_permission(request.user, "licensing.manage", "manage the license key")

    license_key = LicenseKey.get_solo()

    if request.method == "POST":
        form = LicenseKeyForm(request.POST, instance=license_key)
        if form.is_valid():
            license_key = form.save(commit=False)
            license_key.updated_by = request.user
            license_key.save()
            messages.success(request, "License key updated.")
            return redirect("licensing:edit")
    else:
        form = LicenseKeyForm(instance=license_key)

    return render(
        request, "licensing/edit.html",
        {
            "form": form,
            "status": license_status(verify_license_key(license_key.key_text)),
            "breadcrumbs": [{"label": "Licensing"}],
        },
    )
