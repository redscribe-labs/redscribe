from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from . import security

User = get_user_model()


class LockoutAwareModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        ip = security.client_ip(request) if request is not None else None

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            User().set_password(password)
            user = None

        if user is not None and user.auth_type != User.AuthType.LOCAL:
            return None

        is_superadmin = bool(user and user.is_superadmin_role)

        with security.login_attempt_lock(username) as lock:
            if not lock.acquired:
                return None

            status = security.check_lockout(username=username, is_superadmin=is_superadmin)
            if status.blocked:
                return None

            if user is None or not user.is_active:
                security.record_attempt(username=username, user=None, successful=False, ip_address=ip)
                security.maybe_alert_lockout(username=username, is_superadmin=is_superadmin, ip_address=ip)
                return None

            if user.check_password(password) and self.user_can_authenticate(user):
                security.record_attempt(username=username, user=user, successful=True, ip_address=ip)
                return user

            security.record_attempt(username=username, user=user, successful=False, ip_address=ip)
            security.maybe_alert_lockout(username=username, is_superadmin=is_superadmin, ip_address=ip)
            return None
