from django.urls import include, path

from .csp import csp_report_view
from .health import health

urlpatterns = [
    path("health/", health, name="health"),
    path("csp-report/", csp_report_view, name="csp_report"),
    path("accounts/social/", include("allauth.urls")),
    path("engagements/", include("apps.engagements.urls")),
    path("engagements/", include("apps.findings.urls")),
    path("engagements/", include("apps.crypto.urls")),
    path("engagements/", include("apps.checklist.urls")),
    path("engagements/", include("apps.reports.urls")),
    path("catalogue/", include("apps.findings.catalogue_urls")),
    path("reviews/", include("apps.findings.queue_urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("search/", include("apps.search.urls")),
    path("checklist-templates/", include("apps.checklist.template_urls")),
    path("report-profiles/", include("apps.reports.profile_urls")),
    path("branding/", include("apps.reports.branding_urls")),
    path("trends/", include("apps.reports.trends_urls")),
    path("feature-flags/", include("apps.feature_flags.urls")),
    path("licensing/", include("apps.licensing.urls")),
    path("field-visibility/", include("apps.findings.field_visibility_urls")),
    path("audit/", include("apps.audit.urls")),
    path("user-management/", include("apps.accounts.user_management_urls")),
    path("roles/", include("apps.accounts.role_management_urls")),
    path("clients/", include("apps.clients.urls")),
    path("portal/", include("apps.clients.portal_urls")),
    path("", include("apps.accounts.urls")),
]
