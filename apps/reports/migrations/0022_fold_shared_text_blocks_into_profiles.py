from django.db import migrations


def _template_tags(template):
    if not isinstance(template, dict):
        return set()
    tags = set()
    for node in template.get("content") or []:
        if not isinstance(node, dict) or node.get("type") != "paragraph":
            continue
        text = "".join(
            c.get("text", "") for c in (node.get("content") or []) if isinstance(c, dict) and c.get("type") == "text"
        ).strip()
        if text.startswith("{{") and text.endswith("}}"):
            tags.add(text[2:-2].strip())
    return tags


def fold_shared_blocks(apps, schema_editor):
    ReportProfile = apps.get_model("reports", "ReportProfile")
    ReportTextBlockDefinition = apps.get_model("reports", "ReportTextBlockDefinition")

    shared_blocks = {b.slug: b for b in ReportTextBlockDefinition.objects.filter(profile__isnull=True)}
    if not shared_blocks:
        return

    for profile in ReportProfile.objects.all():
        used_tags = _template_tags(profile.template)
        own_slugs = set(
            ReportTextBlockDefinition.objects.filter(profile=profile).values_list("slug", flat=True)
        )
        block_defaults = dict(profile.block_defaults) if isinstance(profile.block_defaults, dict) else {}
        changed = False
        for tag in used_tags:
            shared = shared_blocks.get(tag)
            if shared is None or tag in own_slugs:
                continue
            ReportTextBlockDefinition.objects.create(
                profile=profile, slug=shared.slug, label=shared.label,
                is_active=shared.is_active,
                include_in_remediation_report_only=shared.include_in_remediation_report_only,
            )
            block_defaults.setdefault(shared.slug, shared.content)
            changed = True
        if changed:
            profile.block_defaults = block_defaults
            profile.save(update_fields=["block_defaults"])

    ReportTextBlockDefinition.objects.filter(profile__isnull=True).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0021_reportprofile_empty_cell_background_color"),
    ]

    operations = [
        migrations.RunPython(fold_shared_blocks, noop_reverse),
    ]
