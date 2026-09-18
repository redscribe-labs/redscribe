from django.http import Http404
from django.urls import include, path

from .csp import csp_report_view
from .health import health


def _blocked_allauth_view(request, *args, **kwargs):
    raise Http404


# include("allauth.urls") below pulls in the *entire* allauth.account app, not just
# the OAuth plumbing RedScribe actually uses (provider login/callback, email
# confirmation, the inactive-account and login-error/cancelled pages) — it also
# registers allauth's own raw login/signup/logout/password-reset/email-management
# views. Those are dead surface here: RedScribe has its own versions of all of them
# (apps.accounts.views/urls), nothing in this codebase links to allauth's, and they
# don't go through RedScribe's lockout/MFA/invite-only machinery. Each is shadowed
# by name below (before the include, so ours wins) rather than removed outright, so
# any internal allauth `reverse()` call by that name still resolves to a valid URL —
# it just 404s instead of serving a redundant, unbranded parallel auth surface.
_BLOCKED_ALLAUTH_URLS = [
    ("accounts/social/login/", "account_login"),
    ("accounts/social/login/code/confirm/", "account_confirm_login_code"),
    ("accounts/social/logout/", "account_logout"),
    ("accounts/social/signup/", "account_signup"),
    ("accounts/social/password/change/", "account_change_password"),
    ("accounts/social/password/set/", "account_set_password"),
    ("accounts/social/password/reset/", "account_reset_password"),
    ("accounts/social/password/reset/done/", "account_reset_password_done"),
    ("accounts/social/password/reset/key/done/", "account_reset_password_from_key_done"),
    ("accounts/social/password/reset/key/<str:uidb36>-<str:key>/", "account_reset_password_from_key"),
    ("accounts/social/reauthenticate/", "account_reauthenticate"),
    ("accounts/social/email/", "account_email"),
    ("accounts/social/3rdparty/", "socialaccount_connections"),
    ("accounts/social/3rdparty/signup/", "socialaccount_signup"),
]

urlpatterns = [
    path("health/", health, name="health"),
    path("csp-report/", csp_report_view, name="csp_report"),
    *(path(pattern, _blocked_allauth_view, name=name) for pattern, name in _BLOCKED_ALLAUTH_URLS),
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
