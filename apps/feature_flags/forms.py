from django import forms

from .models import FeatureFlags


class FeatureFlagsForm(forms.ModelForm):
    class Meta:
        model = FeatureFlags
        fields = [
            "retest_workflow", "notifications", "recurrence_and_trends",
            "cvss_calculator", "global_search", "scan_import", "mfa_required",
            "client_portal_enabled",
        ]
