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


_ALLOWED_IMAGE_SRC_RE = re.compile(r"^/engagements/[0-9a-fA-F-]{36}/blobs/[0-9a-fA-F-]{36}/?(?:\?.*)?$")
_MAX_SANITIZE_DEPTH = 60


def _strip_images(node, *, allow_own_blobs: bool, depth: int = 0):
    if depth > _MAX_SANITIZE_DEPTH or not isinstance(node, dict):
        return node
    content = node.get("content")
    if isinstance(content, list):
        kept = []
        for child in content:
            if isinstance(child, dict) and child.get("type") == "image":
                src = (child.get("attrs") or {}).get("src")
                if allow_own_blobs and isinstance(src, str) and _ALLOWED_IMAGE_SRC_RE.match(src):
                    kept.append(child)
                continue
            kept.append(_strip_images(child, allow_own_blobs=allow_own_blobs, depth=depth + 1))
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
    if depth > _MAX_SANITIZE_DEPTH or not isinstance(node, dict):
        return node
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
        node["content"] = [_strip_disallowed_links(child, depth=depth + 1) for child in content]
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
