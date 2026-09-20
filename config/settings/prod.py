import os

from .base import *  # noqa: F401,F403

if DEBUG and not env_bool("REDSCRIBE_ALLOW_DEBUG_IN_PROD"):
    raise RuntimeError(
        "DJANGO_DEBUG=true with config.settings.prod — this would show full "
        "debug tracebacks (source, local variables, settings/secrets) to any "
        "visitor who triggers a 500. If this is genuinely intentional (e.g. "
        "temporary diagnosis), set REDSCRIBE_ALLOW_DEBUG_IN_PROD=1 as well."
    )

from apps.crypto.root_key import (  # noqa: E402
    DEFAULT_ROOT_KEY_FILE,
    ROOT_KEY_FILE_ENV_VAR,
)

_root_key_file = os.environ.get(ROOT_KEY_FILE_ENV_VAR, DEFAULT_ROOT_KEY_FILE)
if not os.environ.get("REDSCRIBE_ROOT_KEY") and not (
    _root_key_file and os.path.isfile(_root_key_file)
):
    raise RuntimeError(
        "No root key found — generate one with `python manage.py "
        "generate_root_key`, then either mount it as a Docker secret (see "
        "docker-compose.yml) or set REDSCRIBE_ROOT_KEY before deploying."
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_REDIRECT_EXEMPT = [r"^health/$"]

STORAGES["staticfiles"] = {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}
