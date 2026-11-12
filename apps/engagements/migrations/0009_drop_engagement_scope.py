import re
import uuid

from django.db import migrations


def _infer_asset_type(value: str) -> str:
    v = value.strip()
    if "://" in v or v.lower().startswith(("http:", "https:", "ftp:")):
        return "URL"
    if re.search(r"/\d{1,3}$", v):  # CIDR suffix
        return "SUBNET"
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", v):
        return "IP"
    return "FQDN"


def backfill_scope(apps, schema_editor):
    """Convert each engagement's free-text scope into a single 'In Scope'
    AssetCategory with one typed ScopeAsset per non-blank line."""
    Engagement = apps.get_model("engagements", "Engagement")
    AssetCategory = apps.get_model("engagements", "AssetCategory")
    ScopeAsset = apps.get_model("engagements", "ScopeAsset")

    for engagement in Engagement.objects.all():
        text = (engagement.scope or "").strip()
        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        category = AssetCategory.objects.create(
            id=uuid.uuid4(), engagement=engagement, name="In Scope", order=0,
        )
        for order, line in enumerate(lines):
            ScopeAsset.objects.create(
                id=uuid.uuid4(), engagement=engagement, category=category,
                asset_type=_infer_asset_type(line), value=line[:512], description="", order=order,
            )


def noop_reverse(apps, schema_editor):
    # One-way: the free-text column is gone on reverse anyway.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('engagements', '0008_assetcategory_scopeasset_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_scope, noop_reverse),
        migrations.RemoveField(
            model_name='engagement',
            name='scope',
        ),
    ]
