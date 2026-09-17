import hashlib
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


class PwnedPasswordValidator:
    _API_URL = "https://api.pwnedpasswords.com/range/{prefix}"
    _TIMEOUT_SECONDS = 3

    def validate(self, password, user=None):
        if not getattr(settings, "PWNED_PASSWORD_CHECK_ENABLED", True):
            return

        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]

        try:
            request = urllib.request.Request(
                self._API_URL.format(prefix=prefix),
                headers={
                    "User-Agent": "RedScribe-PwnedPasswordCheck",
                    "Add-Padding": "true",
                },
            )
            with urllib.request.urlopen(request, timeout=self._TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Pwned Passwords check unavailable, failing open: %s", exc)
            return

        for line in body.splitlines():
            candidate_suffix, _sep, count = line.partition(":")
            if candidate_suffix == suffix and count.strip("\r\n") != "0":
                raise ValidationError(
                    _(
                        "This password has appeared in known data breaches and can't be "
                        "used. Please choose a different password."
                    ),
                    code="password_pwned",
                )

    def get_help_text(self):
        return _("Your password can't be one that's appeared in a known data breach.")


class MaximumLengthValidator:
    def __init__(self, max_length=128):
        self.max_length = max_length

    def validate(self, password, user=None):
        if len(password) > self.max_length:
            raise ValidationError(
                _("This password is too long. It must contain at most %(max_length)d characters."),
                code="password_too_long",
                params={"max_length": self.max_length},
            )

    def get_help_text(self):
        return _("Your password must contain at most %(max_length)d characters.") % {
            "max_length": self.max_length
        }
