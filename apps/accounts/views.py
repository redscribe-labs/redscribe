import base64
import time
from io import BytesIO

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Count
from django.http import HttpResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.feature_flags.models import FeatureFlags

from . import security
from .forms import (
    ForgotPasswordForm, LocalLoginForm, NotificationPreferencesForm, ProfileForm, SuperadminSetupForm, TOTPVerifyForm,
)
from .middleware import mfa_required_for

User = get_user_model()


def _qr_data_uri(data: str) -> str:
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _no_superadmin_yet() -> bool:
    return not User.objects.filter(role__is_superadmin=True).exists()


def _lockout_error_code(form) -> str | None:
    for error in form.errors.as_data().get("__all__", []):
        if error.code in ("locked_out", "rate_limited"):
            return error.code
    return None


def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    status_code = 200
    if request.method == "POST":
        form = LocalLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.is_client_role and not FeatureFlags.get_solo().client_portal_enabled:
                form.add_error(None, LocalLoginForm.error_messages["invalid_login"])
            else:
                auth_login(request, user)
                if not mfa_required_for(user, FeatureFlags.get_solo()):
                    # Fully authenticated already — no MFA step follows, so this is the
                    # moment login completes. If MFA is required, we defer revoking other
                    # sessions to mfa_verify_view/mfa_enroll_view: revoking here, before the
                    # second factor is checked, would let anyone who merely knows the
                    # password (without the MFA code) kick out the legitimate session.
                    security.invalidate_other_sessions(user, keep_session_key=request.session.session_key)
                if user.is_client_role:
                    return redirect("clients_portal:dashboard")
                return redirect("accounts:dashboard")
        if _lockout_error_code(form):
            status_code = 429
    else:
        form = LocalLoginForm(request)

    response = render(
        request, "accounts/login.html",
        {
            "form": form,
            "no_superadmin_yet": _no_superadmin_yet(),
            "oauth_provider": settings.OAUTH_PROVIDER,
        },
        status=status_code,
    )
    if status_code == 429:
        username = request.POST.get("username", "")
        is_superadmin = User.objects.filter(username=username, role__is_superadmin=True).exists()
        window = (
            settings.SUPERADMIN_RATE_LIMIT_WINDOW_SECONDS if is_superadmin
            else settings.LOCKOUT_DURATION_SECONDS
        )
        response["Retry-After"] = str(window)
    return response


def setup_view(request):
    if not _no_superadmin_yet():
        return redirect("accounts:login")

    if request.method == "POST":
        form = SuperadminSetupForm(request.POST)
        if form.is_valid():
            if not _no_superadmin_yet():
                form.add_error(None, "A Superadmin has already been set up for this instance.")
            else:
                user = form.save()
                auth_login(request, user, backend="apps.accounts.backends.LockoutAwareModelBackend")
                messages.success(request, "Superadmin account created.")
                return redirect("accounts:dashboard")
    else:
        form = SuperadminSetupForm()

    return render(request, "accounts/setup.html", {"form": form})


@login_required
def logout_view(request):
    from .models import UserSession

    UserSession.objects.filter(session_key=request.session.session_key).delete()
    auth_logout(request)
    rotate_token(request)
    return redirect("accounts:login")


@login_required
def session_ping(request):
    return HttpResponse(status=204)


@login_required
def password_change_view(request):
    user = request.user
    if user.auth_type != User.AuthType.LOCAL:
        messages.info(
            request,
            "Your account signs in through your organization's identity provider — "
            "there's no local password to change.",
        )
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = PasswordChangeForm(user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, user)
            security.invalidate_other_sessions(user, keep_session_key=request.session.session_key)
            rotate_token(request)
            security.send_account_email(
                to_email=user.email,
                subject="Your RedScribe password was changed",
                template_name="accounts/email/password_changed.txt",
                context={"user": user},
            )
            messages.success(request, "Your password has been changed. Other active sessions were signed out.")
            return redirect("accounts:dashboard")
    else:
        form = PasswordChangeForm(user)

    return render(
        request, "accounts/password_change.html",
        {"form": form, "breadcrumbs": [{"label": "Change password"}]},
    )


