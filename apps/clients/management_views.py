from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts import security
from apps.accounts.erase_views import run_erase_flow
from apps.engagements.models import Engagement

from .forms import ClientCreateForm, ClientEditForm, ClientUserCreateForm, ClientUserEditForm
from .lifecycle import deactivate_client_users
from .models import Client
from .permissions import require_client_manager

PAGE_SIZE = 10

User = get_user_model()


def _require_client_manager(user):
    require_client_manager(user, "manage clients")


def _get_client_target(user_uuid, *, allow_erased=False, **extra):
    # Erased accounts are read-only tombstones: only the detail page may open one,
    # every action view 404s so nothing can revive or edit it.
    users = User.objects.filter(role__slug="client")
    if not allow_erased:
        users = users.filter(erased_at__isnull=True)
    return get_object_or_404(users, uuid=user_uuid, **extra)


@login_required
def client_list(request):
    _require_client_manager(request.user)
    query = request.GET.get("q", "").strip()
    clients = Client.objects.all()
    if query:
        clients = clients.filter(Q(name__icontains=query))

    page_obj = Paginator(clients, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request, "clients/list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "breadcrumbs": [{"label": "Manage Clients"}],
        },
    )


@login_required
def client_create(request):
    _require_client_manager(request.user)

    if request.method == "POST":
        form = ClientCreateForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            client.created_by = request.user
            client.save()
            messages.success(request, f"Client '{client.name}' created.")
            return redirect("clients:detail", client_uuid=client.pk)
    else:
        form = ClientCreateForm()

    return render(
        request, "clients/create.html",
        {
            "form": form,
            "breadcrumbs": [
                {"label": "Manage Clients", "url": reverse("clients:list")},
                {"label": "New client"},
            ],
        },
    )


@login_required
def client_detail(request, client_uuid):
    _require_client_manager(request.user)
    company = get_object_or_404(Client, pk=client_uuid)
    engagements = Engagement.objects.filter(client=company).order_by("-created_at")
    portal_users = User.objects.filter(client=company).order_by("username")

    return render(
        request, "clients/detail.html",
        {
            "company": company,
            "engagements": engagements,
            "portal_users": portal_users,
            "breadcrumbs": [
                {"label": "Manage Clients", "url": reverse("clients:list")},
                {"label": company.name},
            ],
        },
    )


@login_required
def client_edit(request, client_uuid):
    _require_client_manager(request.user)
    company = get_object_or_404(Client, pk=client_uuid)

    if request.method == "POST":
        form = ClientEditForm(request.POST, instance=company)
        if form.is_valid():
            was_active = Client.objects.values_list("is_active", flat=True).get(pk=company.pk)
            with transaction.atomic():
                form.save()
                deactivated = deactivate_client_users(company) if was_active and not company.is_active else 0
            messages.success(request, f"'{company.name}' updated.")
            if deactivated:
                messages.info(
                    request,
                    f"{deactivated} portal user{'s' if deactivated != 1 else ''} deactivated and signed out. "
                    "Reactivating the client does not reactivate them.",
                )
            return redirect("clients:detail", client_uuid=company.pk)
    else:
        form = ClientEditForm(instance=company)

    return render(
        request, "clients/edit.html",
        {
            "form": form,
            "company": company,
            "breadcrumbs": [
                {"label": "Manage Clients", "url": reverse("clients:list")},
                {"label": company.name, "url": reverse("clients:detail", args=[company.pk])},
                {"label": "Edit"},
            ],
        },
    )


@login_required
def client_user_create(request, client_uuid):
    _require_client_manager(request.user)
    company = get_object_or_404(Client, pk=client_uuid)

    if request.method == "POST":
        form = ClientUserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            security.send_account_created_email(user, request)
            messages.success(request, f"Client account '{user.username}' created.")
            return redirect("clients:user_detail", user_uuid=user.uuid)
    else:
        form = ClientUserCreateForm(initial={"client": company.pk})

    return render(
        request, "clients/user_create.html",
        {
            "form": form,
            "company": company,
            "breadcrumbs": [
                {"label": "Manage Clients", "url": reverse("clients:list")},
                {"label": company.name, "url": reverse("clients:detail", args=[company.pk])},
                {"label": "New client user"},
            ],
        },
    )


