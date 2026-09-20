from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.crypto.access import engagement_access_required
from apps.crypto.services import decrypt_or_blank, encrypt_bytes, record_aad
from apps.engagements.breadcrumbs import engagement_crumbs

from .forms import ChecklistCommentForm, ChecklistItemForm
from .models import ChecklistItem, ChecklistItemComment


def _adjacent_items(item):
    ordered = list(item.run.items.order_by("order", "category", "code"))
    ids = [i.pk for i in ordered]
    position = ids.index(item.pk)
    prev_item = ordered[position - 1] if position > 0 else None
    next_item = ordered[position + 1] if position < len(ordered) - 1 else None
    return prev_item, next_item, position + 1, len(ordered)


@engagement_access_required
def item_detail(request, engagement_id, pk):
    item = get_object_or_404(ChecklistItem, pk=pk, run__engagement=request.engagement)
    prev_item, next_item, position, total = _adjacent_items(item)

    if request.method == "POST" and "save_item" in request.POST:
        form = ChecklistItemForm(request.POST, engagement=request.engagement)
        if form.is_valid():
            item.status = form.cleaned_data["status"]
            item.reference_info = form.cleaned_data["reference_info"]
            item.findings.set(form.cleaned_data["findings"])

            test_results = form.cleaned_data["test_results"]
            item.test_results_ciphertext = (
                encrypt_bytes(
                    test_results.encode("utf-8"), request.project_key,
                    associated_data=record_aad("checklistitem", item.pk, "test_results"),
                ) if test_results else None
            )
            item.save()
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
                "reference_info": item.reference_info,
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
            "prev_item": prev_item, "next_item": next_item,
            "position": position, "total": total,
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
            messages.success(request, "Comment added.")
        else:
            messages.error(request, "Comment couldn't be saved.")
    return redirect("checklist:item_detail", engagement_id=engagement_id, pk=pk)