@login_required
def notification_preferences_view(request):
    if request.method == "POST":
        form = NotificationPreferencesForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification preferences updated.")
            return redirect("accounts:notification_preferences")
    else:
        form = NotificationPreferencesForm(instance=request.user)

    return render(
        request, "accounts/notification_preferences.html",
        {"form": form, "breadcrumbs": [{"label": "Notification preferences"}]},
    )


@login_required
def profile_view(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    return render(
        request, "accounts/profile.html",
        {"form": form, "breadcrumbs": [{"label": "Profile"}]},
    )


def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            started = time.monotonic()
            user = User.objects.filter(
                email__iexact=email, auth_type=User.AuthType.LOCAL, is_active=True
            ).first()
            if user is not None:
                security.send_password_reset_email(user, request)
            _MIN_RESPONSE_SECONDS = 0.4
            remaining = _MIN_RESPONSE_SECONDS - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
            messages.success(
                request,
                "If an account with that email exists, we've sent a link to reset the password.",
            )
            return redirect("accounts:login")
    else:
        form = ForgotPasswordForm()

    return render(request, "accounts/forgot_password.html", {"form": form})


def account_setup_confirm_view(request, uidb64, token):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid, auth_type=User.AuthType.LOCAL, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is None or not security.account_setup_token_generator.check_token(user, token):
        return render(request, "accounts/account_setup_invalid.html", status=400)

    if request.method == "POST":
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            security.invalidate_other_sessions(user)
            rotate_token(request)
            security.send_account_activated_email(user)
            messages.success(request, "Your password has been set. Please sign in.")
            return redirect("accounts:login")
    else:
        form = SetPasswordForm(user)

    return render(request, "accounts/account_setup_confirm.html", {"form": form})


def password_reset_confirm_view(request, uidb64, token):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid, auth_type=User.AuthType.LOCAL, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "accounts/password_reset_invalid.html", status=400)

    if request.method == "POST":
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            security.invalidate_other_sessions(user)
            rotate_token(request)
            security.send_account_email(
                to_email=user.email,
                subject="Your RedScribe password was reset",
                template_name="accounts/email/password_changed.txt",
                context={"user": user},
            )
            messages.success(request, "Your password has been reset. Please sign in.")
            return redirect("accounts:login")
    else:
        form = SetPasswordForm(user)

    return render(request, "accounts/password_reset_confirm.html", {"form": form})


@login_required
def mfa_enroll_view(request):
    user = request.user
    if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        return redirect("accounts:dashboard")

    device, _ = TOTPDevice.objects.get_or_create(
        user=user, confirmed=False, defaults={"name": "default"}
    )

    status_code = 200
    if request.method == "POST":
        form = TOTPVerifyForm(request.POST)
        with security.mfa_attempt_lock(user):
            throttle = security.check_mfa_throttle(user)
            if throttle.blocked:
                form.add_error("token", "Too many attempts. Please wait and try again.")
                status_code = 429
            else:
                verified = form.is_valid() and device.verify_token(form.cleaned_data["token"])
                security.record_mfa_attempt(user, successful=verified)
                if verified:
                    device.confirmed = True
                    device.save(update_fields=["confirmed"])
                    user.mfa_enrolled_at = timezone.now()
                    user.save(update_fields=["mfa_enrolled_at"])
                    otp_login(request, device)
                    if mfa_required_for(user, FeatureFlags.get_solo()):
                        # This account's role/instance requires MFA, so reaching this view
                        # at all means the account had no confirmed device yet and this was
                        # a forced first step of a fresh login (MFAEnforcementMiddleware
                        # blocks every other page until it's done) — revoke other sessions
                        # now that login is actually complete. When MFA isn't required this
                        # is a voluntary opt-in from an already-logged-in user, not a login
                        # event, so their other sessions are left alone.
                        security.invalidate_other_sessions(user, keep_session_key=request.session.session_key)
                    messages.success(request, "MFA enabled for your account.")
                    return redirect("accounts:dashboard")
                form.add_error("token", "That code didn't match. Please try again.")
    else:
        form = TOTPVerifyForm()

    return render(
        request,
        "accounts/mfa_enroll.html",
        {"form": form, "otpauth_url": device.config_url, "qr_data_uri": _qr_data_uri(device.config_url)},
        status=status_code,
    )


