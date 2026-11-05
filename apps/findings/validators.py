import json
import re

from django.core.exceptions import ValidationError

CVSS_V3_1_BASE = [
    ("AV", "NALP"), ("AC", "LH"), ("PR", "NLH"), ("UI", "NR"),
    ("S", "UC"), ("C", "NLH"), ("I", "NLH"), ("A", "NLH"),
]
CVSS_V3_1_OPTIONAL = {
    "E": "XUPFH", "RL": "XOTWU", "RC": "XURC",
    "CR": "XLMH", "IR": "XLMH", "AR": "XLMH",
    "MAV": "XNALP", "MAC": "XLH", "MPR": "XNLH", "MUI": "XNR", "MS": "XUC",
    "MC": "XNLH", "MI": "XNLH", "MA": "XNLH",
}

CVSS_V4_0_BASE = [
    ("AV", "NALP"), ("AC", "LH"), ("AT", "NP"), ("PR", "NLH"), ("UI", "NPA"),
    ("VC", "HLN"), ("VI", "HLN"), ("VA", "HLN"),
    ("SC", "HLN"), ("SI", "HLN"), ("SA", "HLN"),
]
CVSS_V4_0_OPTIONAL_ABBREVIATIONS = {
    "E", "CR", "IR", "AR", "MAV", "MAC", "MAT", "MPR", "MUI",
    "MVC", "MVI", "MVA", "MSC", "MSI", "MSA",
    "S", "AU", "R", "V", "RE", "U",
}

CVE_ID_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")


def _validate_base(tokens, base_defs, vector):
    if len(tokens) < len(base_defs):
        raise ValidationError(f"Missing required base metrics in CVSS vector: {vector!r}")
    for token, (metric, allowed) in zip(tokens, base_defs):
        if ":" not in token:
            raise ValidationError(f"Malformed metric {token!r} in CVSS vector: {vector!r}")
        name, value = token.split(":", 1)
        if name != metric or value not in allowed:
            raise ValidationError(
                f"Invalid or out-of-order metric {token!r} (expected {metric}:[{allowed}]) "
                f"in CVSS vector: {vector!r}"
            )


def _validate_optional_v3_1(tokens, vector):
    seen = set()
    for token in tokens:
        if ":" not in token:
            raise ValidationError(f"Malformed metric {token!r} in CVSS vector: {vector!r}")
        name, value = token.split(":", 1)
        if name not in CVSS_V3_1_OPTIONAL:
            raise ValidationError(f"Unknown metric {name!r} in CVSS v3.1 vector: {vector!r}")
        if name in seen:
            raise ValidationError(f"Duplicate metric {name!r} in CVSS vector: {vector!r}")
        seen.add(name)
        if value not in CVSS_V3_1_OPTIONAL[name]:
            raise ValidationError(f"Invalid value for metric {name!r} in CVSS vector: {vector!r}")


def _validate_optional_v4_0(tokens, vector):
    seen = set()
    for token in tokens:
        if ":" not in token:
            raise ValidationError(f"Malformed metric {token!r} in CVSS vector: {vector!r}")
        name, value = token.split(":", 1)
        if name not in CVSS_V4_0_OPTIONAL_ABBREVIATIONS:
            raise ValidationError(f"Unknown metric {name!r} in CVSS v4.0 vector: {vector!r}")
        if name in seen:
            raise ValidationError(f"Duplicate metric {name!r} in CVSS vector: {vector!r}")
        seen.add(name)
        if not (1 <= len(value) <= 8 and value.isalnum()):
            raise ValidationError(f"Invalid value for metric {name!r} in CVSS vector: {vector!r}")


def validate_cvss_vector(value: str) -> None:
    value = (value or "").strip()
    if not value:
        return

    parts = value.split("/")
    header, metric_tokens = parts[0], parts[1:]

    if header == "CVSS:3.1":
        _validate_base(metric_tokens[: len(CVSS_V3_1_BASE)], CVSS_V3_1_BASE, value)
        _validate_optional_v3_1(metric_tokens[len(CVSS_V3_1_BASE):], value)
    elif header == "CVSS:4.0":
        _validate_base(metric_tokens[: len(CVSS_V4_0_BASE)], CVSS_V4_0_BASE, value)
        _validate_optional_v4_0(metric_tokens[len(CVSS_V4_0_BASE):], value)
    else:
        raise ValidationError(
            f"CVSS vector must start with 'CVSS:3.1' or 'CVSS:4.0', got {header!r}."
        )


def validate_cvss_score(value: str) -> None:
    """Blank (unscored) is fine; otherwise a plain number from 0.0 to 10.0."""
    value = (value or "").strip()
    if not value:
        return
    if not re.fullmatch(r"\d{1,2}(\.\d)?", value) or float(value) > 10.0:
        raise ValidationError("CVSS score must be a number from 0.0 to 10.0 (one decimal place), e.g. 8.6.")


def cvss_severity_for_score(score: float) -> str:
    """Qualitative severity band (CVSS v3.1/v4.0 rating scale) for a score."""
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    if score > 0.0:
        return "LOW"
    return "INFORMATIONAL"


_V31_W = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "CIA": {"H": 0.56, "L": 0.22, "N": 0.0},
}


