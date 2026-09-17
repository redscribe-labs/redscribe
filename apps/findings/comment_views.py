import json

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.crypto.access import engagement_access_required
from apps.crypto.services import decrypt_bytes, encrypt_bytes, record_aad

from .models import CommentEntry, CommentThread, ContentSectionDefinition, Finding
from .permissions import can_delete_comment_thread


def _entry_json(entry, project_key):
    return {
        "id": entry.pk,
        "author": str(entry.author) if entry.author else None,
        "created_at": timezone.localtime(entry.created_at).isoformat(),
        "body": decrypt_bytes(
            bytes(entry.body_ciphertext), project_key,
            associated_data=record_aad("commententry", entry.pk, "body"),
        ).decode("utf-8"),
    }


def _thread_json(thread, project_key, user):
    entries = thread.entries.select_related("author").order_by("created_at")
    return {
        "id": thread.pk,
        "field_name": thread.field_name,
        "start_pos": thread.start_pos,
        "end_pos": thread.end_pos,
        "resolved": thread.resolved,
        "anchored_text": decrypt_bytes(
            bytes(thread.anchored_text_ciphertext), project_key,
            associated_data=record_aad("commentthread", thread.pk, "anchored_text"),
        ).decode("utf-8"),
        "created_by": str(thread.created_by) if thread.created_by else None,
        "created_at": timezone.localtime(thread.created_at).isoformat(),
        "entries": [_entry_json(e, project_key) for e in entries],
        "can_delete": can_delete_comment_thread(user, thread),
    }


def _create_entry(thread, author, body: str, project_key) -> CommentEntry:
    entry = CommentEntry.objects.create(thread=thread, author=author, body_ciphertext=b"")
    entry.body_ciphertext = encrypt_bytes(
        body.encode("utf-8"), project_key, associated_data=record_aad("commententry", entry.pk, "body"),
    )
    entry.save(update_fields=["body_ciphertext"])
    return entry


def _get_finding(request, engagement_id, pk):
    return get_object_or_404(Finding, pk=pk, engagement=request.engagement)


@require_GET
@engagement_access_required
def thread_list(request, engagement_id, pk, field_name):
    if not ContentSectionDefinition.objects.filter(slug=field_name, is_active=True).exists():
        return HttpResponseBadRequest("Unknown or hidden field.")
    finding = _get_finding(request, engagement_id, pk)
    threads = finding.comment_threads.filter(field_name=field_name)
    return JsonResponse({"threads": [_thread_json(t, request.project_key, request.user) for t in threads]})


@require_POST
@engagement_access_required
def thread_create(request, engagement_id, pk, field_name):
    if not ContentSectionDefinition.objects.filter(slug=field_name, is_active=True).exists():
        return HttpResponseBadRequest("Unknown or hidden field.")
    finding = _get_finding(request, engagement_id, pk)

    try:
        payload = json.loads(request.body)
        start_pos = int(payload["start_pos"])
        end_pos = int(payload["end_pos"])
        anchored_text = str(payload["anchored_text"])
        body = str(payload["body"]).strip()
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return HttpResponseBadRequest("Malformed request body.")

    if end_pos <= start_pos or not body:
        return HttpResponseBadRequest("Invalid range or empty comment.")

    thread = CommentThread.objects.create(
        finding=finding,
        field_name=field_name,
        start_pos=start_pos,
        end_pos=end_pos,
        anchored_text_ciphertext=b"",
        created_by=request.user,
    )
    thread.anchored_text_ciphertext = encrypt_bytes(
        anchored_text.encode("utf-8"), request.project_key,
        associated_data=record_aad("commentthread", thread.pk, "anchored_text"),
    )
    thread.save(update_fields=["anchored_text_ciphertext"])
    _create_entry(thread, request.user, body, request.project_key)
    return JsonResponse(_thread_json(thread, request.project_key, request.user), status=201)


@require_POST
@engagement_access_required
def thread_reply(request, engagement_id, pk, thread_id):
    finding = _get_finding(request, engagement_id, pk)
    thread = get_object_or_404(CommentThread, pk=thread_id, finding=finding)

    try:
        payload = json.loads(request.body)
        body = str(payload["body"]).strip()
    except (KeyError, TypeError, json.JSONDecodeError):
        return HttpResponseBadRequest("Malformed request body.")
    if not body:
        return HttpResponseBadRequest("Empty comment.")

    _create_entry(thread, request.user, body, request.project_key)
    return JsonResponse(_thread_json(thread, request.project_key, request.user), status=201)


@require_POST
@engagement_access_required
def thread_toggle_resolved(request, engagement_id, pk, thread_id):
    finding = _get_finding(request, engagement_id, pk)
    thread = get_object_or_404(CommentThread, pk=thread_id, finding=finding)
    thread.resolved = not thread.resolved
    thread.save(update_fields=["resolved"])
    return JsonResponse(_thread_json(thread, request.project_key, request.user))


@require_POST
@engagement_access_required
def thread_delete(request, engagement_id, pk, thread_id):
    finding = _get_finding(request, engagement_id, pk)
    thread = get_object_or_404(CommentThread, pk=thread_id, finding=finding)
    if not can_delete_comment_thread(request.user, thread):
        raise PermissionDenied("You don't have permission to delete this comment.")
    thread.delete()
    return JsonResponse({"deleted": True})