@login_required
def client_user_detail(request, user_uuid):
    _require_client_manager(request.user)
    target = _get_client_target(user_uuid, allow_erased=True)
    has_confirmed_mfa = TOTPDevice.objects.filter(user=target, confirmed=True).exists()

    return render(
        request, "clients/user_detail.html",
        {
            "target": target,
            "has_confirmed_mfa": has_confirmed_mfa,
            "breadcrumbs": [
                {"label": "Manage Clients", "url": reverse("clients:list")},
                {"label": target.client.name, "url": reverse("clients:detail", args=[target.client.pk])} if target.client else {"label": "Client user"},
                {"label": target.username},
            ],
        },
    )


@login_required
def client_user_erase(request, user_uuid):
    _require_client_manager(request.user)
    # clients.manage is a Team Lead default; erasing is irreversible, so it stays with Superadmins.
    if not request.user.is_superadmin_role:
        raise PermissionDenied("Only a Superadmin can erase a client user.")
    target = _get_client_target(user_uuid, allow_erased=True)
    detail_url = reverse("clients:user_detail", args=[target.uuid])

    return run_erase_flow(
        request, target,
        detail_url=detail_url,
        erase_url=reverse("clients:user_erase", args=[target.uuid]),
        breadcrumbs=[
            {"label": "Manage Clients", "url": reverse("clients:list")},
            {"label": target.client.name, "url": reverse("clients:detail", args=[target.client.pk])}
            if target.client else {"label": "Client user"},
            {"label": target.username, "url": detail_url},
            {"label": "Erase"},
        ],
        action="clients:erase_user",
        route="clients/users",
    )


@login_required
def client_user_edit(request, user_uuid):
    _require_client_manager(request.user)
    target = _get_client_target(user_uuid)

    if request.method == "POST":
        form = ClientUserEditForm(request.POST, instance=target)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{target.username}' updated.")
            return redirect("clients:user_detail", user_uuid=target.uuid)
    else:
        form = ClientUserEditForm(instance=target)

    return render(
        request, "clients/user_edit.html",
        {
            "form": form,
            "target": target,
            "breadcrumbs": [
                {"label": "Manage Clients", "url": reverse("clients:list")},
                {"label": target.username, "url": reverse("clients:user_detail", args=[target.uuid])},
                {"label": "Edit"},
            ],
        },
    )


@login_required
def client_user_deactivate(request, user_uuid):
    _require_client_manager(request.user)
    target = _get_client_target(user_uuid)

    if request.method == "POST":
        target.deactivate()
        security.invalidate_other_sessions(target)
        messages.success(request, f"'{target.username}' deactivated and signed out of all sessions.")

    return redirect("clients:user_detail", user_uuid=target.uuid)


@login_required
def client_user_reactivate(request, user_uuid):
    _require_client_manager(request.user)
    target = _get_client_target(user_uuid)

    if request.method == "POST":
        if target.client is None:
            messages.error(request, "This account isn't linked to a client company, so it can't be reactivated here.")
        elif not target.client.is_active:
            messages.error(request, "Reactivate the client company before reactivating its users.")
        else:
            target.reactivate()
            messages.success(request, f"'{target.username}' reactivated.")

    return redirect("clients:user_detail", user_uuid=target.uuid)


@login_required
def client_user_send_password_reset(request, user_uuid):
    _require_client_manager(request.user)
    target = _get_client_target(user_uuid, auth_type=User.AuthType.LOCAL)

    if request.method == "POST":
        security.send_password_reset_email(target, request)
        messages.success(request, f"Password reset link sent to {target.email}.")

    return redirect("clients:user_detail", user_uuid=target.uuid)


@login_required
def client_user_clear_mfa(request, user_uuid):
    _require_client_manager(request.user)
    target = _get_client_target(user_uuid, auth_type=User.AuthType.LOCAL)

    if request.method == "POST":
        deleted, _unused = TOTPDevice.objects.filter(user=target).delete()
        if deleted:
            messages.success(request, f"MFA cleared for '{target.username}' — they'll re-enroll at next login.")
        else:
            messages.info(request, f"'{target.username}' had no MFA device to clear.")

    return redirect("clients:user_detail", user_uuid=target.uuid)
