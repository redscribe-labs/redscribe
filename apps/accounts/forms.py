from django import forms
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

from apps.findings.forms import RichTextField

from . import security
from .models import Role

User = get_user_model()


class LocalLoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, strip=False)

    error_messages = {
        "invalid_login": "Invalid username or password.",
        "locked_out": "This account is temporarily locked due to repeated failed "
        "attempts. Please try again in a few minutes.",
        "rate_limited": "Too many attempts in a short period. Please wait a moment "
        "and try again.",
    }

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            try:
                candidate = User.objects.get(username=username)
                is_superadmin = candidate.is_superadmin_role
            except User.DoesNotExist:
                is_superadmin = False

            status = security.check_lockout(username=username, is_superadmin=is_superadmin)
            if status.blocked:
                raise forms.ValidationError(
                    self.error_messages[status.reason], code=status.reason
                )

            self.user_cache = authenticate(self.request, username=username, password=password)
            if self.user_cache is None:
                raise forms.ValidationError(
                    self.error_messages["invalid_login"], code="invalid_login"
                )
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class TOTPVerifyForm(forms.Form):
    token = forms.CharField(
        max_length=6, min_length=6, label="6-digit authentication code",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(label="Email address")


def _staff_role_queryset(requesting_user):
    qs = Role.objects.exclude(slug="client")
    if not (requesting_user and requesting_user.is_superadmin_role):
        qs = qs.exclude(is_superadmin=True)
    return qs


def oauth_domain_mismatch(email: str) -> str | None:
    """Returns an error message if `email` can't ever be claimed via OAuth on this
    instance (i.e. doesn't match OAUTH_ALLOWED_DOMAIN, when one is set), else None."""
    domain = settings.OAUTH_ALLOWED_DOMAIN
    if not domain or not email:
        return None
    email_domain = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    if email_domain == domain:
        return None
    return (
        f"This invite can only be claimed by an @{domain} address — an account with this "
        "email could never sign in through the identity provider."
    )


class LocalUserCreateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "role"]

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"] = forms.ModelChoiceField(
            queryset=_staff_role_queryset(requesting_user), label="Role"
        )

    @property
    def creates_oauth_invite(self) -> bool:
        return bool(settings.OAUTH_PROVIDER)

    def clean(self):
        cleaned_data = super().clean()
        if not self.creates_oauth_invite:
            return cleaned_data

        role = cleaned_data.get("role")
        if role is not None and role.is_superadmin:
            self.add_error(
                "role",
                "Superadmin can't be created as an OAuth invite from this form — use the "
                "'bootstrap_superadmin' management command instead.",
            )

        email = cleaned_data.get("email")
        mismatch = oauth_domain_mismatch(email)
        if mismatch:
            self.add_error("email", mismatch)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.creates_oauth_invite and not user.role.is_superadmin:
            user.auth_type = User.AuthType.OAUTH
            user.oauth_invite_pending = True
        else:
            user.auth_type = User.AuthType.LOCAL
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class NotificationPreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email_notifications_enabled"]


class ProfileForm(forms.ModelForm):
    qualifications = RichTextField(
        required=False, label="Qualifications / certifications",
        help_text="Shown as a bulleted list in the report's Assessment team section.",
    )
    background = RichTextField(
        required=False, help_text="A short professional bio — shown under your name in the same section.",
    )

    class Meta:
        model = User
        fields = ["qualifications", "background"]


class LocalUserEditForm(forms.ModelForm):
    qualifications = RichTextField(
        required=False, label="Qualifications / certifications",
        help_text="Shown as a bulleted list in the report's Assessment team section.",
    )
    background = RichTextField(
        required=False, help_text="A short professional bio — shown under their name in the same section.",
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "role", "qualifications", "background"]

    def __init__(self, *args, requesting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"] = forms.ModelChoiceField(
            queryset=_staff_role_queryset(requesting_user), label="Role"
        )

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        if (
            role is not None
            and role.is_superadmin
            and self.instance.auth_type == User.AuthType.OAUTH
        ):
            self.add_error(
                "role",
                "Superadmin is local-auth only — this account can't be given the Superadmin "
                "role while it's an OAuth account.",
            )
        return cleaned_data


class SuperadminSetupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "email"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.auth_type = User.AuthType.LOCAL
        user.role = Role.objects.get(is_superadmin=True)
        user.is_staff = True
        user.is_superuser = True
        if commit:
            user.save()
        return user
