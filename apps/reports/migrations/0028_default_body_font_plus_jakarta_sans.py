import pathlib

import apps.reports.validators
from django.db import migrations, models

FONTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "seed_data" / "fonts"

# New default body_font (see AlterField below) needs its own CachedGoogleFont
# rows seeded, same as 0026 did for the original Open Sans/JetBrains Mono
# defaults. This is a NEW migration rather than editing 0026 in place,
# because 0026 may have already run against an existing install (this repo's
# own tagged v0.1.0-alpha.1 release included it) — Django won't re-run an
# already-applied migration, so seeding here is the only way every install
# (fresh or upgrading) ends up with the new default font cached. The
# existing Open Sans rows are deliberately left alone: any ReportProfile row
# already persisted with the literal string "Open Sans" still needs it.
_VARIANTS = [
    ("Plus Jakarta Sans", "400", "normal", "plus-jakarta-sans-400-normal.woff2"),
    ("Plus Jakarta Sans", "700", "normal", "plus-jakarta-sans-700-normal.woff2"),
]


def seed_font(apps, schema_editor):
    CachedGoogleFont = apps.get_model("reports", "CachedGoogleFont")
    for family, weight, style, filename in _VARIANTS:
        if CachedGoogleFont.objects.filter(family=family, weight=weight, style=style).exists():
            continue
        font_data = (FONTS_DIR / filename).read_bytes()
        CachedGoogleFont.objects.create(
            family=family, weight=weight, style=style,
            font_format="woff2", content_type="font/woff2", font_data=font_data,
        )


def unseed_font(apps, schema_editor):
    CachedGoogleFont = apps.get_model("reports", "CachedGoogleFont")
    CachedGoogleFont.objects.filter(family="Plus Jakarta Sans").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0027_reportprofile_docx_style_map_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reportprofile",
            name="body_font",
            field=models.CharField(
                blank=True, default="Plus Jakarta Sans", max_length=100,
                validators=[apps.reports.validators.validate_font_name],
            ),
        ),
        migrations.RunPython(seed_font, unseed_font),
    ]