@login_required
def mfa_verify_view(request):
    user = request.user
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        return redirect("accounts:mfa_enroll")
    if request.user.is_verified():
        return redirect("accounts:dashboard")

    status_code = 200
    if request.method == "POST":
        form = TOTPVerifyForm(request.POST)
        with security.mfa_attempt_lock(user):
            throttle = security.check_mfa_throttle(user)
            if throttle.blocked:
                form.add_error("token", "Too many attempts. Please wait and try again.")
                status_code = 429
            else:
                verified = form.is_valid() and device.verify_token(form.cleaned_data["token"])
                security.record_mfa_attempt(user, successful=verified)
                if verified:
                    otp_login(request, device)
                    security.invalidate_other_sessions(user, keep_session_key=request.session.session_key)
                    return redirect("accounts:dashboard")
                form.add_error("token", "That code didn't match. Please try again.")
    else:
        form = TOTPVerifyForm()

    return render(request, "accounts/mfa_verify.html", {"form": form}, status=status_code)


WORKFLOW_COLORS = {
    "DRAFT": "bg-slate-400",
    "REVIEWED": "bg-bell-500",
    "REVIEW_CHANGES_REQUESTED": "bg-amber-500",
    "QA_APPROVED": "bg-green-600",
    "QA_CHANGES_REQUESTED": "bg-amber-500",
}


def _severity_bar_style(severity_value):
    from apps.reports.colors import severity_rgba

    return f"background-color:{severity_rgba(severity_value, 'open')}"


def _chart_data(queryset, field, choices, colors=None, severity_style=False):
    counts = {row[field]: row["n"] for row in queryset.values(field).annotate(n=Count("id"))}
    total = sum(counts.values())
    data = []
    for value, label in choices:
        count = counts.get(value, 0)
        if count == 0:
            continue
        pct = round(count / total * 100) if total else 0
        row = {"label": label, "count": count, "pct": pct}
        if severity_style:
            row["style"] = _severity_bar_style(value)
        else:
            row["color"] = colors.get(value, "bg-slate-400")
        data.append(row)
    return data


@login_required
def dashboard_view(request):
    from apps.engagements.access import visible_engagements
    from apps.findings.models import Finding

    user = request.user
    engagements = visible_engagements(user)
    my_findings = Finding.objects.filter(created_by=user)

    to_review_count = Finding.objects.filter(
        assigned_reviewer=user,
        workflow_status__in=[Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED],
    ).count()
    to_qa_count = Finding.objects.filter(
        assigned_qa=user,
        workflow_status__in=[Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED],
    ).count()

    context = {
        "engagement_count": engagements.count(),
        "active_engagement_count": engagements.filter(archived=False).count(),
        "recent_engagements": engagements.order_by("-created_at")[:5],
        "my_finding_count": my_findings.count(),
        "my_severity_chart": _chart_data(my_findings, "severity", Finding.Severity.choices, severity_style=True),
        "my_status_chart": _chart_data(
            my_findings, "workflow_status", Finding.WorkflowStatus.choices, WORKFLOW_COLORS
        ),
        "to_review_count": to_review_count,
        "to_qa_count": to_qa_count,
    }

    if user.has_permission("engagements.view_all"):
        org_findings = Finding.objects.filter(engagement__in=engagements)
        context.update({
            "is_manager_view": True,
            "org_finding_count": org_findings.count(),
            "org_severity_chart": _chart_data(
                org_findings, "severity", Finding.Severity.choices, severity_style=True
            ),
            "needs_reviewer_count": org_findings.filter(
                workflow_status=Finding.WorkflowStatus.DRAFT, assigned_reviewer__isnull=True
            ).count(),
            "needs_qa_count": org_findings.filter(
                workflow_status=Finding.WorkflowStatus.REVIEWED, assigned_qa__isnull=True
            ).count(),
        })

    return render(request, "accounts/dashboard.html", context)
