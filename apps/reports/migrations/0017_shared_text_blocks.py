"""
Allows a ReportTextBlockDefinition's `profile` to be blank — a blank
profile means the tag is SHARED, usable via {{ slug }} from any profile's
template rather than belonging to just one (see that model's own
docstring). Adds `content`, the shared tag's own single body of text,
used only when `profile` is blank; a profile-owned tag's text keeps living
in that profile's own `block_defaults[slug]`, unchanged.

No data migration needed: every existing row already has a real profile
(from 0016), so relaxing the field to nullable doesn't touch any of them.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0016_text_blocks_per_profile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reporttextblockdefinition",
            name="profile",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="text_blocks", to="reports.reportprofile",
            ),
        ),
        migrations.AddField(
            model_name="reporttextblockdefinition",
            name="content",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddConstraint(
            model_name="reporttextblockdefinition",
            constraint=models.UniqueConstraint(
                condition=models.Q(("profile__isnull", True)),
                fields=("slug",), name="unique_shared_text_block_slug",
            ),
        ),
    ]
