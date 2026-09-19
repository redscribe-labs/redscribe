from django.conf import settings
from django.db import models


class FeatureFlags(models.Model):
    retest_workflow = models.BooleanField(
        default=True, help_text="Retest/remediation tracking on findings (Fixed/Not Fixed/etc. + history).",
    )
    notifications = models.BooleanField(
        default=True,
        help_text="Reviewer/QA assignment notifications, both in-app and email. Per-user email opt-out "
        "(see accounts:notification_preferences) still applies on top of this.",
    )
    recurrence_and_trends = models.BooleanField(
        default=True,
        help_text="Recurring-vulnerability detection on the finding page, and the cross-engagement Trends page.",
    )
    cvss_calculator = models.BooleanField(
        default=True, help_text="CVSS v3.1/v4.0 calculator widget on the finding create/edit form.",
    )
    global_search = models.BooleanField(
        default=True, help_text="Global search across every engagement/finding the user has access to.",
    )
    scan_import = models.BooleanField(
        default=True, help_text="Scanner import (Nmap / Burp Suite / Nuclei) on the findings list.",
    )

    mfa_required = models.BooleanField(
        default=True,
        help_text="Require TOTP MFA for local accounts. This is the right call before any real "
        "deployment; turn it OFF only for a local/disposable dev or test instance.",
    )

    client_portal_enabled = models.BooleanField(
        default=False,
        help_text="Allow client-role accounts to log in and use the client portal. Managing Client "
        "companies/accounts stays available to Superadmin/Team Lead either way.",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="feature_flag_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Feature flags"

    @classmethod
    def get_solo(cls) -> "FeatureFlags":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
