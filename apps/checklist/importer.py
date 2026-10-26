import csv
import io
import json

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.findings.validators import (
    sanitize_tiptap_image_srcs,
    sanitize_tiptap_link_hrefs,
    validate_tiptap_doc_json,
)

from .models import ChecklistTemplate, ChecklistTemplateItem


EXPORT_FORMAT = "redscribe-checklist-template"
EXPORT_VERSION = 1

_EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}


def _is_doc(value) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "doc"
        and isinstance(value.get("content", []), list)
    )


def _wrap_plain_text(text) -> str:
    text = (text or "").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, RecursionError):
            parsed = None
        if _is_doc(parsed):
            return text
    if not text:
        return json.dumps(_EMPTY_DOC)
    return json.dumps(
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
    )


def _clean_reference(value, row_number) -> str:
    """Accept plain text, a Tiptap doc as a JSON string, or a Tiptap doc object."""
    if value is None:
        value = ""
    elif isinstance(value, dict):
        if not _is_doc(value):
            raise ValueError(f"Row {row_number}: 'reference_info' object must be a Tiptap document (type 'doc').")
        value = json.dumps(value)
    elif not isinstance(value, str):
        raise ValueError(f"Row {row_number}: 'reference_info' must be text or a Tiptap document object.")
    wrapped = _wrap_plain_text(value)
    try:
        validate_tiptap_doc_json(wrapped)
    except ValidationError as exc:
        raise ValueError(f"Row {row_number}: 'reference_info' {exc.messages[0][0].lower()}{exc.messages[0][1:]}") from exc
    return sanitize_tiptap_link_hrefs(sanitize_tiptap_image_srcs(wrapped, allow_own_blobs=False))


def _text_field(row, key, row_number, max_length):
    """A short text field from an import row. Numbers are accepted (a code of 42); other types aren't."""
    value = row.get(key)
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"Row {row_number}: '{key}' must be text.")
    value = str(value).strip()
    if len(value) > max_length:
        raise ValueError(f"Row {row_number}: '{key}' is too long ({len(value)} characters, max {max_length}).")
    return value


def _parse_json_payload(raw_text):
    """Return (name, description, rows). Accepts the versioned envelope or a bare list of items."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError("Invalid JSON: too deeply nested.") from exc
    if isinstance(data, list):
        return "", "", data
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be a template object or a list of checklist item objects.")
    if data.get("format", EXPORT_FORMAT) != EXPORT_FORMAT:
        raise ValueError(f"Unrecognised file format {data.get('format')!r}.")
    version = data.get("version", EXPORT_VERSION)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("Template file has an invalid 'version'.")
    if version > EXPORT_VERSION:
        raise ValueError(
            f"This template file is format version {version}; this RedScribe understands up to {EXPORT_VERSION}."
        )
    rows = data.get("items")
    if not isinstance(rows, list):
        raise ValueError("Template object must have an 'items' list.")
    name, description = data.get("name") or "", data.get("description") or ""
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError("Template 'name' and 'description' must be text.")
    return name.strip(), description, rows


def import_file(fmt, template_name, description, raw_text, *, uploaded_by):
    """Import a template and return (template, item_count). The form's name and
    description win over the ones in the file; the file's fill in when blank."""
    template_name = (template_name or "").strip()
    name_from_file = False
    if fmt == "json":
        file_name, file_description, rows = _parse_json_payload(raw_text)
        name_from_file = not template_name and bool(file_name)
        template_name = template_name or file_name
        description = description or file_description
    else:
        rows = _read_csv_rows(raw_text)
    if not template_name:
        raise ValueError("Give the template a name: the file doesn't include one.")
    if len(template_name) > 255:
        raise ValueError("The template name is too long (max 255 characters).")
    # Importing replaces a template's items, so a name that only came from the
    # file must not be able to do that to an existing template unannounced.
    if name_from_file and ChecklistTemplate.objects.filter(name=template_name).exists():
        raise ValueError(
            f"A template named '{template_name}' already exists. Type that name in the Name box to replace "
            "its items, or use a different name."
        )
    return _replace_template_items(template_name, description, rows, uploaded_by=uploaded_by)


def import_json(template_name, description, raw_text, *, uploaded_by):
    return import_file("json", template_name, description, raw_text, uploaded_by=uploaded_by)[1]


def _read_csv_rows(raw_text):
    reader = csv.DictReader(io.StringIO(raw_text))
    required = {"category", "title"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV must have at least 'category' and 'title' columns.")
    return list(reader)


def import_csv(template_name, description, raw_text, *, uploaded_by):
    return import_file("csv", template_name, description, raw_text, uploaded_by=uploaded_by)[1]


@transaction.atomic
def _replace_template_items(template_name, description, rows, *, uploaded_by):
    template, _ = ChecklistTemplate.objects.get_or_create(name=template_name)
    template.description = description
    template.uploaded_by = uploaded_by
    template.save(update_fields=["description", "uploaded_by", "updated_at"])

    template.items.all().delete()

    items = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Row {i + 1}: each item must be an object.")
        category = _text_field(row, "category", i + 1, 255)
        title = _text_field(row, "title", i + 1, 500)
        if not category or not title:
            raise ValueError(f"Row {i + 1}: 'category' and 'title' are required.")
        items.append(ChecklistTemplateItem(
            template=template,
            category=category,
            code=_text_field(row, "code", i + 1, 32),
            title=title,
            reference_info=_clean_reference(row.get("reference_info"), i + 1),
            order=i,
        ))
    ChecklistTemplateItem.objects.bulk_create(items)
    return template, len(items)


def _reference_for_export(raw):
    raw = (raw or "").strip()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return raw
    return parsed if _is_doc(parsed) else raw


def export_json(template: ChecklistTemplate) -> str:
    return json.dumps(
        {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "name": template.name,
            "description": template.description,
            "is_default": template.is_default,
            "items": [
                {
                    "category": item.category,
                    "code": item.code,
                    "title": item.title,
                    "reference_info": _reference_for_export(item.reference_info),
                }
                for item in template.items.order_by("order")
            ],
        },
        indent=2,
    )
