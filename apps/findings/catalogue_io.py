import json

from django.db import transaction

from .classifications import save_classification_rows
from .models import ContentSectionDefinition, Finding, TemplateSection, VulnerabilityTemplate
from .validators import sanitize_tiptap_image_srcs, validate_cvss_vector, validate_tiptap_doc_json


class CatalogueImportError(Exception):
    pass


def _wrap_plain_text(text: str) -> str:
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


def export_templates(queryset) -> str:
    entries = []
    for template in queryset.prefetch_related("classifications", "sections__definition").order_by("title"):
        entry = {
            "title": template.title,
            "default_severity": template.default_severity,
            "default_cvss_score": template.default_cvss_score,
            "default_cvss_vector": template.default_cvss_vector,
            "classifications": [
                {"taxonomy": t.taxonomy, "value": t.value} for t in template.classifications.all()
            ],
            "sections": {},
        }
        for template_section in template.sections.all():
            raw = template_section.content
            try:
                entry["sections"][template_section.definition.slug] = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                entry["sections"][template_section.definition.slug] = None
        entries.append(entry)
    return json.dumps(entries, indent=2)


def _clean_entry(index: int, raw_entry, definitions_by_slug: dict) -> dict:
    if not isinstance(raw_entry, dict):
        raise CatalogueImportError(f"Entry {index}: must be a JSON object.")

    title = str(raw_entry.get("title") or "").strip()
    if not title:
        raise CatalogueImportError(f"Entry {index}: missing 'title'.")

    severity = str(raw_entry.get("default_severity") or "").strip().upper()
    if severity not in Finding.Severity.values:
        raise CatalogueImportError(
            f"Entry {index} ('{title}'): default_severity must be one of {', '.join(Finding.Severity.values)}."
        )

    cvss_vector = str(raw_entry.get("default_cvss_vector") or "").strip()
    try:
        validate_cvss_vector(cvss_vector)
    except Exception as exc:
        raise CatalogueImportError(f"Entry {index} ('{title}'): {exc}") from exc

    cleaned = {
        "title": title,
        "default_severity": severity,
        "default_cvss_score": str(raw_entry.get("default_cvss_score") or "").strip(),
        "default_cvss_vector": cvss_vector,
    }

    raw_sections = raw_entry.get("sections") or {}
    if not isinstance(raw_sections, dict):
        raise CatalogueImportError(f"Entry {index} ('{title}'): 'sections' must be an object.")
    cleaned_sections = {}
    for slug, value in raw_sections.items():
        definition = definitions_by_slug.get(slug)
        if definition is None:
            continue
        text = json.dumps(value) if isinstance(value, dict) else (value or "")
        wrapped = _wrap_plain_text(text)
        try:
            validate_tiptap_doc_json(wrapped)
        except Exception as exc:
            raise CatalogueImportError(f"Entry {index} ('{title}'), section '{slug}': {exc}") from exc
        cleaned_sections[definition.id] = sanitize_tiptap_image_srcs(wrapped, allow_own_blobs=False)
    cleaned["sections"] = cleaned_sections

    raw_classifications = raw_entry.get("classifications") or []
    if not isinstance(raw_classifications, list):
        raise CatalogueImportError(f"Entry {index} ('{title}'): 'classifications' must be a list.")
    rows = []
    for row in raw_classifications:
        if not isinstance(row, dict) or not row.get("taxonomy") or not row.get("value"):
            raise CatalogueImportError(
                f"Entry {index} ('{title}'): each classification needs a 'taxonomy' and a 'value'."
            )
        rows.append({"taxonomy": str(row["taxonomy"]).strip(), "value": str(row["value"]).strip()})
    cleaned["classifications"] = rows
    return cleaned


@transaction.atomic
def import_templates(raw_text: str, *, created_by) -> list[VulnerabilityTemplate]:
    try:
        raw_entries = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise CatalogueImportError(f"Invalid JSON: {exc}") from exc
    except RecursionError as exc:
        raise CatalogueImportError("Invalid JSON: too deeply nested.") from exc
    if not isinstance(raw_entries, list):
        raise CatalogueImportError("Top-level JSON must be a list of catalogue entry objects.")
    if not raw_entries:
        raise CatalogueImportError("No entries found in the uploaded file.")

    definitions_by_slug = {d.slug: d for d in ContentSectionDefinition.objects.all()}
    cleaned_entries = [_clean_entry(i + 1, entry, definitions_by_slug) for i, entry in enumerate(raw_entries)]

    created = []
    for entry in cleaned_entries:
        rows = entry.pop("classifications")
        sections = entry.pop("sections")
        template = VulnerabilityTemplate.objects.create(created_by=created_by, **entry)
        template.classifications.set(save_classification_rows(rows))
        for definition_id, content in sections.items():
            TemplateSection.objects.create(template=template, definition_id=definition_id, content=content)
        created.append(template)
    return created
