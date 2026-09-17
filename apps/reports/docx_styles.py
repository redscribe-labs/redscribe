import io

from docx import Document
from docx.enum.style import WD_STYLE_TYPE

_BUCKETS = {
    WD_STYLE_TYPE.PARAGRAPH: "paragraph",
    WD_STYLE_TYPE.CHARACTER: "character",
    WD_STYLE_TYPE.TABLE: "table",
}


def discover_styles(docx_bytes: bytes) -> dict[str, list[str]]:
    """Returns {'paragraph': [...names...], 'character': [...], 'table': [...]},
    used to populate the per-role style-mapping dropdowns on the Report
    Profile page. Every style the uploaded template defines is listed
    (including Word's built-ins like "Normal") — no attempt to filter out
    "noise" styles, since that'd risk hiding one the superadmin actually
    wants to map.
    """
    document = Document(io.BytesIO(docx_bytes))
    buckets: dict[str, list[str]] = {"paragraph": [], "character": [], "table": []}
    for style in document.styles:
        bucket = _BUCKETS.get(style.type)
        if bucket is not None and style.name:
            buckets[bucket].append(style.name)
    for names in buckets.values():
        names.sort(key=str.lower)
    return buckets
