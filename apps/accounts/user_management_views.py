from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

PAGE_SIZE = 10

from apps.findings.review import assignments_for_user

from . import security
from .forms import LocalUserCreateForm, LocalUserEditForm
from .models import LoginAttempt
from .permissions import require_permission

User = get_user_model()


def _require_users_manage(user):
    require_permission(user, "users.manage", "manage users")


def _get_staff_target(user_uuid, **extra):
    return get_object_or_404(User.objects.exclude(role__slug="client"), uuid=user_uuid, **extra)


@login_required
def user_list(request):
    _require_users_manage(request.user)
    query = request.GET.get("q", "").strip()
    users = User.objects.all()
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    page_obj = Paginator(users, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request, "accounts/user_management/list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "breadcrumbs": [{"label": "User Management"}],
        },
    )


@login_required
def user_create(request):
    _require_users_manage(request.user)

    if request.method == "POST":
        form = LocalUserCreateForm(request.POST, requesting_user=request.user)
        if form.is_valid():
            user = form.save()
            if user.auth_type == User.AuthType.OAUTH:
                messages.success(
                    request,
                    f"Account '{user.username}' created as a pending OAuth invite — they'll get "
                    f"access the first time they sign in with {user.email} through "
                    f"{settings.OAUTH_PROVIDER}.",
                )
            else:
                security.send_account_created_email(user, request)
                messages.success(request, f"Account '{user.username}' created.")
            return redirect("user_management:detail", user_uuid=user.uuid)
    else:
        form = LocalUserCreateForm(requesting_user=request.user)

    return render(
        request, "accounts/user_management/create.html",
        {
            "form": form,
            "breadcrumbs": [
                {"label": "User Management", "url": reverse("user_management:list")},
                {"label": "New user"},
            ],
        },
    )


@login_required
def user_detail(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid)
    recent_attempts = LoginAttempt.objects.filter(user=target)[:10]
    has_confirmed_mfa = TOTPDevice.objects.filter(user=target, confirmed=True).exists()

    return render(
        request, "accounts/user_management/detail.html",
        {
            "target": target,
            "recent_attempts": recent_attempts,
            "has_confirmed_mfa": has_confirmed_mfa,
            "is_self": target.pk == request.user.pk,
            "is_last_active_superadmin": security.is_last_active_superadmin(target),
            "oauth_provider": settings.OAUTH_PROVIDER,
            "breadcrumbs": [
                {"label": "User Management", "url": reverse("user_management:list")},
                {"label": target.username},
            ],
        },
    )


@login_required
def user_edit(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid)
    is_self = target.pk == request.user.pk

    if request.method == "POST":
        form = LocalUserEditForm(request.POST, instance=target, requesting_user=request.user)
        if is_self:
            form.fields["role"].disabled = True
        if form.is_valid():
            new_role = form.cleaned_data.get("role", target.role)
            if new_role != target.role and security.is_last_active_superadmin(target):
                form.add_error(
                    "role",
                    "This is the last active Superadmin — change another account's role "
                    "to Superadmin first, or this instance will have no Superadmin left.",
                )
            else:
                form.save()
                messages.success(request, f"'{target.username}' updated.")
                return redirect("user_management:detail", user_uuid=target.uuid)
    else:
        form = LocalUserEditForm(instance=target, requesting_user=request.user)
        if is_self:
            form.fields["role"].disabled = True

    return render(
        request, "accounts/user_management/edit.html",
        {
            "form": form,
            "target": target,
            "is_self": is_self,
            "breadcrumbs": [
                {"label": "User Management", "url": reverse("user_management:list")},
                {"label": target.username, "url": reverse("user_management:detail", args=[target.uuid])},
                {"label": "Edit"},
            ],
        },
    )


@login_required
def user_deactivate(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid)

    if request.method == "POST":
        if target.pk == request.user.pk:
            messages.error(request, "You can't deactivate your own account. Ask another Superadmin to do it.")
        elif security.is_last_active_superadmin(target):
            messages.error(request, "Can't deactivate the last active Superadmin.")
        else:
            to_review, to_qa = assignments_for_user(target)
            orphaned = list(to_review) + list(to_qa)

            target.deactivate()
            security.invalidate_other_sessions(target)
            messages.success(request, f"'{target.username}' deactivated and signed out of all sessions.")

            if orphaned:
                shown = orphaned[:5]
                names = ", ".join(f"“{f.title}” ({f.engagement.client_name})" for f in shown)
                if len(orphaned) > len(shown):
                    names += f", and {len(orphaned) - len(shown)} more"
                messages.warning(
                    request,
                    f"'{target.username}' still had {len(orphaned)} finding{'s' if len(orphaned) != 1 else ''} "
                    f"assigned for review/QA — these need reassigning to someone else: {names}.",
                )

    return redirect("user_management:detail", user_uuid=target.uuid)


@login_required
def user_reactivate(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid)

    if request.method == "POST":
        target.reactivate()
        messages.success(request, f"'{target.username}' reactivated.")

    return redirect("user_management:detail", user_uuid=target.uuid)


@login_required
def user_send_password_reset(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid, auth_type=User.AuthType.LOCAL)

    if request.method == "POST":
        security.send_password_reset_email(target, request)
        messages.success(request, f"Password reset link sent to {target.email}.")

    return redirect("user_management:detail", user_uuid=target.uuid)


@login_required
def user_convert_to_local(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid, auth_type=User.AuthType.OAUTH)

    if request.method == "POST":
        target.auth_type = User.AuthType.LOCAL
        target.oauth_invite_pending = False
        target.set_unusable_password()
        target.save(update_fields=["auth_type", "oauth_invite_pending", "password"])
        security.send_account_created_email(target, request)
        messages.success(
            request,
            f"'{target.username}' converted to a local account — they've been emailed a link "
            "to set their password.",
        )

    return redirect("user_management:detail", user_uuid=target.uuid)


@login_required
def user_clear_mfa(request, user_uuid):
    _require_users_manage(request.user)
    target = _get_staff_target(user_uuid, auth_type=User.AuthType.LOCAL)

    if request.method == "POST":
        deleted, _unused = TOTPDevice.objects.filter(user=target).delete()
        if deleted:
            messages.success(request, f"MFA cleared for '{target.username}' — they'll re-enroll at next login.")
        else:
            messages.info(request, f"'{target.username}' had no MFA device to clear.")

    return redirect("user_management:detail", user_uuid=target.uuid)
