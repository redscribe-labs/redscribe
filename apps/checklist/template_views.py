from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from . import importer
from .forms import ChecklistImportForm, ChecklistTemplateForm, ChecklistTemplateItemForm
from .models import ChecklistTemplate, ChecklistTemplateItem


def _require_permission(user):
    if not user.has_permission("checklist_templates.manage"):
        raise PermissionDenied("You don't have permission to manage checklist templates.")


@login_required
def template_list(request):
    _require_permission(request.user)
    templates = ChecklistTemplate.objects.prefetch_related("items")
    return render(request, "checklist/template_list.html", {"templates": templates})


@login_required
def template_detail(request, pk):
    _require_permission(request.user)
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    items = ChecklistTemplateItem.objects.filter(template=template)
    by_category: dict = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)
    grouped = [{"category": category, "items": group_items} for category, group_items in by_category.items()]
    return render(
        request, "checklist/template_detail.html",
        {"template": template, "items": items, "grouped": grouped},
    )


@login_required
def template_export(request, pk):
    _require_permission(request.user)
    template = get_object_or_404(ChecklistTemplate, pk=pk)

    payload = importer.export_json(template)
    response = HttpResponse(payload, content_type="application/json")
    base = slugify(template.name) or "checklist-template"
    filename = f"redscribe-{base}-{timezone.now().strftime('%Y%m%d-%H%M%S')}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def template_create(request):
    _require_permission(request.user)

    if request.method == "POST":
        form = ChecklistTemplateForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            if ChecklistTemplate.objects.filter(name=name).exists():
                form.add_error("name", "A template with this name already exists.")
            else:
                with transaction.atomic():
                    template = ChecklistTemplate.objects.create(
                        name=name, description=form.cleaned_data["description"], uploaded_by=request.user,
                    )
                    if form.cleaned_data["set_default"]:
                        ChecklistTemplate.objects.exclude(pk=template.pk).update(is_default=False)
                        template.is_default = True
                        template.save(update_fields=["is_default"])
                messages.success(request, f"Template '{template.name}' created.")
                return redirect("checklist_templates:detail", pk=template.pk)
    else:
        form = ChecklistTemplateForm()

    return render(request, "checklist/template_form.html", {"form": form, "heading": "New checklist template"})


@login_required
def template_edit(request, pk):
    _require_permission(request.user)
    template = get_object_or_404(ChecklistTemplate, pk=pk)

    if request.method == "POST":
        form = ChecklistTemplateForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            if ChecklistTemplate.objects.exclude(pk=template.pk).filter(name=name).exists():
                form.add_error("name", "A template with this name already exists.")
            else:
                with transaction.atomic():
                    template.name = name
                    template.description = form.cleaned_data["description"]
                    if form.cleaned_data["set_default"]:
                        ChecklistTemplate.objects.exclude(pk=template.pk).update(is_default=False)
                        template.is_default = True
                    elif template.is_default:
                        template.is_default = False
                    template.save(update_fields=["name", "description", "is_default"])
                messages.success(request, "Template updated.")
                return redirect("checklist_templates:detail", pk=template.pk)
    else:
        form = ChecklistTemplateForm(initial={
            "name": template.name, "description": template.description, "set_default": template.is_default,
        })

    return render(
        request, "checklist/template_form.html",
        {"form": form, "heading": f"Edit {template.name}", "template": template},
    )


@login_required
def template_item_create(request, pk):
    _require_permission(request.user)
    template = get_object_or_404(ChecklistTemplate, pk=pk)
    categories = list(
        ChecklistTemplateItem.objects.filter(template=template).values_list("category", flat=True).distinct()
    )

    if request.method == "POST":
        form = ChecklistTemplateItemForm(request.POST)
        if form.is_valid():
            next_order = (template.items.aggregate(Max("order"))["order__max"] or 0) + 1
            item = ChecklistTemplateItem.objects.create(
                template=template, order=next_order,
                category=form.cleaned_data["category"], code=form.cleaned_data["code"],
                title=form.cleaned_data["title"], reference_info=form.cleaned_data["reference_info"],
            )
            messages.success(request, f"Item '{item.title}' added.")
            return redirect("checklist_templates:detail", pk=template.pk)
    else:
        initial = {}
        category = request.GET.get("category")
        if category:
            initial["category"] = category
        form = ChecklistTemplateItemForm(initial=initial)

    return render(
        request, "checklist/template_item_form.html",
        {"form": form, "template": template, "categories": categories, "heading": "Add checklist item"},
    )


