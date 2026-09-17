from django.db import migrations


def _tag_paragraph(tag_name):
    return {"type": "paragraph", "content": [{"type": "text", "text": f"{{{{ {tag_name} }}}}"}]}


def _heading(text, level=2):
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


def _node_tag(node):
    if not isinstance(node, dict) or node.get("type") != "paragraph":
        return None
    text = "".join(
        c.get("text", "") for c in (node.get("content") or []) if isinstance(c, dict) and c.get("type") == "text"
    ).strip()
    if text.startswith("{{") and text.endswith("}}"):
        return text[2:-2].strip()
    return None


def _heading_text(node):
    if not isinstance(node, dict) or node.get("type") != "heading":
        return None
    return "".join(
        c.get("text", "") for c in (node.get("content") or []) if isinstance(c, dict) and c.get("type") == "text"
    ).strip()


def migrate_templates(apps, schema_editor):
    ReportProfile = apps.get_model("reports", "ReportProfile")
    for profile in ReportProfile.objects.all():
        template = profile.template if isinstance(profile.template, dict) else {}
        nodes = list(template.get("content") or [])
        if not nodes:
            continue

        existing_tags = {_node_tag(n) for n in nodes}
        existing_tags.discard(None)

        # engagement_timeline is being removed outright — strip its tag, and
        # the immediately preceding "Engagement timeline" heading if that's
        # all that heading introduced (leaves everything else untouched).
        cleaned = []
        i = 0
        while i < len(nodes):
            node = nodes[i]
            if _node_tag(node) == "engagement_timeline":
                if cleaned and (_heading_text(cleaned[-1]) or "").strip().lower() == "engagement timeline":
                    cleaned.pop()
                i += 1
                continue
            cleaned.append(node)
            i += 1
        nodes = cleaned

        # Preserve prior default appearance (cover -> document control ->
        # disclaimers -> table of contents, all above the template's own
        # content) for profiles saved before these became opt-in tags.
        prefix = []
        if "cover_page" not in existing_tags:
            prefix.append(_tag_paragraph("cover_page"))
        if "document_control" not in existing_tags:
            prefix.append(_heading("Document control"))
            prefix.append(_tag_paragraph("document_control"))
        if "disclaimers" not in existing_tags:
            prefix.append(_heading("Disclaimers"))
            prefix.append(_tag_paragraph("disclaimers"))
        if "table_of_contents" not in existing_tags:
            prefix.append(_tag_paragraph("table_of_contents"))

        template["content"] = prefix + nodes
        profile.template = template
        profile.save(update_fields=["template"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0019_remove_reportprofile_docx_template_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_templates, noop_reverse),
    ]
