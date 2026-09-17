from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.accounts.permissions import require_permission

from .forms import FeatureFlagsForm
from .models import FeatureFlags


@login_required
def flags_edit(request):
    require_permission(request.user, "feature_flags.manage", "manage feature flags")

    flags = FeatureFlags.get_solo()

    if request.method == "POST":
        form = FeatureFlagsForm(request.POST, instance=flags)
        if form.is_valid():
            flags = form.save(commit=False)
            flags.updated_by = request.user
            flags.save()
            messages.success(request, "Feature flags updated.")
            return redirect("feature_flags:edit")
    else:
        form = FeatureFlagsForm(instance=flags)

    return render(
        request, "feature_flags/edit.html",
        {"form": form, "breadcrumbs": [{"label": "Feature Flags"}]},
    )
