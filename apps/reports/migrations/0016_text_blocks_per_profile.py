"""
Splits ReportTextBlockDefinition from a single global catalog (shared by
every ReportProfile) into rows owned by exactly one profile — see that
model's own docstring for why: two profiles should each manage their own
independent set of tags, not silently share (and step on) one global set
just because they happen to use the same name.

Existing rows have no single natural owner — a tag could be referenced by
one profile's template, several, or none — so the data migration below
assigns each one:
  - referenced by exactly one profile -> reassigned to that profile
    in place (same row, same id).
  - referenced by more than one -> the original row goes to the first
    (by pk) referencing profile, and an independent COPY (new row, same
    label/flags/text) is made for every other referencing profile, so
    each keeps working exactly as it did before this migration — nobody
    has to notice this happened.
  - referenced by none (unused anywhere) -> assigned to the default
    profile (or, if there isn't one, the first profile by pk) rather than
    silently deleted — it's still real admin-entered data.
"""
import re

from django.db import migrations, models
import django.db.models.deletion

# Same convention as apps.reports.placeholders._TOKEN_RE — flexible
# whitespace inside {{ }}. Run against the template's raw JSON text rather
# than walking its node structure: this only needs to decide who *used* to
# reference a slug well enough to preserve existing behavior, not
# perfectly replicate the render-time parser.
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def assign_text_blocks_to_profiles(apps, schema_editor):
    ReportProfile = apps.get_model("reports", "ReportProfile")
    ReportTextBlockDefinition = apps.get_model("reports", "ReportTextBlockDefinition")

    profiles = list(ReportProfile.objects.order_by("pk"))
    if not profiles:
        # No profile exists to own anything — nothing meaningful to do;
        # AlterField below would fail on any leftover NULL profile_id, but
        # there can be no ReportTextBlockDefinition rows in a database with
        # zero ReportProfile rows to begin with (every install seeds at
        # least the one it's about to use, or has none of either).
        return
    default_profile = next((p for p in profiles if p.is_default), profiles[0])
    tokens_by_profile = {p.pk: set(_TOKEN_RE.findall(str(p.template))) for p in profiles}

    for block in list(ReportTextBlockDefinition.objects.all()):
        referencing = [p for p in profiles if block.slug in tokens_by_profile[p.pk]]

        if not referencing:
            block.profile_id = default_profile.pk
            block.save(update_fields=["profile"])
            continue

        block.profile_id = referencing[0].pk
        block.save(update_fields=["profile"])
        for extra_profile in referencing[1:]:
            ReportTextBlockDefinition.objects.create(
                profile_id=extra_profile.pk,
                slug=block.slug,
                label=block.label,
                is_active=block.is_active,
                include_in_remediation_report_only=block.include_in_remediation_report_only,
                updated_by_id=block.updated_by_id,
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0015_fold_report_settings_into_profiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="reporttextblockdefinition",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="text_blocks", to="reports.reportprofile",
            ),
        ),
        # Must drop the OLD global unique=True on slug BEFORE the data
        # migration below — a tag referenced by more than one profile
        # becomes two rows sharing the same slug value (one per owning
        # profile), which the old global constraint would reject outright.
        migrations.AlterField(
            model_name="reporttextblockdefinition",
            name="slug",
            field=models.SlugField(max_length=64),
        ),
        migrations.RunPython(assign_text_blocks_to_profiles, noop_reverse),
        migrations.AlterField(
            model_name="reporttextblockdefinition",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="text_blocks", to="reports.reportprofile",
            ),
        ),
        migrations.AddConstraint(
            model_name="reporttextblockdefinition",
            constraint=models.UniqueConstraint(
                fields=("profile", "slug"), name="unique_profile_text_block_slug",
            ),
        ),
    ]
