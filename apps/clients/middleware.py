from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from apps.feature_flags.models import FeatureFlags

_CLIENT_EXEMPT_URL_NAMES = {
    "accounts:login",
    "accounts:logout",
    "accounts:password_change",
    "accounts:password_reset_request",
    "accounts:password_reset_confirm",
    "accounts:mfa_enroll",
    "accounts:mfa_verify",
    "csp_report",
}

_CLIENT_PORTAL_URL_PREFIX = "clients_portal:"


class ClientPortalAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if user is not None and user.is_authenticated and user.is_client_role:
            feature_flags = getattr(request, "feature_flags", None) or FeatureFlags.get_solo()

            if not feature_flags.client_portal_enabled:
                logout(request)
                messages.error(request, "The client portal is currently unavailable. Please try again later.")
                return redirect(reverse("accounts:login"))

            if (
                not request.path.startswith(settings.STATIC_URL)
                and not self._is_allowed_view(request.path)
            ):
                raise PermissionDenied("This page is not part of the client portal.")

        return self.get_response(request)

    def _is_allowed_view(self, path):
        try:
            view_name = resolve(path).view_name
        except Resolver404:
            return False
        return view_name in _CLIENT_EXEMPT_URL_NAMES or view_name.startswith(_CLIENT_PORTAL_URL_PREFIX)
