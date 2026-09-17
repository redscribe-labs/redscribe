import json

from django.utils import timezone

from apps.crypto.services import decrypt_or_blank, record_aad
from apps.reports.tiptap_render import tiptap_to_html

_MAX_NODE_DEPTH = 50


def _count_images(node, depth=0):
    if depth > _MAX_NODE_DEPTH or not isinstance(node, dict):
        return 0
    count = 1 if node.get("type") == "image" else 0
    for child in node.get("content") or []:
        count += _count_images(child, depth + 1)
    return count


def _render_rich_field(raw):
    """Render a stored Tiptap JSON field to HTML, dropping any embedded images.

    Images live as encrypted blobs the recipient of a JSON export has no way to
    fetch, so they're stripped rather than left as dangling/broken references.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", 0
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw, 0
    images_omitted = _count_images(parsed) if isinstance(parsed, dict) else 0
    return tiptap_to_html(raw, image_resolver=None), images_omitted


def _finding_payload(finding):
    return {
        "id": str(finding.pk),
        "display_id": finding.display_id,
        "title": finding.title,
        "severity": finding.severity,
        "status": finding.status,
        "workflow_status": finding.workflow_status,
    }


def _comment_payload(comment, project_key):
    body_raw = decrypt_or_blank(
        comment.body_ciphertext, project_key,
        associated_data=record_aad("checklistitemcomment", comment.pk, "body"),
    )
    body_html, images_omitted = _render_rich_field(body_raw)
    return {
        "author": str(comment.author) if comment.author else None,
        "created_at": comment.created_at.isoformat(),
        "body_html": body_html,
        "images_omitted": images_omitted,
    }


def _item_payload(item, project_key):
    objectives_html, objectives_images_omitted = _render_rich_field(item.reference_info)

    test_results_raw = decrypt_or_blank(
        item.test_results_ciphertext, project_key,
        associated_data=record_aad("checklistitem", item.pk, "test_results"),
    )
    test_results_html, test_results_images_omitted = _render_rich_field(test_results_raw)

    return {
        "id": str(item.pk),
        "code": item.code,
        "category": item.category,
        "title": item.title,
        "status": item.status,
        "objectives_html": objectives_html,
        "objectives_images_omitted": objectives_images_omitted,
        "test_results_html": test_results_html,
        "test_results_images_omitted": test_results_images_omitted,
        "findings": [_finding_payload(f) for f in item.findings.all()],
        "comments": [_comment_payload(c, project_key) for c in item.comments.all()],
    }


def build_checklist_export(engagement, project_key, *, exported_by):
    runs = engagement.checklist_runs.select_related("template").prefetch_related(
        "items__findings", "items__comments__author",
    )

    run_payloads = []
    total_images_omitted = 0
    for run in runs:
        item_payloads = [_item_payload(item, project_key) for item in run.items.all()]
        for item_payload in item_payloads:
            total_images_omitted += (
                item_payload["objectives_images_omitted"]
                + item_payload["test_results_images_omitted"]
                + sum(c["images_omitted"] for c in item_payload["comments"])
            )
        run_payloads.append({
            "id": str(run.pk),
            "label": run.label,
            "template_name": run.template.name if run.template else None,
            "template_description": run.template.description if run.template else "",
            "created_by": str(run.created_by) if run.created_by else None,
            "created_at": run.created_at.isoformat(),
            "items": item_payloads,
        })

    note = (
        "Rich-text fields (objectives, test results, comments) are exported as HTML. Images "
        "embedded in them are stored as encrypted attachments outside this export and are not "
        "included."
    )
    if total_images_omitted:
        note += f" {total_images_omitted} image(s) across this export were omitted."

    return {
        "engagement_id": str(engagement.pk),
        "client_name": engagement.client_name,
        "exported_at": timezone.now().isoformat(),
        "exported_by": str(exported_by),
        "note": note,
        "images_omitted_total": total_images_omitted,
        "runs": run_payloads,
    }
