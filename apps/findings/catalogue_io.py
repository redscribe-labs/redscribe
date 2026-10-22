import json
from collections import Counter

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


def parse_templates(raw_text: str) -> list[dict]:
    """Validates an export file and returns its cleaned entries, in file order.
    Raises CatalogueImportError on the first problem."""
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
    return [_clean_entry(i + 1, entry, definitions_by_slug) for i, entry in enumerate(raw_entries)]


def section_notices(raw_text: str) -> list[str]:
    """Warnings for the confirm step about section content that won't show up
    after import: sections this instance doesn't have (skipped — matched by
    slug, not label) and retired ones (stored, but hidden until re-activated).
    Call only after parse_templates has accepted raw_text."""
    definitions_by_slug = {d.slug: d for d in ContentSectionDefinition.objects.all()}
    missing, retired = Counter(), Counter()
    for entry in json.loads(raw_text):
        for slug, value in (entry.get("sections") or {}).items():
            if not value:
                continue
            definition = definitions_by_slug.get(slug)
            if definition is None:
                missing[slug] += 1
            elif not definition.is_active:
                retired[definition.label] += 1

    def listed(counter):
        return ", ".join(f"'{name}' ({n} entr{'y' if n == 1 else 'ies'})" for name, n in counter.most_common())

    notices = []
    if missing:
        notices.append(
            f"Content for sections this instance doesn't have will be skipped: {listed(missing)}. "
            "Sections are matched by their internal name, not their label — add matching sections in "
            "Finding structure before importing to keep it."
        )
    if retired:
        notices.append(
            f"Content for retired sections will be imported but stay hidden until they're re-activated: {listed(retired)}."
        )
    return notices


def preview_rows(cleaned_entries) -> list[dict]:
    """What import_templates would create, for the confirm step. Flags entries
    whose title matches one already in the catalogue (import never merges)."""
    existing = {t.lower() for t in VulnerabilityTemplate.objects.values_list("title", flat=True)}
    rows = []
    for index, entry in enumerate(cleaned_entries):
        sections = len(entry["sections"])
        classifications = ", ".join(f"{r['taxonomy']} {r['value']}" for r in entry["classifications"][:3])
        rows.append({
            "index": index,
            "title": entry["title"],
            "severity": entry["default_severity"],
            "severity_label": dict(Finding.Severity.choices).get(entry["default_severity"], entry["default_severity"]),
            "detail": " · ".join(part for part in [
                f"{sections} section{'s' if sections != 1 else ''}", classifications,
            ] if part),
            "duplicate": entry["title"].lower() in existing,
        })
    return rows


@transaction.atomic
def import_templates(raw_text: str, *, created_by, only=None) -> list[VulnerabilityTemplate]:
    """only: optional set of entry indexes (from preview_rows) to import."""
    cleaned_entries = parse_templates(raw_text)
    if only is not None:
        cleaned_entries = [entry for index, entry in enumerate(cleaned_entries) if index in only]

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
