from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from . import security
from .models import LoginAttempt


@receiver(user_logged_in)
def record_oauth_login(sender, request, user, **kwargs):
    backend_path = getattr(user, "backend", "")
    if backend_path.endswith("LockoutAwareModelBackend"):
        return

    security.record_attempt(
        username=user.username,
        user=user,
        successful=True,
        ip_address=security.client_ip(request) if request is not None else None,
        auth_method=LoginAttempt.AuthMethod.OAUTH,
    )
    # OAuth accounts never go through the local MFA gate (see mfa_required_for), so unlike
    # the local login views, this signal firing always means the login is fully complete.
    #
    # Unconditional call, matching the local-auth views exactly — do NOT gate this on
    # request.session.session_key being truthy. Django's own login() takes a different
    # branch (session.flush(), which explicitly clears session_key back to None) instead of
    # cycle_key() whenever the browser's existing session already belongs to a different
    # authenticated user (e.g. a shared/kiosk browser where someone else was logged in
    # without logging out first) — session_key legitimately reads None at this exact point
    # in that case. Passing keep_session_key=None here is still correct and safe: nothing
    # in the sessions table has session_key=None to wrongly protect, the current request's
    # own session row doesn't exist yet (it's created later when SessionMiddleware saves
    # the response), and every *other* session belonging to this user still gets found and
    # deleted by user id, which is the whole point. A prior version of this guard skipped
    # the call entirely whenever session_key was falsy, silently defeating single-session
    # enforcement for exactly this shared-browser case.
    if request is not None:
        security.invalidate_other_sessions(user, keep_session_key=request.session.session_key)