def _roundup(x: float) -> float:
    n = round(x * 100000)
    return n / 100000.0 if n % 10000 == 0 else (n // 10000 + 1) / 10.0


def cvss_v31_base_score(vector: str):
    """Base score of a CVSS:3.1 vector, or None if it carries any
    temporal/environmental metric (the entered score may then differ)."""
    parts = vector.strip().split("/")
    if parts[0] != "CVSS:3.1" or len(parts) != 9:
        return None
    try:
        m = dict(t.split(":", 1) for t in parts[1:])
        changed = m["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[m["PR"]]
        iss = 1 - (1 - _V31_W["CIA"][m["C"]]) * (1 - _V31_W["CIA"][m["I"]]) * (1 - _V31_W["CIA"][m["A"]])
        expl = 8.22 * _V31_W["AV"][m["AV"]] * _V31_W["AC"][m["AC"]] * pr * _V31_W["UI"][m["UI"]]
    except (KeyError, ValueError):
        return None
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    return _roundup(min((1.08 if changed else 1.0) * (impact + expl), 10.0))


def validate_cvss_consistency(score: str, vector: str, severity: str) -> None:
    """Cross-field check: the severity must fall in the score's band, and a
    base-only CVSS:3.1 vector must produce the entered score. Raises
    ValidationError (callers attach it to the right field)."""
    score = (score or "").strip()
    if not score:
        return
    try:
        value = float(score)
    except ValueError:
        # Non-numeric score (e.g. a legacy free-text value): its format is
        # reported separately by validate_cvss_score, so there's nothing to
        # cross-check here. Returning avoids a ValueError bubbling up as a 500.
        return
    expected = cvss_severity_for_score(value)
    if severity and severity != expected:
        raise ValidationError(
            f"Severity {severity.title()} doesn't match a CVSS score of {score} ({expected.title()})."
        )
    computed = cvss_v31_base_score((vector or "").strip())
    if computed is not None and abs(computed - value) > 0.05:
        raise ValidationError(f"CVSS score {score} doesn't match the vector, which scores {computed:.1f}.")


# The sanitizers below walk the document down to this depth. Anything deeper
# can't be checked, so the validator rejects it and the sanitizers drop it.
_MAX_SANITIZE_DEPTH = 60


def _exceeds_depth(node, depth: int = 0) -> bool:
    if not isinstance(node, dict):
        return False
    if depth > _MAX_SANITIZE_DEPTH:
        return True
    content = node.get("content")
    return isinstance(content, list) and any(_exceeds_depth(child, depth + 1) for child in content)


def validate_tiptap_doc_json(value: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise ValidationError("Rich text content is not valid JSON.")
    if not isinstance(parsed, dict) or parsed.get("type") != "doc":
        raise ValidationError("Rich text content must be a Tiptap document (type: 'doc').")
    if _exceeds_depth(parsed):
        raise ValidationError("Rich text content is nested too deeply.")


_ALLOWED_IMAGE_SRC_RE = re.compile(r"^/engagements/[0-9a-fA-F-]{36}/blobs/[0-9a-fA-F-]{36}/?(?:\?.*)?$")


def _strip_images(node, *, allow_own_blobs: bool, depth: int = 0):
    """Returns None for a node too deep to check, so the caller drops it."""
    if not isinstance(node, dict):
        return node
    if depth > _MAX_SANITIZE_DEPTH:
        return None
    content = node.get("content")
    if isinstance(content, list):
        kept = []
        for child in content:
            if isinstance(child, dict) and child.get("type") == "image":
                src = (child.get("attrs") or {}).get("src")
                if allow_own_blobs and isinstance(src, str) and _ALLOWED_IMAGE_SRC_RE.match(src):
                    kept.append(child)
                continue
            cleaned = _strip_images(child, allow_own_blobs=allow_own_blobs, depth=depth + 1)
            if cleaned is not None:
                kept.append(cleaned)
        node["content"] = kept
    return node


def sanitize_tiptap_image_srcs(value: str, *, allow_own_blobs: bool = True) -> str:
    value = (value or "").strip()
    if not value:
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return value
    if not isinstance(parsed, dict):
        return value
    _strip_images(parsed, allow_own_blobs=allow_own_blobs)
    return json.dumps(parsed)


# Same allowlist the read-only renderer applies (apps/reports/tiptap_render.py,
# _ALLOWED_LINK_PROTOCOLS) — kept here as an independent server-side check
# rather than importing that module, so a link mark is stripped at write time
# regardless of which renderer eventually displays it, and regardless of
# whether a submission went through the Tiptap editor at all (a form POST
# built by hand skips the editor's own client-side protocol allowlist).
_ALLOWED_LINK_HREF_RE = re.compile(r"^(?:https?://|mailto:)", re.IGNORECASE)


def _strip_disallowed_links(node, depth: int = 0):
    """Returns None for a node too deep to check, so the caller drops it."""
    if not isinstance(node, dict):
        return node
    if depth > _MAX_SANITIZE_DEPTH:
        return None
    marks = node.get("marks")
    if isinstance(marks, list):
        kept_marks = []
        for mark in marks:
            if isinstance(mark, dict) and mark.get("type") == "link":
                href = (mark.get("attrs") or {}).get("href")
                if not isinstance(href, str) or not _ALLOWED_LINK_HREF_RE.match(href.strip()):
                    continue
            kept_marks.append(mark)
        node["marks"] = kept_marks
    content = node.get("content")
    if isinstance(content, list):
        cleaned = (_strip_disallowed_links(child, depth=depth + 1) for child in content)
        node["content"] = [child for child in cleaned if child is not None]
    return node


def sanitize_tiptap_link_hrefs(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return value
    if not isinstance(parsed, dict):
        return value
    _strip_disallowed_links(parsed)
    return json.dumps(parsed)


def validate_cve_id(value: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    if not CVE_ID_RE.match(value):
        raise ValidationError("CVE ID must look like CVE-YYYY-NNNN (year, then 4+ digits).")
