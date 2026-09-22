import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

APP_VERSION = (BASE_DIR / "VERSION").read_text().strip()


def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and val in (None, ""):
        raise RuntimeError(f"Required environment variable {name} is not set")
    return val


def env_secret(name, default=None, required=False):
    # Same Docker-secret convention as REDSCRIBE_ROOT_KEY (apps/crypto/root_key.py):
    # a file named by <NAME>_FILE beats the plain env var, since an env var is
    # readable via `docker inspect`/`/proc/<pid>/environ` by any root/same-UID
    # process on the host, while a mounted secret file's access is controlled
    # by the mount itself. The plain var remains a supported fallback for
    # non-Docker/bare-metal deployments and CI, where there's no secret to mount.
    file_path = os.environ.get(f"{name}_FILE")
    if file_path and os.path.isfile(file_path):
        with open(file_path) as f:
            val = f.read().strip()
    else:
        val = os.environ.get(name, default)
    if required and val in (None, ""):
        raise RuntimeError(
            f"Required secret {name} is not set (checked {name}_FILE, then {name})"
        )
    return val


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    val = os.environ.get(name, default)
    return [item.strip() for item in val.split(",") if item.strip()]


SECRET_KEY = env_secret("DJANGO_SECRET_KEY", required=True)

DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

LICENSE_SIGNING_PUBLIC_KEY = env(
    "LICENSE_SIGNING_PUBLIC_KEY",
    default="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBxsVm0Bfb0V9iIwYqzAQN8HaKh7YdZYY3AhpBFWCm+Q",
)

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "apps.accounts",
    "apps.engagements",
    "apps.crypto",
    "apps.findings",
    "apps.checklist",
    "apps.reports",
    "apps.audit",
    "apps.notifications",
    "apps.search",
    "apps.feature_flags",
    "apps.backup",
    "apps.clients",
    "apps.licensing",
]

OAUTH_PROVIDER = env("OAUTH_PROVIDER", "")

OAUTH_ALLOWED_DOMAIN = env("OAUTH_ALLOWED_DOMAIN", "").strip().lower()

if OAUTH_PROVIDER == "google":
    INSTALLED_APPS.append("allauth.socialaccount.providers.google")
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APPS": [
                {
                    "client_id": env("GOOGLE_OAUTH_CLIENT_ID", required=True),
                    "secret": env_secret("GOOGLE_OAUTH_CLIENT_SECRET", required=True),
                    "key": "",
                }
            ],
            # Without this, Google silently reuses whichever Google account already
            # has an active session in the browser, skipping the account chooser
            # entirely — surprising when someone has multiple Google accounts signed
            # in (e.g. personal + work) and clicks "Sign in with Google" expecting to
            # pick one, especially relevant given OAUTH_ALLOWED_DOMAIN only rejects
            # the wrong account *after* it's already been silently chosen.
            "AUTH_PARAMS": {"prompt": "select_account"},
        }
    }
elif OAUTH_PROVIDER == "microsoft":
    INSTALLED_APPS.append("allauth.socialaccount.providers.microsoft")
    SOCIALACCOUNT_PROVIDERS = {
        "microsoft": {
            "APPS": [
                {
                    "client_id": env("MICROSOFT_OAUTH_CLIENT_ID", required=True),
                    "secret": env_secret("MICROSOFT_OAUTH_CLIENT_SECRET", required=True),
                    "key": "",
                }
            ],
            "TENANT": env("MICROSOFT_OAUTH_TENANT_ID", "organizations"),
            # Same reasoning as Google's AUTH_PARAMS above. allauth's Microsoft
            # provider only forces this on its own for a re-authentication request —
            # setting it here forces the account picker on every ordinary sign-in too.
            "AUTH_PARAMS": {"prompt": "select_account"},
        }
    }
elif OAUTH_PROVIDER:
    raise RuntimeError(
        f"Unsupported OAUTH_PROVIDER={OAUTH_PROVIDER!r}; must be 'google', "
        "'microsoft', or unset."
    )

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.accounts.middleware.IdleTimeoutMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.MFAEnforcementMiddleware",
    "apps.clients.middleware.ClientPortalAccessMiddleware",
    "apps.audit.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.unread_count",
                "apps.feature_flags.context_processors.flags",
                "apps.reports.context_processors.branding",
                "apps.licensing.context_processors.license_info",
                "config.context_processors.app_version",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "redscribe"),
        "USER": env("POSTGRES_USER", "redscribe"),
        "PASSWORD": env_secret("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        # Default "prefer" matches psycopg's own default and is fine for the
        # shipped docker-compose.yml topology, where `db` and `web` only
        # ever talk over the Docker-internal network, never a real network
        # hop. It silently allows a plaintext fallback and doesn't validate
        # the server certificate, though, so if POSTGRES_HOST ever points
        # at a separate host (see dev/scaling's "move Postgres onto its own
        # host" as the next step past a single box), set this to
        # "verify-full" and configure POSTGRES_SSLROOTCERT to match.
        "OPTIONS": {"sslmode": env("POSTGRES_SSLMODE", "prefer")},
    }
}
if env("POSTGRES_SSLROOTCERT", ""):
    DATABASES["default"]["OPTIONS"]["sslrootcert"] = env("POSTGRES_SSLROOTCERT", "")

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.LockoutAwareModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

