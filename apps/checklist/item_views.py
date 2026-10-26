from datetime import timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.crypto.access import engagement_access_required
from apps.crypto.services import decrypt_or_blank, encrypt_bytes, record_aad
from apps.engagements.breadcrumbs import engagement_crumbs

from .forms import ChecklistCommentForm, ChecklistItemForm
from .models import ChecklistItem, ChecklistItemComment, ChecklistItemEvent
from .services import decrypt_item_text, encrypt_item_text


def _adjacent_items(item):
    ordered = list(item.run.items.select_related("assignee").order_by("order", "category", "code"))
    ids = [i.pk for i in ordered]
    position = ids.index(item.pk)
    prev_item = ordered[position - 1] if position > 0 else None
    next_item = ordered[position + 1] if position < len(ordered) - 1 else None
    return prev_item, next_item, position + 1, len(ordered), ordered


def _navigator(ordered, current, mine_only=None):
    """The run's checks grouped by category for the side navigator; the
    current item's category starts open. mine_only=<user> keeps just that
    user's checks (plus the current one)."""
    groups = []
    for it in ordered:
        if mine_only is not None and it.assignee_id != mine_only.pk and it.pk != current.pk:
            continue
        if not groups or groups[-1]["category"] != it.category:
            groups.append({"category": it.category, "items": [], "done": 0, "open": False})
        group = groups[-1]
        group["items"].append(it)
        if it.status != ChecklistItem.Status.NOT_TESTED:
            group["done"] += 1
        if it.pk == current.pk:
            group["open"] = True
    return groups


# Autosave saves on every pause in typing; text edits by the same person
# within this window show as one "edited" entry instead of dozens.
EDIT_EVENT_WINDOW = timedelta(minutes=10)


def _recently_logged(item, actor, kind):
    return item.events.filter(actor=actor, kind=kind, created_at__gte=timezone.now() - EDIT_EVENT_WINDOW).exists()


def _record_events(item, actor, before, cleaned):
    Kind = ChecklistItemEvent.Kind
    labels = dict(ChecklistItem.Status.choices)
    events = []
    if before["status"] != cleaned["status"]:
        events.append(ChecklistItemEvent(
            item=item, actor=actor, kind=Kind.STATUS,
            from_value=labels.get(before["status"], ""), to_value=labels.get(cleaned["status"], ""),
        ))
    if before["assignee"] != cleaned["assignee"]:
        events.append(ChecklistItemEvent(
            item=item, actor=actor, kind=Kind.ASSIGNEE,
            from_value=str(before["assignee"] or "Unassigned")[:255], to_value=str(cleaned["assignee"] or "Unassigned")[:255],
        ))
    if before["test_results"] != (cleaned["test_results"] or "") and not _recently_logged(item, actor, Kind.EVIDENCE):
        events.append(ChecklistItemEvent(item=item, actor=actor, kind=Kind.EVIDENCE))
    if before["scope_tested"] != cleaned["scope_tested"].strip() and not _recently_logged(item, actor, Kind.SCOPE):
        events.append(ChecklistItemEvent(item=item, actor=actor, kind=Kind.SCOPE))
    if before["findings"] != {f.pk for f in cleaned["findings"]}:
        events.append(ChecklistItemEvent(
            item=item, actor=actor, kind=Kind.FINDINGS,
            from_value=str(len(before["findings"])), to_value=str(len(cleaned["findings"])),
        ))
    ChecklistItemEvent.objects.bulk_create(events)


def _version(item):
    return item.updated_at.isoformat() if item.updated_at else ""


def _is_stale(item, version):
    """True when the page was loaded from an older copy of this check than
    the one in the database, i.e. someone else has saved it since."""
    return bool(version) and version != _version(item)


def _apply_form(item, form, request):
    """Saves a valid ChecklistItemForm onto item and records what changed.
    Shared by the normal form POST and autosave."""
    key = request.project_key
    before = {
        "status": item.status,
        "assignee": item.assignee,
        "findings": set(item.findings.values_list("pk", flat=True)),
        "test_results": decrypt_or_blank(
            item.test_results_ciphertext, key, associated_data=record_aad("checklistitem", item.pk, "test_results"),
        ),
        "scope_tested": decrypt_item_text(item, "scope_tested", key),
    }
    cleaned = form.cleaned_data
    if cleaned["status"] == ChecklistItem.Status.NOT_TESTED:
        item.tested_by, item.tested_at = None, None
    elif cleaned["status"] != item.status:
        item.tested_by, item.tested_at = request.user, timezone.now()
    item.status = cleaned["status"]
    item.assignee = cleaned["assignee"]
    item.scope_tested_ciphertext = encrypt_item_text(item, "scope_tested", cleaned["scope_tested"].strip(), key)
    item.blocked_reason_ciphertext = encrypt_item_text(item, "blocked_reason", cleaned["blocked_reason"].strip(), key)
    item.findings.set(cleaned["findings"])
    test_results = cleaned["test_results"]
    item.test_results_ciphertext = (
        encrypt_bytes(test_results.encode("utf-8"), key, associated_data=record_aad("checklistitem", item.pk, "test_results"))
        if test_results else None
    )
    item.save()
    _record_events(item, request.user, before, cleaned)


