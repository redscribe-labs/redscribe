import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

APP_VERSION = (BASE_DIR / "VERSION").read_text().strip()


def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and val in (None, ""):
        raise RuntimeError(f"Required environment variable {name} is not set")
    return val


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    val = os.environ.get(name, default)
    return [item.strip() for item in val.split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)

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
                    "secret": env("GOOGLE_OAUTH_CLIENT_SECRET", required=True),
                    "key": "",
                }
            ],
        }
    }
elif OAUTH_PROVIDER == "microsoft":
    INSTALLED_APPS.append("allauth.socialaccount.providers.microsoft")
    SOCIALACCOUNT_PROVIDERS = {
        "microsoft": {
            "APPS": [
                {
                    "client_id": env("MICROSOFT_OAUTH_CLIENT_ID", required=True),
                    "secret": env("MICROSOFT_OAUTH_CLIENT_SECRET", required=True),
                    "key": "",
                }
            ],
            "TENANT": env("MICROSOFT_OAUTH_TENANT_ID", "organizations"),
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
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

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

AUDIT_LOG_RETENTION_DAYS = int(env("AUDIT_LOG_RETENTION_DAYS", str(365 * 6)))

BACKUP_DIR = env("BACKUP_DIR", "/app/backups")
BACKUP_ENCRYPTION_PASSPHRASE = env("BACKUP_ENCRYPTION_PASSPHRASE", "")
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
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
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
