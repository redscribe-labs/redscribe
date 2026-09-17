import json

from .base import ImportedFinding

_SEVERITY_MAP = {
    "critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM",
    "low": "LOW", "info": "INFORMATIONAL", "unknown": "INFORMATIONAL",
}


def _tags_of(info: dict) -> list[str]:
    raw = info.get("tags") or []
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return [str(t).strip() for t in raw if str(t).strip()]


def _cve_of(info: dict) -> str:
    classification = info.get("classification") or {}
    cve_ids = classification.get("cve-id") or []
    if isinstance(cve_ids, str):
        return cve_ids
    return cve_ids[0] if cve_ids else ""


def parse(raw) -> list[ImportedFinding]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")

    results = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {lineno}: invalid JSON ({exc}).") from exc
        except RecursionError as exc:
            raise ValueError(f"Line {lineno}: invalid JSON (too deeply nested).") from exc

        info = row.get("info") or {}
        name = info.get("name") or row.get("template-id") or "Untitled finding"
        severity = _SEVERITY_MAP.get((info.get("severity") or "").lower(), "INFORMATIONAL")
        matched_at = row.get("matched-at") or row.get("host") or ""
        template_id = row.get("template-id") or ""
        description = (info.get("description") or "").strip()

        details = [f"Template: {template_id}"]
        if description:
            details.append(description)
        if matched_at:
            details.append(f"Matched at: {matched_at}")

        results.append(ImportedFinding(
            title=f"{name} ({matched_at})" if matched_at else name,
            severity=severity,
            affects=matched_at,
            technical_details="\n\n".join(details),
            cve_id=_cve_of(info),
            tags=_tags_of(info),
        ))

    if not results:
        raise ValueError("No results found in this Nuclei output (expected one JSON object per line).")
    return results