@engagement_access_required
@require_POST
def item_autosave(request, engagement_id, pk):
    """Background save from the item page. Refuses (409) if someone else saved
    the check after this page loaded, instead of overwriting their work."""
    item = get_object_or_404(ChecklistItem, pk=pk, run__engagement=request.engagement)
    if _is_stale(item, request.POST.get("version")):
        last = item.events.select_related("actor").first()
        return JsonResponse({
            "saved": False, "conflict": True,
            "message": f"{last.actor if last and last.actor else 'Someone else'} saved this check after you opened it.",
        }, status=409)
    form = ChecklistItemForm(request.POST, engagement=request.engagement)
    if not form.is_valid():
        return JsonResponse({"saved": False, "errors": form.errors.get_json_data()}, status=400)
    _apply_form(item, form, request)
    return JsonResponse({"saved": True, "version": _version(item), "saved_at": timezone.localtime(item.updated_at).strftime("%H:%M")})


@engagement_access_required
def item_detail(request, engagement_id, pk):
    item = get_object_or_404(ChecklistItem, pk=pk, run__engagement=request.engagement)
    prev_item, next_item, position, total, ordered = _adjacent_items(item)

    conflict = False
    if request.method == "POST" and "save_item" in request.POST:
        form = ChecklistItemForm(request.POST, engagement=request.engagement)
        # Someone else saved after this page loaded: show their change instead of
        # overwriting it, unless the user has chosen "Keep my changes" (save_item=overwrite).
        conflict = _is_stale(item, request.POST.get("version")) and request.POST.get("save_item") != "overwrite"
        if not conflict and form.is_valid():
            _apply_form(item, form, request)
            messages.success(request, "Checklist item updated.")

            action = request.POST.get("save_item")
            if action == "next":
                if next_item:
                    return redirect("checklist:item_detail", engagement_id=engagement_id, pk=next_item.pk)
                return redirect("checklist:list", engagement_id=engagement_id)
            if action == "prev" and prev_item:
                return redirect("checklist:item_detail", engagement_id=engagement_id, pk=prev_item.pk)
            return redirect("checklist:item_detail", engagement_id=engagement_id, pk=pk)
    else:
        form = ChecklistItemForm(
            engagement=request.engagement,
            initial={
                "status": item.status,
                "assignee": item.assignee_id,
                "scope_tested": decrypt_item_text(item, "scope_tested", request.project_key),
                "blocked_reason": decrypt_item_text(item, "blocked_reason", request.project_key),
                "test_results": decrypt_or_blank(
                    item.test_results_ciphertext, request.project_key,
                    associated_data=record_aad("checklistitem", item.pk, "test_results"),
                ),
                "findings": list(item.findings.values_list("id", flat=True)),
            },
        )

    comments = [
        {
            "author": c.author,
            "created_at": c.created_at,
            "body": decrypt_or_blank(
                c.body_ciphertext, request.project_key,
                associated_data=record_aad("checklistitemcomment", c.pk, "body"),
            ),
        }
        for c in item.comments.select_related("author")
    ]

    return render(
        request, "checklist/item_detail.html",
        {
            "engagement": request.engagement, "item": item, "form": form,
            "comments": comments, "comment_form": ChecklistCommentForm(),
            "events": item.events.select_related("actor")[:30],
            "version": _version(item),
            "conflict": conflict,
            "last_event": item.events.select_related("actor").first(),
            "prev_item": prev_item, "next_item": next_item,
            "position": position, "total": total,
            "navigator": _navigator(ordered, item, mine_only=request.user if request.GET.get("mine") == "1" else None),
            "mine_only": request.GET.get("mine") == "1",
            "tested_total": sum(1 for i in ordered if i.status != ChecklistItem.Status.NOT_TESTED),
            "status_choices": ChecklistItem.Status.choices,
            "breadcrumbs": engagement_crumbs(request.engagement) + [
                {"label": "Checklist", "url": reverse("checklist:list", args=[request.engagement.pk])},
                {"label": f"{item.code} — {item.title}" if item.code else item.title},
            ],
        },
    )


@engagement_access_required
def item_comment_create(request, engagement_id, pk):
    item = get_object_or_404(ChecklistItem, pk=pk, run__engagement=request.engagement)
    if request.method == "POST":
        form = ChecklistCommentForm(request.POST)
        if form.is_valid():
            comment = ChecklistItemComment.objects.create(
                checklist_item=item, author=request.user, body_ciphertext=b"",
            )
            comment.body_ciphertext = encrypt_bytes(
                form.cleaned_data["body"].encode("utf-8"), request.project_key,
                associated_data=record_aad("checklistitemcomment", comment.pk, "body"),
            )
            comment.save(update_fields=["body_ciphertext"])
            ChecklistItemEvent.objects.create(item=item, actor=request.user, kind=ChecklistItemEvent.Kind.COMMENT)
            messages.success(request, "Comment added.")
        else:
            messages.error(request, "Comment couldn't be saved.")
    return redirect("checklist:item_detail", engagement_id=engagement_id, pk=pk)
