import json

from django.db import migrations


# background/qualifications stay TextFields — only what they hold changes,
# from freeform plain text to a Tiptap doc JSON string (same storage shape
# already used for e.g. ReportTextBlockDefinition/TemplateSection content).
# This converts existing values in place so the Tiptap editor has something
# valid to load, and so the report's Assessment team section keeps rendering
# unchanged (qualifications was shown as a bulleted list — one listItem per
# non-blank line reproduces that).
def _paragraphs_doc(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in text.splitlines() if line.strip()
    ]
    return json.dumps({"type": "doc", "content": paragraphs or [{"type": "paragraph"}]})


def _bullet_list_doc(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    items = [
        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": line}]}]}
        for line in text.splitlines() if line.strip()
    ]
    if not items:
        return ""
    return json.dumps({"type": "doc", "content": [{"type": "bulletList", "content": items}]})


def convert_forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        user.background = _paragraphs_doc(user.background)
        user.qualifications = _bullet_list_doc(user.qualifications)
        user.save(update_fields=["background", "qualifications"])


def convert_backward(apps, schema_editor):
    # Best-effort plain-text extraction — not a byte-exact inverse (a Tiptap
    # doc can express things plain text can't), fine for a migration that
    # only needs to leave the field readable if this is ever rolled back.
    User = apps.get_model("accounts", "User")

    def _plain_text(doc_json: str) -> str:
        if not doc_json:
            return ""
        try:
            parsed = json.loads(doc_json)
        except (TypeError, ValueError):
            return doc_json
        lines = []

        def walk(node):
            if not isinstance(node, dict):
                return
            if node.get("type") == "text":
                lines.append(node.get("text", ""))
                return
            for child in node.get("content") or []:
                walk(child)
            if node.get("type") in ("paragraph", "listItem"):
                lines.append("\n")

        walk(parsed)
        return "".join(lines).strip()

    for user in User.objects.all():
        user.background = _plain_text(user.background)
        user.qualifications = _plain_text(user.qualifications)
        user.save(update_fields=["background", "qualifications"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_user_oauth_invite_pending"),
    ]

    operations = [
        migrations.RunPython(convert_forward, convert_backward),
    ]
