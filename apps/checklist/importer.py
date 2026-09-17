import csv
import io
import json

from django.db import transaction

from apps.findings.validators import sanitize_tiptap_image_srcs

from .models import ChecklistTemplate, ChecklistTemplateItem


def _wrap_plain_text(text) -> str:
    text = (text or "").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, dict) and parsed.get("type") == "doc":
            return text
    if not text:
        return json.dumps({"type": "doc", "content": [{"type": "paragraph"}]})
    return json.dumps(
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
    )


def import_json(template_name, description, raw_text, *, uploaded_by):
    try:
        rows = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError("Invalid JSON: too deeply nested.") from exc
    if not isinstance(rows, list):
        raise ValueError("Top-level JSON must be a list of checklist item objects.")
    return _replace_template_items(template_name, description, rows, uploaded_by=uploaded_by)


def import_csv(template_name, description, raw_text, *, uploaded_by):
    reader = csv.DictReader(io.StringIO(raw_text))
    required = {"category", "title"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV must have at least 'category' and 'title' columns.")
    return _replace_template_items(template_name, description, list(reader), uploaded_by=uploaded_by)


@transaction.atomic
def _replace_template_items(template_name, description, rows, *, uploaded_by):
    template, _ = ChecklistTemplate.objects.get_or_create(name=template_name)
    template.description = description
    template.uploaded_by = uploaded_by
    template.save(update_fields=["description", "uploaded_by", "updated_at"])

    template.items.all().delete()

    items = []
    for i, row in enumerate(rows):
        category = (row.get("category") or "").strip()
        title = (row.get("title") or "").strip()
        if not category or not title:
            raise ValueError(f"Row {i + 1}: 'category' and 'title' are required.")
        items.append(ChecklistTemplateItem(
            template=template,
            category=category,
            code=(row.get("code") or "").strip(),
            title=title,
            reference_info=sanitize_tiptap_image_srcs(_wrap_plain_text(row.get("reference_info")), allow_own_blobs=False),
            order=i,
        ))
    ChecklistTemplateItem.objects.bulk_create(items)
    return len(items)


def export_json(template: ChecklistTemplate) -> str:
    return json.dumps(
        [
            {
                "category": item.category,
                "code": item.code,
                "title": item.title,
                "reference_info": item.reference_info,
            }
            for item in template.items.order_by("order")
        ],
        indent=2,
    )
