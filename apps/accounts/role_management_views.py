from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Permission, Role
from .permissions import require_permission

PAGE_SIZE = 10


def _require_roles_manage(user):
    require_permission(user, "roles.manage", "manage roles")


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["name", "requires_mfa"]


def _selected_codenames(request) -> set:
    return set(request.POST.getlist("permissions"))


@login_required
def role_list(request):
    _require_roles_manage(request.user)
    query = request.GET.get("q", "").strip()
    roles = Role.objects.all()
    if query:
        roles = roles.filter(Q(name__icontains=query))

    page_obj = Paginator(roles, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request, "accounts/role_management/list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "breadcrumbs": [{"label": "Roles"}],
        },
    )


@login_required
def role_create(request):
    _require_roles_manage(request.user)
    permissions = Permission.objects.all()

    if request.method == "POST":
        form = RoleForm(request.POST)
        selected = _selected_codenames(request)
        if form.is_valid():
            role = form.save(commit=False)
            role.slug = Role.unique_slug_from_name(role.name)
            role.save()
            role.permissions.set(permissions.filter(codename__in=selected))
            messages.success(request, f"Role '{role.name}' created.")
            return redirect("role_management:detail", pk=role.pk)
    else:
        form = RoleForm()
        selected = set()

    return render(
        request, "accounts/role_management/create.html",
        {
            "form": form,
            "permissions": permissions,
            "selected_codenames": selected,
            "breadcrumbs": [
                {"label": "Roles", "url": reverse("role_management:list")},
                {"label": "New role"},
            ],
        },
    )


@login_required
def role_detail(request, pk):
    _require_roles_manage(request.user)
    role = get_object_or_404(Role, pk=pk)
    return render(
        request, "accounts/role_management/detail.html",
        {
            "target": role,
            "user_count": role.users.count(),
            "granted_codenames": set(role.permissions.values_list("codename", flat=True)),
            "all_permissions": Permission.objects.all(),
            "breadcrumbs": [
                {"label": "Roles", "url": reverse("role_management:list")},
                {"label": role.name},
            ],
        },
    )


@login_required
def role_edit(request, pk):
    _require_roles_manage(request.user)
    role = get_object_or_404(Role, pk=pk)
    if role.is_superadmin:
        raise PermissionDenied("The Superadmin role can't be edited — its access can't be scoped down.")

    permissions = Permission.objects.all()

    if request.method == "POST":
        form = RoleForm(request.POST, instance=role)
        selected = _selected_codenames(request)
        if form.is_valid():
            form.save()
            role.permissions.set(permissions.filter(codename__in=selected))
            messages.success(request, f"Role '{role.name}' updated.")
            return redirect("role_management:detail", pk=role.pk)
    else:
        form = RoleForm(instance=role)
        selected = set(role.permissions.values_list("codename", flat=True))

    return render(
        request, "accounts/role_management/edit.html",
        {
            "form": form,
            "target": role,
            "permissions": permissions,
            "selected_codenames": selected,
            "breadcrumbs": [
                {"label": "Roles", "url": reverse("role_management:list")},
                {"label": role.name, "url": reverse("role_management:detail", args=[role.pk])},
                {"label": "Edit"},
            ],
        },
    )


@login_required
def role_delete(request, pk):
    _require_roles_manage(request.user)
    role = get_object_or_404(Role, pk=pk)

    if request.method == "POST":
        if role.is_builtin:
            messages.error(request, f"'{role.name}' is a built-in role and can't be deleted.")
        elif role.users.exists():
            messages.error(
                request,
                f"Can't delete '{role.name}' — {role.users.count()} account(s) still have it. "
                "Reassign them to a different role first.",
            )
        else:
            try:
                role.delete()
            except ProtectedError:
                messages.error(request, f"Can't delete '{role.name}' — it's still in use.")
            else:
                messages.success(request, f"Role '{role.name}' deleted.")
                return redirect("role_management:list")

    return redirect("role_management:detail", pk=role.pk)
