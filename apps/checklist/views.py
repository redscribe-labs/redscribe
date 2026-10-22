from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.crypto.access import engagement_access_required
from apps.engagements.breadcrumbs import engagement_crumbs

from .export import build_checklist_export
from .models import ChecklistItem, ChecklistItemEvent, ChecklistTemplate
from .posture import run_posture
from .services import instantiate_checklist


def _build_run_context(run):
    items = list(run.items.select_related("assignee").prefetch_related("findings"))
    by_category: dict = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)
    grouped = [
        {
            "category": category, "items": group_items,
            "untested": sum(1 for i in group_items if i.status == ChecklistItem.Status.NOT_TESTED),
        }
        for category, group_items in by_category.items()
    ]

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


def _add_custom_check(request, engagement_id):
    """Adds a one-off check to a single run, without touching its template."""
    run = get_object_or_404(request.engagement.checklist_runs, pk=request.POST.get("run_id"))
    title = request.POST.get("title", "").strip()[:500]
    category = request.POST.get("category", "").strip()[:255] or "Custom checks"
    code = request.POST.get("code", "").strip()[:32]
    list_url = f"{reverse('checklist:list', args=[engagement_id])}?run={run.pk}"
    if not title:
        messages.error(request, "Give the custom check a title.")
        return redirect(list_url)
    last_order = run.items.aggregate(Max("order"))["order__max"] or 0
    item = ChecklistItem.objects.create(run=run, category=category, code=code, title=title, order=last_order + 1)
    messages.success(request, f"Added '{item.title}' to {run.label}.")
    return redirect(list_url)


# Outcomes a whole category can be given at once. Blocked isn't one: each
# blocked check needs its own reason.
BULK_OUTCOMES = [ChecklistItem.Status.NOT_APPLICABLE, ChecklistItem.Status.TESTED_NO_FINDING]


def _bulk_mark_category(request, engagement_id):
    """Gives every untested check in one category of a run the same outcome.
    Checks that already have an outcome are left alone."""
    run = get_object_or_404(request.engagement.checklist_runs, pk=request.POST.get("run_id"))
    category = request.POST.get("category", "")
    status = request.POST.get("status", "")
    list_url = f"{reverse('checklist:list', args=[engagement_id])}?run={run.pk}"
    if status not in BULK_OUTCOMES:
        messages.error(request, "Choose Not applicable or Tested, no finding.")
        return redirect(list_url)
    items = list(run.items.filter(category=category, status=ChecklistItem.Status.NOT_TESTED))
    if not items:
        messages.info(request, f"Every check in {category or 'that category'} already has an outcome.")
        return redirect(list_url)
    labels = dict(ChecklistItem.Status.choices)
    now = timezone.now()
    with transaction.atomic():
        for item in items:
            item.status, item.tested_by, item.tested_at, item.updated_at = status, request.user, now, now
        ChecklistItem.objects.bulk_update(items, ["status", "tested_by", "tested_at", "updated_at"])
        ChecklistItemEvent.objects.bulk_create([
            ChecklistItemEvent(
                item=item, actor=request.user, kind=ChecklistItemEvent.Kind.STATUS,
                from_value=labels[ChecklistItem.Status.NOT_TESTED], to_value=labels[status],
            )
            for item in items
        ])
    messages.success(
        request, f"Marked {len(items)} untested check{'s' if len(items) != 1 else ''} in {category} as {labels[status]}.",
    )
    return redirect(list_url)


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

    if request.method == "POST" and "add_custom_check" in request.POST:
        return _add_custom_check(request, engagement_id)

    if request.method == "POST" and "bulk_category" in request.POST:
        return _bulk_mark_category(request, engagement_id)

    runs = request.engagement.checklist_runs.select_related("template")
    run_contexts = [_build_run_context(run) for run in runs]
    postures = [run_posture(run, request.project_key) for run in runs]
    selected = next((p for p in postures if str(p["run"].pk) == request.GET.get("run", "")), postures[0] if postures else None)
    selected_context = next((c for c in run_contexts if selected and c["run"].pk == selected["run"].pk), None)
    unlinked_findings = request.engagement.findings.filter(archived=False, checklist_items__isnull=True).count()

    return render(
        request, "checklist/list.html",
        {
            "engagement": request.engagement, "runs": run_contexts,
            "postures": postures, "posture": selected, "selected_context": selected_context,
            "unlinked_findings": unlinked_findings,
            "checklist_templates": ChecklistTemplate.objects.all(),
            "bulk_outcomes": [(s, ChecklistItem.Status(s).label) for s in BULK_OUTCOMES],
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