PWNED_PASSWORD_CHECK_ENABLED = env_bool("PWNED_PASSWORD_CHECK_ENABLED", True)

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 14},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "apps.accounts.password_validators.MaximumLengthValidator",
        "OPTIONS": {"max_length": 128},
    },
    {
        "NAME": "apps.accounts.password_validators.PwnedPasswordValidator",
    },
]

PASSWORD_RESET_TIMEOUT = int(env("PASSWORD_RESET_TIMEOUT_SECONDS", str(60 * 60)))

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# 6 years (2190 days). There's no single audit-log-specific retention rule
# here, but 6 years matches HIPAA's retention period for *required
# documentation* generally (45 CFR 164.316(b)(2)(i): 6 years from creation
# or last effective date, whichever is later) and is the most conservative
# of the commonly-referenced regimes for this kind of tool:
#   - PCI DSS v4.0 (10.5.1): at least 1 year, 3 months immediately available
#   - CIS Controls v8 (8.10): at least 90 days
#   - NIST SP 800-53 (AU-11): organization-defined, no fixed minimum
# Override per your own compliance obligations — shortening this may not
# satisfy whichever regime actually applies to your deployment.
AUDIT_LOG_RETENTION_DAYS = int(env("AUDIT_LOG_RETENTION_DAYS", str(365 * 6)))

BACKUP_DIR = env("BACKUP_DIR", "/app/backups")
BACKUP_ENCRYPTION_PASSPHRASE = env_secret("BACKUP_ENCRYPTION_PASSPHRASE", "")
BACKUP_RETENTION_DAYS = int(env("BACKUP_RETENTION_DAYS", "30"))

LOCKOUT_THRESHOLD = int(env("LOCKOUT_THRESHOLD", "5"))
LOCKOUT_DURATION_SECONDS = int(env("LOCKOUT_DURATION_SECONDS", str(24 * 60 * 60)))
SUPERADMIN_RATE_LIMIT_WINDOW_SECONDS = int(
    env("SUPERADMIN_RATE_LIMIT_WINDOW_SECONDS", "60")
)
SUPERADMIN_RATE_LIMIT_MAX_ATTEMPTS = int(
    env("SUPERADMIN_RATE_LIMIT_MAX_ATTEMPTS", "10")
)

MFA_THROTTLE_MAX_ATTEMPTS = int(env("MFA_THROTTLE_MAX_ATTEMPTS", "5"))
MFA_THROTTLE_WINDOW_SECONDS = int(env("MFA_THROTTLE_WINDOW_SECONDS", "30"))

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_secret("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "RedScribe <no-reply@redscribe.local>")

if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SITE_ID = 1
ACCOUNT_ADAPTER = "apps.accounts.adapters.SingleRoleAccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SingleProviderSocialAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# Our own login page already presents an explicit, styled "Sign in with
# Google/Microsoft" button — that click *is* the user's confirmation, so
# skip allauth's own unbranded intermediate "Continue?" page (GET would
# otherwise render it) and go straight to the provider.
SOCIALACCOUNT_LOGIN_ON_GET = True
# Without this, allauth prefixes every subject it sends (e.g. the email-confirmation
# message) with "[<site name>] " using django.contrib.sites — which isn't installed
# here, so it'd fall back to the raw request host (e.g. "[redscribe.example.com] ").
# RedScribe's own emails never do this; our own templates already say who they're
# from, so there's nothing this prefix would add.
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""

LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Brisbane"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SESSION_COOKIE_AGE = 60 * 60 * 4

# 30 minutes. HIPAA's Security Rule requires "automatic logoff" as an
# addressable implementation specification (45 CFR 164.312(a)(2)(iii)) but
# doesn't mandate a specific interval; 30 minutes is a commonly used
# baseline for a tool handling client security/health-adjacent findings.
# Tune this to your own risk assessment via the env var below.
SESSION_IDLE_TIMEOUT_SECONDS = int(env("SESSION_IDLE_TIMEOUT_SECONDS", str(30 * 60)))

CSRF_COOKIE_AGE = SESSION_COOKIE_AGE

DJANGO_LOG_LEVEL = env("DJANGO_LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": DJANGO_LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
