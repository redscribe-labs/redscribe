import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.feature_flags.models import FeatureFlags

_IDLE_SESSION_KEY = "last_activity_ts"

_IDLE_EXEMPT_URL_NAMES = {"accounts:login", "accounts:logout"}

_IDLE_NON_ACTIVITY_URL_NAMES = {"accounts:session_ping"}


class IdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if (
            user is not None and user.is_authenticated
            and request.path not in self._exempt_paths()
            and not request.path.startswith(settings.STATIC_URL)
        ):
            now = time.time()
            last_activity = request.session.get(_IDLE_SESSION_KEY)
            expired = last_activity is not None and (
                now - last_activity > settings.SESSION_IDLE_TIMEOUT_SECONDS or last_activity > now
            )
            if expired:
                from .models import UserSession

                UserSession.objects.filter(session_key=request.session.session_key).delete()
                logout(request)
                messages.info(request, "You were signed out after a period of inactivity.")
                return redirect(reverse("accounts:login"))
            if request.path not in self._non_activity_paths():
                request.session[_IDLE_SESSION_KEY] = now

        return self.get_response(request)

    def _exempt_paths(self):
        return {reverse(name) for name in _IDLE_EXEMPT_URL_NAMES}

    def _non_activity_paths(self):
        return {reverse(name) for name in _IDLE_NON_ACTIVITY_URL_NAMES}

_EXEMPT_URL_NAMES = {
    "accounts:mfa_enroll",
    "accounts:mfa_verify",
    "accounts:logout",
    "accounts:session_ping",
}


def mfa_required_for(user, feature_flags) -> bool:
    """Whether this user's account must pass TOTP MFA before using the app —
    either instance-wide (`feature_flags.mfa_required`) or because their
    role hard-requires it (`Role.requires_mfa`, e.g. Superadmin)."""
    return (
        bool(user) and user.is_authenticated and user.auth_type == user.AuthType.LOCAL
        and (feature_flags.mfa_required or getattr(user.role, "requires_mfa", False))
    )


def mfa_satisfied(user, feature_flags) -> bool:
    """Whether it's safe to show this user authenticated content — either
    their account doesn't require MFA, or they've already passed it this
    session. Used by templates to keep UI gating in sync with
    MFAEnforcementMiddleware's actual enforcement below."""
    if not bool(user) or not user.is_authenticated:
        return True
    if not mfa_required_for(user, feature_flags):
        return True
    return user.is_verified()


class MFAEnforcementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        request.feature_flags = FeatureFlags.get_solo()

        if mfa_required_for(user, request.feature_flags):
            if request.path not in self._exempt_paths() and not request.path.startswith(settings.STATIC_URL):
                has_confirmed_device = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
                if not has_confirmed_device:
                    return redirect(reverse("accounts:mfa_enroll"))
                if not request.user.is_verified():
                    return redirect(reverse("accounts:mfa_verify"))

        return self.get_response(request)

    def _exempt_paths(self):
        return {reverse(name) for name in _EXEMPT_URL_NAMES}
