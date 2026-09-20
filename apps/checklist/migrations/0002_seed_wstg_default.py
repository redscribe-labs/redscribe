"""
No longer seeds a default "OWASP WSTG" checklist template — a fresh
instance now starts with zero checklist templates, so whether to have
WSTG (or anything else) as the default is entirely the operator's choice,
made through the existing JSON/CSV import (Checklist Templates in the
nav) rather than baked into every install. The content that used to be
seeded here (a representative subset of the OWASP WSTG structure/
numbering, plus the per-item testing guidance 0003_wstg_reference_
guidance.py used to add) now lives as an importable file at
docs/checklist-templates/owasp-wstg.json — upload it if you want it.

This migration and 0003 are kept (rather than deleted) only to preserve
the migration dependency chain for instances that already applied them
with the old seed/unseed RunPython functions; both are now no-ops on a
fresh `migrate`.
"""
from django.db import migrations


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("checklist", "0001_initial")]
    operations = [migrations.RunPython(noop, noop)]
