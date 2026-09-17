from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts import security
from apps.engagements.models import Engagement

from .forms import ClientCreateForm, ClientEditForm, ClientUserCreateForm, ClientUserEditForm
from .models import Client
from .permissions import require_client_manager

PAGE_SIZE = 10

User = get_user_model()


def _require_client_manager(user):
    require_client_manager(user, "manage clients")


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
            form.save()
            messages.success(request, f"'{company.name}' updated.")
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
    target = get_object_or_404(User, uuid=user_uuid, role__slug="client")
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
def client_user_edit(request, user_uuid):
    _require_client_manager(request.user)
    target = get_object_or_404(User, uuid=user_uuid, role__slug="client")

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
    target = get_object_or_404(User, uuid=user_uuid, role__slug="client")

    if request.method == "POST":
        target.deactivate()
        security.invalidate_other_sessions(target)
        messages.success(request, f"'{target.username}' deactivated and signed out of all sessions.")

    return redirect("clients:user_detail", user_uuid=target.uuid)


@login_required
def client_user_reactivate(request, user_uuid):
    _require_client_manager(request.user)
    target = get_object_or_404(User, uuid=user_uuid, role__slug="client")

    if request.method == "POST":
        target.reactivate()
        messages.success(request, f"'{target.username}' reactivated.")

    return redirect("clients:user_detail", user_uuid=target.uuid)


@login_required
def client_user_send_password_reset(request, user_uuid):
    _require_client_manager(request.user)
    target = get_object_or_404(User, uuid=user_uuid, role__slug="client", auth_type=User.AuthType.LOCAL)

    if request.method == "POST":
        security.send_password_reset_email(target, request)
        messages.success(request, f"Password reset link sent to {target.email}.")

    return redirect("clients:user_detail", user_uuid=target.uuid)


@login_required
def client_user_clear_mfa(request, user_uuid):
    _require_client_manager(request.user)
    target = get_object_or_404(User, uuid=user_uuid, role__slug="client", auth_type=User.AuthType.LOCAL)

    if request.method == "POST":
        deleted, _unused = TOTPDevice.objects.filter(user=target).delete()
        if deleted:
            messages.success(request, f"MFA cleared for '{target.username}' — they'll re-enroll at next login.")
        else:
            messages.info(request, f"'{target.username}' had no MFA device to clear.")

    return redirect("clients:user_detail", user_uuid=target.uuid)
