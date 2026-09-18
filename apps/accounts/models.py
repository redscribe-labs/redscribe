import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Permission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codename = models.CharField(max_length=100, unique=True, editable=False)
    label = models.CharField(max_length=200, editable=False)
    category = models.CharField(max_length=50, editable=False)

    class Meta:
        ordering = ["category", "label"]

    def __str__(self):
        return self.label


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True, editable=False)
    is_builtin = models.BooleanField(default=False, editable=False)
    is_superadmin = models.BooleanField(default=False, editable=False)
    requires_mfa = models.BooleanField(
        default=False,
        help_text="Local accounts with this role must enroll in TOTP MFA, even if the instance-wide "
        "'Require MFA' feature flag is off.",
    )
    permissions = models.ManyToManyField(Permission, blank=True, related_name="roles")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def has_permission(self, codename: str) -> bool:
        if self.is_superadmin:
            return True
        return self.permissions.filter(codename=codename).exists()

    @staticmethod
    def unique_slug_from_name(name: str) -> str:
        base = slugify(name)[:50] or "role"
        slug = base
        suffix = 2
        while Role.objects.filter(slug=slug).exists():
            suffix_str = f"-{suffix}"
            slug = f"{base[: 50 - len(suffix_str)]}{suffix_str}"
            suffix += 1
        return slug


class _BuiltinRoleSlug:
    SUPERADMIN = "SUPERADMIN"
    TEAM_LEAD = "TEAM_LEAD"
    SENIOR = "SENIOR"
    CONSULTANT = "CONSULTANT"


class User(AbstractUser):
    class AuthType(models.TextChoices):
        LOCAL = "LOCAL", "Local username/password"
        OAUTH = "OAUTH", "OAuth"

    role = models.ForeignKey("accounts.Role", on_delete=models.PROTECT, related_name="users")

    Role = _BuiltinRoleSlug
    auth_type = models.CharField(max_length=10, choices=AuthType.choices, default=AuthType.LOCAL)
    oauth_invite_pending = models.BooleanField(
        default=False,
        help_text="True for an admin-pre-created OAuth account that has not yet been claimed "
        "by a matching first sign-in through the identity provider.",
    )

    email = models.EmailField(unique=True)

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    mfa_enrolled_at = models.DateTimeField(null=True, blank=True)

    deactivated_at = models.DateTimeField(null=True, blank=True)

    email_notifications_enabled = models.BooleanField(default=True)

    client = models.ForeignKey(
        "clients.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="portal_users",
    )

    qualifications = models.TextField(blank=True, default="")
    background = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def qualifications_list(self) -> list[str]:
        return [line.strip() for line in self.qualifications.splitlines() if line.strip()]

    @property
    def is_superadmin_role(self):
        return self.role.is_superadmin

    @property
    def is_team_lead_role(self):
        return self.role.slug == "team_lead"

    @property
    def is_senior_role(self):
        return self.role.slug == "senior"

    @property
    def is_consultant_role(self):
        return self.role.slug == "consultant"

    @property
    def is_client_role(self):
        return self.role.slug == "client"

    def has_permission(self, codename: str) -> bool:
        return self.role.has_permission(codename)

    def deactivate(self):
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=["is_active", "deactivated_at"])

    def reactivate(self):
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=["is_active", "deactivated_at"])


class LoginAttempt(models.Model):
    class AuthMethod(models.TextChoices):
        LOCAL = "local", "Local"
        OAUTH = "oauth", "OAuth"

    username_attempted = models.CharField(max_length=150)
    user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="login_attempts"
    )
    successful = models.BooleanField()
    auth_method = models.CharField(max_length=8, choices=AuthMethod.choices, default=AuthMethod.LOCAL)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["username_attempted", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        outcome = "success" if self.successful else "failure"
        return f"{self.username_attempted} @ {self.created_at:%Y-%m-%d %H:%M:%S} ({outcome})"


class MFAAttempt(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="mfa_attempts")
    successful = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        outcome = "success" if self.successful else "failure"
        return f"{self.user_id} @ {self.created_at:%Y-%m-%d %H:%M:%S} ({outcome})"


class UserSession(models.Model):
    """A thin user_id -> session_key index, since Django's own Session model has no
    queryable user reference (session_data is an opaque encoded blob) — without this,
    finding "every other active session for user X" means decoding every active session
    in the whole application. Maintained by security.invalidate_other_sessions(), which is
    the single choke point every login path already calls — no other call site needs to
    know this table exists. Self-healing: a row can go stale (its Session logged out or
    expired through some other path) without causing incorrect behavior, since the next
    time this same user logs in, invalidate_other_sessions clears every row for that user
    except the one being kept, stale or not."""

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="tracked_sessions")
    session_key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id} @ {self.session_key}"
