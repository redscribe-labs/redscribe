"""
Report Profiles v3 — folds the report-visual settings that used to live
on the single global ReportSettings row (cover title, classification
label, finding-id prefix, severity colors, fonts, bullet glyph, table/
theme color) into ReportProfile instead, so different profiles can look
different. Also drops front_matter/back_matter entirely (cut feature, not
migrated — a profile's own free-form template covers that need now).

Combined into one migration (schema + data) because the data step needs
to read the 8 fields off the *current* ReportSettings singleton before
they're dropped, and needs them to already exist on ReportProfile to copy
into — see operations order below.
"""
from django.db import migrations, models

import apps.reports.validators


def copy_settings_onto_default_profile(apps, schema_editor):
    ReportSettings = apps.get_model("reports", "ReportSettings")
    ReportProfile = apps.get_model("reports", "ReportProfile")

    settings_obj = ReportSettings.objects.first()
    if settings_obj is None:
        return

    ReportProfile.objects.filter(name="Default").update(
        cover_title=settings_obj.cover_title,
        classification_label=settings_obj.classification_label,
        finding_id_prefix=settings_obj.finding_id_prefix,
        severity_colors=settings_obj.severity_colors,
        body_font=settings_obj.body_font,
        monospace_font=settings_obj.monospace_font,
        bullet_character=settings_obj.bullet_character,
        table_header_color=settings_obj.table_header_color,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0014_report_profiles_v2_free_form_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportprofile", name="cover_title",
            field=models.CharField(blank=True, default="Penetration Test Report", max_length=255),
        ),
        migrations.AddField(
            model_name="reportprofile", name="classification_label",
            field=models.CharField(blank=True, default="Strictly Confidential", max_length=64),
        ),
        migrations.AddField(
            model_name="reportprofile", name="finding_id_prefix",
            field=models.CharField(blank=True, default="F", max_length=16),
        ),
        migrations.AddField(
            model_name="reportprofile", name="severity_colors",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="reportprofile", name="body_font",
            field=models.CharField(
                blank=True, default="Open Sans", max_length=100,
                validators=[apps.reports.validators.validate_font_name],
            ),
        ),
        migrations.AddField(
            model_name="reportprofile", name="monospace_font",
            field=models.CharField(
                blank=True, default="JetBrains Mono", max_length=100,
                validators=[apps.reports.validators.validate_font_name],
            ),
        ),
        migrations.AddField(
            model_name="reportprofile", name="bullet_character",
            field=models.CharField(
                blank=True, default="•", max_length=8,
                validators=[apps.reports.validators.validate_no_markup_chars],
            ),
        ),
        migrations.AddField(
            model_name="reportprofile", name="table_header_color",
            field=models.CharField(
                blank=True, default="rgba(248,250,252,1)", max_length=64,
                validators=[apps.reports.validators.validate_rgba],
            ),
        ),
        migrations.RunPython(copy_settings_onto_default_profile, noop_reverse),
        migrations.RemoveField(model_name="reportsettings", name="cover_title"),
        migrations.RemoveField(model_name="reportsettings", name="classification_label"),
        migrations.RemoveField(model_name="reportsettings", name="finding_id_prefix"),
        migrations.RemoveField(model_name="reportsettings", name="severity_colors"),
        migrations.RemoveField(model_name="reportsettings", name="body_font"),
        migrations.RemoveField(model_name="reportsettings", name="monospace_font"),
        migrations.RemoveField(model_name="reportsettings", name="bullet_character"),
        migrations.RemoveField(model_name="reportsettings", name="table_header_color"),
        migrations.RemoveField(model_name="reportsettings", name="front_matter"),
        migrations.RemoveField(model_name="reportsettings", name="back_matter"),
    ]
