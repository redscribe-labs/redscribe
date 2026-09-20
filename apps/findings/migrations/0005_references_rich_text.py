"""
`references` moves from a plain "one link per line" field to full rich
text (Tiptap JSON), same as vulnerability_description/business_impact/etc,
so a reference can be a real hyperlink (source name as link text) instead
of a bare URL. Existing values are plain newline-separated text, not JSON,
so they're converted here rather than left to break the editor/report
renderer — each line becomes a paragraph, and any http(s) URL found in a
line is turned into a real link mark rather than left as bare text.
"""
import json
import re

from django.db import migrations

_URL_RE = re.compile(r"https?://\S+")
_TRAILING_PUNCT = ".,;:)]}\"'"


def _line_to_paragraph(line: str) -> dict:
    content = []
    pos = 0
    for match in _URL_RE.finditer(line):
        if match.start() > pos:
            content.append({"type": "text", "text": line[pos:match.start()]})
        url = match.group(0)
        end = match.end()
        while url and url[-1] in _TRAILING_PUNCT:
            url = url[:-1]
            end -= 1
        content.append({"type": "text", "text": url, "marks": [{"type": "link", "attrs": {"href": url}}]})
        pos = end
    if pos < len(line):
        content.append({"type": "text", "text": line[pos:]})
    if not content:
        content = [{"type": "text", "text": line}]
    return {"type": "paragraph", "content": content}


def _text_to_doc_json(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return json.dumps({"type": "doc", "content": [_line_to_paragraph(line) for line in lines]})


def convert_references_to_rich_text(apps, schema_editor):
    Finding = apps.get_model("findings", "Finding")
    VulnerabilityTemplate = apps.get_model("findings", "VulnerabilityTemplate")

    for model in (Finding, VulnerabilityTemplate):
        for obj in model.objects.exclude(references="").iterator():
            obj.references = _text_to_doc_json(obj.references)
            obj.save(update_fields=["references"])


class Migration(migrations.Migration):

    dependencies = [
        ("findings", "0004_remove_self_reviewed"),
    ]

    operations = [
        migrations.RunPython(convert_references_to_rich_text, migrations.RunPython.noop),
    ]
