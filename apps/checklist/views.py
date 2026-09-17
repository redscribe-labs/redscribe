from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.crypto.access import engagement_access_required
from apps.engagements.breadcrumbs import engagement_crumbs

from .export import build_checklist_export
from .models import ChecklistItem, ChecklistTemplate
from .services import instantiate_checklist


def _build_run_context(run):
    items = list(run.items.prefetch_related("findings"))
    by_category: dict = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)
    grouped = [{"category": category, "items": group_items} for category, group_items in by_category.items()]

    suggestions = []
    for group in grouped:
        first_untouched = next(
            (i for i in group["items"] if i.status == ChecklistItem.Status.NOT_TESTED), None
        )
        if first_untouched:
            suggestions.append({"category": group["category"], "item": first_untouched})

    total_count = len(items)
    tested_count = sum(1 for i in items if i.status != ChecklistItem.Status.NOT_TESTED)
    progress_pct = round(tested_count / total_count * 100) if total_count else 0

    return {
        "run": run, "grouped": grouped, "suggestions": suggestions,
        "total_count": total_count, "tested_count": tested_count, "progress_pct": progress_pct,
        "suggested_ids": {s["item"].pk for s in suggestions},
    }


@engagement_access_required
def checklist_list(request, engagement_id):
    if request.method == "POST" and "start_checklist" in request.POST:
        template_id = request.POST.get("template_id")
        label = request.POST.get("label", "")
        try:
            template = get_object_or_404(ChecklistTemplate, pk=template_id) if template_id else None
            run = instantiate_checklist(request.engagement, template=template, label=label, created_by=request.user)
            messages.success(request, f"Checklist '{run.label}' started with {run.items.count()} items.")
        except ValueError as exc:
            messages.error(request, str(exc))
        except ValidationError:
            messages.error(request, "That's not a valid checklist template.")
        return redirect("checklist:list", engagement_id=engagement_id)

    runs = request.engagement.checklist_runs.select_related("template")
    run_contexts = [_build_run_context(run) for run in runs]

    return render(
        request, "checklist/list.html",
        {
            "engagement": request.engagement, "runs": run_contexts,
            "checklist_templates": ChecklistTemplate.objects.all(),
            "breadcrumbs": engagement_crumbs(request.engagement) + [{"label": "Checklist"}],
        },
    )


@engagement_access_required
def checklist_export(request, engagement_id):
    payload = build_checklist_export(request.engagement, request.project_key, exported_by=request.user)
    response = JsonResponse(payload, json_dumps_params={"indent": 2})
    filename = f"checklist-export-{request.engagement.pk}-{timezone.now():%Y%m%d-%H%M%S}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
