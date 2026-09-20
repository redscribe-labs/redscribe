import pathlib

from django.db import migrations

FONTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "seed_data" / "fonts"

# (family, weight, style, filename) — the exact "latin" subset variants
# ReportProfile's shipped defaults (body_font="Open Sans",
# monospace_font="JetBrains Mono") need, pre-fetched from Google Fonts at
# dev time and bundled in seed_data/fonts/ so a fresh install renders
# reports with the intended fonts with zero network access at migrate
# time or first report generation. Superadmins choosing a *different*
# font later still goes through the normal live fetch_and_cache_font()
# path (apps/reports/google_fonts.py) — that's an explicit admin action,
# not something a restricted-environment install needs at setup.
_VARIANTS = [
    ("Open Sans", "400", "normal", "open-sans-400-normal.woff2"),
    ("Open Sans", "700", "normal", "open-sans-700-normal.woff2"),
    ("JetBrains Mono", "400", "normal", "jetbrains-mono-400-normal.woff2"),
    ("JetBrains Mono", "700", "normal", "jetbrains-mono-700-normal.woff2"),
]


def seed_fonts(apps, schema_editor):
    CachedGoogleFont = apps.get_model("reports", "CachedGoogleFont")
    for family, weight, style, filename in _VARIANTS:
        if CachedGoogleFont.objects.filter(family=family, weight=weight, style=style).exists():
            continue
        font_data = (FONTS_DIR / filename).read_bytes()
        CachedGoogleFont.objects.create(
            family=family, weight=weight, style=style,
            font_format="woff2", content_type="font/woff2", font_data=font_data,
        )


def unseed_fonts(apps, schema_editor):
    CachedGoogleFont = apps.get_model("reports", "CachedGoogleFont")
    CachedGoogleFont.objects.filter(family__in=["Open Sans", "JetBrains Mono"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0025_reportprofile_finding_table_layout"),
    ]

    operations = [
        migrations.RunPython(seed_fonts, unseed_fonts),
    ]
