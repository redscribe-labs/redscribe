import base64
import re
from html import unescape

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .base import ImportedFinding

_SEVERITY_MAP = {
    "High": "HIGH", "Medium": "MEDIUM", "Low": "LOW",
    "Information": "INFORMATIONAL", "False Positive": "INFORMATIONAL",
}
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(html_text: str) -> str:
    text = _TAG_RE.sub(" ", unescape(html_text or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _text_of(el) -> str:
    if el is None:
        return ""
    text = el.text or ""
    if el.get("isBase64") == "true":
        try:
            text = base64.b64decode(text).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            pass
    return text


def parse(raw) -> list[ImportedFinding]:
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise ValueError(f"Invalid Burp Suite XML: {exc}") from exc
    if root.tag != "issues":
        raise ValueError("Not a Burp Suite XML report (root element must be <issues>).")

    results = []
    for issue in root.findall("issue"):
        name = (issue.findtext("name") or "Untitled issue").strip()
        host = (issue.findtext("host") or "").strip()
        path = (issue.findtext("path") or "").strip()
        severity = _SEVERITY_MAP.get((issue.findtext("severity") or "").strip(), "INFORMATIONAL")

        detail = _strip_html(_text_of(issue.find("issueDetail")))
        background = _strip_html(_text_of(issue.find("issueBackground")))
        remediation = _strip_html(_text_of(issue.find("remediationBackground")))

        parts = []
        if detail:
            parts.append(f"Detail:\n{detail}")
        if background:
            parts.append(f"Background:\n{background}")
        if remediation:
            parts.append(f"Suggested remediation:\n{remediation}")

        affects = f"{host}{path}" if host else path
        results.append(ImportedFinding(
            title=f"{name} ({affects})" if affects else name,
            severity=severity,
            affects=affects,
            technical_details="\n\n".join(parts),
            tags=["Web Application Scan"],
        ))

    if not results:
        raise ValueError("No issues found in this Burp Suite report.")
    return results
