import json
import uuid

from django.db import transaction

from apps.crypto.services import encrypt_bytes, record_aad

from .classifications import save_classification_rows
from .importers import burp, nmap, nuclei
from .models import ContentSectionDefinition, Finding, FindingSection, ScanImportRecord
from .validators import CVE_ID_RE

PARSERS = {"NMAP": nmap.parse, "BURP": burp.parse, "NUCLEI": nuclei.parse}
FORMAT_LABELS = {"NMAP": "Nmap", "BURP": "Burp Suite", "NUCLEI": "Nuclei"}


def _to_doc_json(text: str) -> str:
    text = (text or "").strip()
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in text.splitlines() if line.strip()
    ]
    if not paragraphs:
        paragraphs = [{"type": "paragraph"}]
    return json.dumps({"type": "doc", "content": paragraphs})


def parse_scan(raw, fmt: str):
    parser = PARSERS.get(fmt)
    if parser is None:
        raise ValueError(f"Unsupported scan format: {fmt!r}")
    return parser(raw)


def preview_rows(engagement, imported) -> list[dict]:
    """What import_scan would create, for the confirm step. Flags results that
    look like a finding this engagement already has (same title and affects)."""
    existing = set(engagement.findings.values_list("title", "affects"))
    return [
        {
            "index": index,
            "title": item.title[:255],
            "severity": item.severity,
            "severity_label": dict(Finding.Severity.choices).get(item.severity, item.severity),
            "detail": " · ".join(part for part in [item.affects, item.cve_id] if part),
            "duplicate": (item.title[:255], item.affects) in existing,
        }
        for index, item in enumerate(imported)
    ]


def import_target_section():
    """The section a scan result's technical details are written into, or None
    when no active section is ticked as the import target (the details are then
    dropped — the import page warns about this up front)."""
    return ContentSectionDefinition.objects.filter(is_import_target=True, is_active=True).narrative().first()


@transaction.atomic
def import_scan(*, engagement, project_key, raw, fmt: str, imported_by, filename: str = "", only=None) -> int:
    """only: optional set of result indexes (from preview_rows) to import; the
    rest are skipped."""
    imported = parse_scan(raw, fmt)
    if only is not None:
        imported = [item for index, item in enumerate(imported) if index in only]

    import_target = import_target_section()

    count = 0
    for item in imported:
        cve_id = item.cve_id if item.cve_id and CVE_ID_RE.match(item.cve_id) else ""
        finding_id = uuid.uuid4()
        finding = Finding(
            id=finding_id,
            engagement=engagement,
            title=item.title[:255],
            severity=item.severity,
            cve_id=cve_id,
            affects=item.affects,
            created_by=imported_by,
        )
        finding.save()
        if import_target is not None:
            FindingSection.objects.create(
                finding=finding, definition=import_target,
                content_ciphertext=encrypt_bytes(
                    _to_doc_json(item.technical_details).encode("utf-8"), project_key,
                    associated_data=record_aad("finding", finding_id, import_target.slug),
                ),
            )
        if item.tags:
            rows = [{"taxonomy": FORMAT_LABELS[fmt], "value": tag} for tag in item.tags]
            finding.classifications.set(save_classification_rows(rows))
        count += 1

    # Recorded regardless of count — a scan that found nothing is still
    # evidence that tool coverage happened, which is exactly what a
    # report's scan-imports appendix exists to show.
    ScanImportRecord.objects.create(
        engagement=engagement, source_format=fmt, filename=filename[:255],
        findings_created=count, imported_by=imported_by,
    )
    return count
