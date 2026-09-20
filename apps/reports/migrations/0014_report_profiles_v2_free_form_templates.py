"""
Report Profiles v2 — replaces the node-tree `ReportProfile.structure`
(type/parent_id/order per node) with a free-form `template` Tiptap
document authored directly, using headings for structure and literal
`{{ tag_name }}` placeholders for computed/custom content (see
apps.reports.models.ReportProfile's docstring and apps.reports.assembly.
_parse_template).

Also renames every ReportTextBlockDefinition's slug from the old
hyphenated form ("summary-of-testing") to underscores
("summary_of_testing") — a `{{ tag }}` placeholder only matches
`[a-zA-Z0-9_]+` (apps.reports.placeholders._TOKEN_RE, the same convention
already used for {{ client_name }} etc.), so a hyphenated slug could never
actually be typed as a working placeholder. Any ReportConfig.content
["dynamic"] key referencing an old slug is renamed to match, so no
reporter's already-written per-engagement text is orphaned.

The schema changes and this data migration are combined into one
migration (rather than split into a schema migration + a following data
migration) because the data migration needs to read `structure` and
`dynamic_defaults` before they're dropped, and needs `template`/
`block_defaults`/`include_in_remediation_report_only` to already exist to
write into them — operations run in the order listed below.
"""
from django.db import migrations, models


def _heading(level: int, text: str) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


def _tag(slug: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": f"{{{{ {slug} }}}}"}]}


def migrate_data(apps, schema_editor):
    ReportTextBlockDefinition = apps.get_model("reports", "ReportTextBlockDefinition")
    ReportProfile = apps.get_model("reports", "ReportProfile")
    ReportSettings = apps.get_model("reports", "ReportSettings")
    ReportConfig = apps.get_model("reports", "ReportConfig")

    # 1. Rename every existing tag's slug to the underscore form a
    # placeholder can actually match, tracking old -> new so
    # ReportConfig.content["dynamic"] and ReportSettings.dynamic_defaults
    # keys (both keyed by the OLD slug) can be renamed to match.
    old_to_new: dict[str, str] = {}
    existing_slugs = set(ReportTextBlockDefinition.objects.values_list("slug", flat=True))
    for i, block in enumerate(ReportTextBlockDefinition.objects.all()):
        new_slug = block.slug.replace("-", "_")
        if new_slug == block.slug:
            continue
        if new_slug in existing_slugs and new_slug != block.slug:
            new_slug = f"{new_slug}_{i}"
        old_to_new[block.slug] = new_slug
        existing_slugs.discard(block.slug)
        existing_slugs.add(new_slug)
        block.slug = new_slug
        block.save(update_fields=["slug"])

    def renamed(slug: str) -> str:
        return old_to_new.get(slug, slug)

    # "Summary of remediations" was previously gated by a per-NODE
    # remediation_report_only flag on its old text_block node — that
    # gating is now a property of the tag itself (see
    # ReportTextBlockDefinition.include_in_remediation_report_only's own
    # docstring), so carry the same behavior over here.
    ReportTextBlockDefinition.objects.filter(slug=renamed("summary-of-remediations")).update(
        include_in_remediation_report_only=True,
    )

    # 2. Every ReportConfig's own "dynamic" overrides, same rename.
    for config in ReportConfig.objects.all():
        content = config.content if isinstance(config.content, dict) else None
        dynamic = content.get("dynamic") if content else None
        if not isinstance(dynamic, dict) or not any(k in old_to_new for k in dynamic):
            continue
        content["dynamic"] = {renamed(k): v for k, v in dynamic.items()}
        config.content = content
        config.save(update_fields=["content"])

    # 3. Rebuild the seeded "Default" profile's document as free-form
    # Tiptap JSON reproducing the old fixed layout with the new slugs.
    # One deliberate adaptation: "Vulnerability rating" (previously a
    # bare node directly under the "Testing Methodology" group, a
    # position a pure heading-depth outline can't reproduce once its
    # siblings are real H2 subsections) becomes its own H2 subsection
    # instead — same content, one level of structure cleaner.
    template = {
        "type": "doc",
        "content": [
            _heading(1, "Executive Summary"),
            _tag("engagement_timeline"),
            _tag(renamed("summary-of-testing")),
            _tag(renamed("summary-of-findings")),
            _tag("breakdown_of_findings"),
            _tag(renamed("summary-of-remediations")),
            _tag(renamed("conclusions")),

            _heading(1, "Detailed Findings"),
            _tag(renamed("information-gathering")),
            _tag("finding_details"),
            _tag("observations"),

            _heading(1, "Testing Methodology"),
            _heading(2, "Scoping and requirements development"),
            _tag(renamed("assessment-objectives")),
            _tag(renamed("scope-of-testing")),
            _tag(renamed("permitted-actions")),
            _tag(renamed("constraints")),
            _tag(renamed("assumptions")),
            _tag(renamed("requirements")),
            _heading(2, "Assessment team"),
            _tag("assessment_team"),
            _heading(2, "Assessment outcomes"),
            _tag(renamed("equipment-and-tooling")),
            _tag("testing_phases"),
            _heading(2, "Vulnerability rating"),
            _tag(renamed("vulnerability-rating")),
        ],
    }

    settings_obj = ReportSettings.objects.first()
    old_defaults = getattr(settings_obj, "dynamic_defaults", None) or {}
    block_defaults = {renamed(k): v for k, v in old_defaults.items()} if isinstance(old_defaults, dict) else {}

    # filter().update(), not update_or_create() — Report Profiles are no
    # longer pre-seeded (see 0013's own updated comment), so on a fresh
    # install there IS no "Default" profile at this point and this must
    # stay a no-op rather than conjure one back into existence. On an
    # environment where 0013 already seeded one (already applied, before
    # this decision), this rebuilds it exactly as before.
    ReportProfile.objects.filter(name="Default").update(
        template=template, block_defaults=block_defaults, is_default=True,
    )

    # Any OTHER profile (e.g. created while testing the earlier node-tree
    # UI) has no generically-correct way to become a heading-based
    # document — it's left as a blank template for an admin to rewrite,
    # same "degrade, don't crash" rule used elsewhere in this migration.
    ReportProfile.objects.exclude(name="Default").update(template={}, block_defaults={})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0013_seed_report_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportprofile", name="template",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="reportprofile", name="block_defaults",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="reporttextblockdefinition", name="include_in_remediation_report_only",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterModelOptions(
            name="reporttextblockdefinition", options={"ordering": ["label", "created_at"]},
        ),
        migrations.RunPython(migrate_data, noop_reverse),
        migrations.RemoveField(model_name="reportprofile", name="structure"),
        migrations.RemoveField(model_name="reporttextblockdefinition", name="order"),
        migrations.RemoveField(model_name="reportsettings", name="dynamic_defaults"),
    ]
