from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify

from apps.accounts.permissions import require_permission

from .field_visibility_forms import ContentSectionCreateForm, ContentSectionDefinitionFormSet
from .models import CommentThread, ContentSectionDefinition


def _unique_slug(label: str) -> str:
    base = slugify(label)[:64] or "section"
    slug = base
    suffix = 2
    while ContentSectionDefinition.objects.filter(slug=slug).exists():
        slug = f"{base[:60]}-{suffix}"
        suffix += 1
    return slug


@login_required
def field_visibility_edit(request):
    require_permission(request.user, "field_visibility.manage", "manage content sections")

    create_form = ContentSectionCreateForm(prefix="create")
    if request.method == "POST" and request.POST.get("action") == "create":
        create_form = ContentSectionCreateForm(request.POST, prefix="create")
        if create_form.is_valid():
            section = create_form.save(commit=False)
            section.slug = _unique_slug(section.label)
            section.updated_by = request.user
            last = ContentSectionDefinition.objects.order_by("-order").first()
            section.order = (last.order + 10) if last else 10
            section.save()
            messages.success(request, f"Section '{section.label}' added.")
            return redirect("field_visibility:edit")
        formset = ContentSectionDefinitionFormSet(queryset=ContentSectionDefinition.objects.all())
    elif request.method == "POST":
        formset = ContentSectionDefinitionFormSet(request.POST, queryset=ContentSectionDefinition.objects.all())
        if formset.is_valid():
            instances = formset.save(commit=False)
            for instance in instances:
                instance.updated_by = request.user
                instance.save()
            messages.success(request, "Finding structure updated.")
            return redirect("field_visibility:edit")
        elif formset.non_form_errors():
            messages.error(
                request,
                "Couldn't save — this list changed since the page was loaded. Reload and try again.",
            )
        else:
            messages.error(request, "Couldn't save — check the errors below.")
    else:
        formset = ContentSectionDefinitionFormSet(queryset=ContentSectionDefinition.objects.all())

    return render(
        request, "field_visibility/edit.html",
        {"formset": formset, "create_form": create_form, "breadcrumbs": [{"label": "Finding Structure"}]},
    )


@login_required
def content_section_move(request, pk, direction):
    require_permission(request.user, "field_visibility.manage", "manage content sections")
    if request.method != "POST" or direction not in ("up", "down"):
        return redirect("field_visibility:edit")

    section = get_object_or_404(ContentSectionDefinition, pk=pk)
    ordered = list(ContentSectionDefinition.objects.order_by("order", "id"))
    index = next((i for i, s in enumerate(ordered) if s.pk == section.pk), None)
    neighbor_index = index - 1 if direction == "up" else index + 1
    if index is not None and 0 <= neighbor_index < len(ordered):
        neighbor = ordered[neighbor_index]
        section.order, neighbor.order = neighbor.order, section.order
        section.updated_by = request.user
        neighbor.updated_by = request.user
        section.save(update_fields=["order", "updated_by", "updated_at"])
        neighbor.save(update_fields=["order", "updated_by", "updated_at"])
        messages.success(request, f"'{section.label}' moved {direction}.")
    return redirect("field_visibility:edit")


@login_required
def content_section_delete(request, pk):
    require_permission(request.user, "field_visibility.manage", "manage content sections")
    section = get_object_or_404(ContentSectionDefinition, pk=pk)

    if request.method == "POST":
        label = section.label
        deleted_threads = CommentThread.objects.filter(field_name=section.slug).count()
        CommentThread.objects.filter(field_name=section.slug).delete()
        section.delete()
        message = f"Section '{label}' deleted — any content already stored against it is gone too."
        if deleted_threads:
            message += f" {deleted_threads} comment thread{'s' if deleted_threads != 1 else ''} on it were deleted too."
        messages.success(request, message)
        return redirect("field_visibility:edit")

    return render(
        request, "field_visibility/delete_confirm.html",
        {"section": section, "breadcrumbs": [
            {"label": "Finding Structure", "url": reverse("field_visibility:edit")}, {"label": f"Delete {section.label}"},
        ]},
    )