@login_required
def template_item_edit(request, item_pk):
    _require_permission(request.user)
    item = get_object_or_404(ChecklistTemplateItem, pk=item_pk)
    template = item.template
    categories = list(
        ChecklistTemplateItem.objects.filter(template=template).values_list("category", flat=True).distinct()
    )

    if request.method == "POST":
        form = ChecklistTemplateItemForm(request.POST)
        if form.is_valid():
            item.category = form.cleaned_data["category"]
            item.code = form.cleaned_data["code"]
            item.title = form.cleaned_data["title"]
            item.reference_info = form.cleaned_data["reference_info"]
            item.save(update_fields=["category", "code", "title", "reference_info"])
            messages.success(request, "Item updated.")
            return redirect("checklist_templates:detail", pk=template.pk)
    else:
        form = ChecklistTemplateItemForm(initial={
            "category": item.category, "code": item.code,
            "title": item.title, "reference_info": item.reference_info,
        })

    return render(
        request, "checklist/template_item_form.html",
        {"form": form, "template": template, "categories": categories, "heading": "Edit checklist item", "item": item},
    )


@login_required
def template_item_delete(request, item_pk):
    _require_permission(request.user)
    item = get_object_or_404(ChecklistTemplateItem, pk=item_pk)
    template = item.template

    if request.method == "POST":
        title = item.title
        item.delete()
        messages.success(request, f"Item '{title}' deleted.")
        return redirect("checklist_templates:detail", pk=template.pk)

    return render(request, "checklist/template_item_delete_confirm.html", {"item": item, "template": template})


@login_required
def template_item_move(request, item_pk):
    _require_permission(request.user)
    item = get_object_or_404(ChecklistTemplateItem, pk=item_pk)

    if request.method == "POST":
        direction = request.POST.get("direction")
        siblings = list(
            ChecklistTemplateItem.objects.filter(template=item.template, category=item.category).order_by("order", "code")
        )
        index = next((i for i, sibling in enumerate(siblings) if sibling.pk == item.pk), None)
        if index is not None:
            swap_index = index - 1 if direction == "up" else index + 1 if direction == "down" else None
            if swap_index is not None and 0 <= swap_index < len(siblings):
                other = siblings[swap_index]
                with transaction.atomic():
                    item.order, other.order = other.order, item.order
                    ChecklistTemplateItem.objects.bulk_update([item, other], ["order"])
                messages.success(request, f"'{item.title}' moved {direction}.")

    return redirect("checklist_templates:detail", pk=item.template_id)


@login_required
def template_upload(request):
    _require_permission(request.user)

    if request.method == "POST":
        form = ChecklistImportForm(request.POST, request.FILES)
        if form.is_valid():
            raw_text = form.cleaned_data["file"].read().decode("utf-8", errors="replace")
            importer_fn = importer.import_json if form.cleaned_data["format"] == "json" else importer.import_csv
            try:
                with transaction.atomic():
                    count = importer_fn(
                        form.cleaned_data["name"], form.cleaned_data["description"], raw_text,
                        uploaded_by=request.user,
                    )
                    if form.cleaned_data["set_default"]:
                        ChecklistTemplate.objects.exclude(name=form.cleaned_data["name"]).update(is_default=False)
                        ChecklistTemplate.objects.filter(name=form.cleaned_data["name"]).update(is_default=True)
                messages.success(request, f"Imported {count} items into '{form.cleaned_data['name']}'.")
                return redirect("checklist_templates:list")
            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        form = ChecklistImportForm()

    return render(request, "checklist/template_upload.html", {"form": form})


@login_required
def template_set_default(request, pk):
    _require_permission(request.user)
    if request.method == "POST":
        target = get_object_or_404(ChecklistTemplate, pk=pk)
        with transaction.atomic():
            ChecklistTemplate.objects.update(is_default=False)
            ChecklistTemplate.objects.filter(pk=target.pk).update(is_default=True)
        messages.success(request, "Default checklist template updated.")
    return redirect("checklist_templates:list")
