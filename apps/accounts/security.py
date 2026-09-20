import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.contrib.sessions.models import Session
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_encode

from .models import LoginAttempt, MFAAttempt, User, UserSession

logger = logging.getLogger(__name__)


@dataclass
class LockoutStatus:
    blocked: bool
    retry_after_seconds: int = 0
    reason: str = ""


def _recent_failed_count(*, username: str, window_seconds: int) -> int:
    since = timezone.now() - timezone.timedelta(seconds=window_seconds)
    qs = LoginAttempt.objects.filter(
        username_attempted=username, successful=False, created_at__gte=since
    )
    last_success = LoginAttempt.objects.filter(
        username_attempted=username, successful=True, created_at__gte=since
    ).order_by("-created_at").first()
    if last_success:
        qs = qs.filter(created_at__gt=last_success.created_at)
    return qs.count()


def check_lockout(*, username: str, is_superadmin: bool) -> LockoutStatus:
    if is_superadmin:
        window = settings.SUPERADMIN_RATE_LIMIT_WINDOW_SECONDS
        threshold = settings.SUPERADMIN_RATE_LIMIT_MAX_ATTEMPTS
        reason = "rate_limited"
    else:
        window = settings.LOCKOUT_DURATION_SECONDS
        threshold = settings.LOCKOUT_THRESHOLD
        reason = "locked_out"

    failed = _recent_failed_count(username=username, window_seconds=window)
    if failed >= threshold:
        return LockoutStatus(blocked=True, retry_after_seconds=window, reason=reason)
    return LockoutStatus(blocked=False)


_LOCK_HOLD_SECONDS = 10
_LOCK_WAIT_SECONDS = 3
_LOCK_POLL_INTERVAL_SECONDS = 0.05


class _LoginAttemptLock:
    def __init__(self, username: str):
        self._key = f"login-attempt-lock:{username}"
        self.acquired = False

    def __enter__(self) -> "_LoginAttemptLock":
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            if cache.add(self._key, "1", timeout=_LOCK_HOLD_SECONDS):
                self.acquired = True
                return self
            time.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.acquired:
            cache.delete(self._key)
        return False


def login_attempt_lock(username: str) -> _LoginAttemptLock:
    return _LoginAttemptLock(username)


def mfa_attempt_lock(user) -> _LoginAttemptLock:
    return _LoginAttemptLock(f"mfa:{user.pk}")


def check_mfa_throttle(user) -> LockoutStatus:
    since = timezone.now() - timezone.timedelta(seconds=settings.MFA_THROTTLE_WINDOW_SECONDS)
    recent = MFAAttempt.objects.filter(user=user, created_at__gte=since).count()
    if recent >= settings.MFA_THROTTLE_MAX_ATTEMPTS:
        return LockoutStatus(
            blocked=True, retry_after_seconds=settings.MFA_THROTTLE_WINDOW_SECONDS, reason="mfa_rate_limited"
        )
    return LockoutStatus(blocked=False)


def record_mfa_attempt(user, *, successful: bool) -> None:
    MFAAttempt.objects.create(user=user, successful=successful)


def record_attempt(
    *,
    username: str,
    user: User | None,
    successful: bool,
    ip_address: str | None,
    auth_method: str = LoginAttempt.AuthMethod.LOCAL,
) -> None:
    LoginAttempt.objects.create(
        username_attempted=username,
        user=user,
        successful=successful,
        auth_method=auth_method,
        ip_address=ip_address,
    )


def maybe_alert_lockout(*, username: str, is_superadmin: bool, ip_address: str | None) -> None:
    threshold = settings.SUPERADMIN_RATE_LIMIT_MAX_ATTEMPTS if is_superadmin else settings.LOCKOUT_THRESHOLD
    window = settings.SUPERADMIN_RATE_LIMIT_WINDOW_SECONDS if is_superadmin else settings.LOCKOUT_DURATION_SECONDS
    failed = _recent_failed_count(username=username, window_seconds=window)
    if failed != threshold:
        return

    recipients = list(
        User.objects.filter(role__is_superadmin=True, is_active=True)
        .exclude(email="").values_list("email", flat=True)
    )
    if not recipients:
        return

    reason = "rate-limited" if is_superadmin else "locked out"
    safe_username = "".join(ch for ch in username if ch not in "\r\n")
    try:
        send_mail(
            subject=f"RedScribe security alert: account {reason} — {safe_username}",
            message=(
                f"The account '{safe_username}' was just {reason} after {failed} failed login "
                f"attempt{'s' if failed != 1 else ''}"
                + (f" from IP {ip_address}" if ip_address else "")
                + ".\n\nNo action is required unless this is unexpected — check the Audit "
                "Log for details."
            ),
            from_email=None,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send lockout security-alert email for username=%r", safe_username)


def invalidate_other_sessions(user: User, *, keep_session_key: str | None = None) -> None:
    # UserSession is a maintained user_id -> session_key index (see its docstring) —
    # avoids decoding every active Session row in the whole application just to find the
    # ones belonging to this one user, which used to run on every login.
    stale = list(UserSession.objects.filter(user=user).exclude(session_key=keep_session_key))
    if stale:
        Session.objects.filter(session_key__in=[row.session_key for row in stale]).delete()
        UserSession.objects.filter(pk__in=[row.pk for row in stale]).delete()
    if keep_session_key:
        UserSession.objects.update_or_create(session_key=keep_session_key, defaults={"user": user})


def client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def send_account_email(*, to_email, subject, template_name, context):
    from apps.reports.branding import get_branding

    context = {**context, "branding": get_branding()}
    body = render_to_string(template_name, context)
    message = EmailMultiAlternatives(subject, body, None, [to_email])
    html_template_name = template_name[: -len(".txt")] + ".html"
    message.attach_alternative(render_to_string(html_template_name, context), "text/html")
    message.send(fail_silently=False)


class AccountSetupTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "apps.accounts.security.AccountSetupTokenGenerator"
    timeout_seconds = 60 * 60 * 24

    def check_token(self, user, token):
        if not (user and token):
            return False
        try:
            ts_b36, _ = token.split("-")
        except ValueError:
            return False
        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
                break
        else:
            return False
        if (self._num_seconds(self._now()) - ts) > self.timeout_seconds:
            return False
        return True


account_setup_token_generator = AccountSetupTokenGenerator()


def send_account_created_email(user: User, request) -> None:
    token = account_setup_token_generator.make_token(user)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    path = reverse("accounts:account_setup_confirm", kwargs={"uidb64": uidb64, "token": token})
    send_account_email(
        to_email=user.email,
        subject="Welcome to RedScribe — set your password",
        template_name="accounts/email/account_created.txt",
        context={"user": user, "setup_url": request.build_absolute_uri(path)},
    )


def send_account_activated_email(user: User) -> None:
    send_account_email(
        to_email=user.email,
        subject="Your RedScribe account is now active",
        template_name="accounts/email/account_activated.txt",
        context={"user": user},
    )


def send_password_reset_email(user: User, request) -> None:
    token = default_token_generator.make_token(user)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    path = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})
    send_account_email(
        to_email=user.email,
        subject="Reset your RedScribe password",
        template_name="accounts/email/password_reset.txt",
        context={"user": user, "reset_url": request.build_absolute_uri(path)},
    )


def is_last_active_superadmin(user: User) -> bool:
    if not user.is_superadmin_role or not user.is_active:
        return False
    return not User.objects.filter(role__is_superadmin=True, is_active=True).exclude(pk=user.pk).exists()
