"""
Used to add per-item testing guidance to the default-seeded "OWASP WSTG"
checklist template. Now a no-op: 0002_seed_wstg_default no longer creates
that template on a fresh instance (see its docstring), so there's nothing
here to update — the guidance text this migration used to write now lives
in docs/checklist-templates/owasp-wstg.json, importable via the Checklist
Templates JSON/CSV import for anyone who wants it.

Kept (rather than deleted) only to preserve the migration dependency
chain for instances that already applied it with the old RunPython
functions.
"""
from django.db import migrations


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("checklist", "0002_seed_wstg_default")]
    operations = [migrations.RunPython(noop, noop)]
