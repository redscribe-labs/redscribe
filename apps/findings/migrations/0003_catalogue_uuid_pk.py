import uuid

from django.db import migrations, models

# Postgres can't implicitly cast bigint -> uuid, so the default AlterField
# Django would generate here fails outright. Handwritten instead: add a real
# uuid column, backfill it (and the M2M through table's FK column) with
# generated UUIDs, then swap the old bigint id out for it. Only a handful of
# catalogue rows ever exist (no engagement/finding data hangs off this
# table), so a straight backfill-in-place is safe — no need for the
# "reset the table" shortcut used for Engagement/Finding's UUID migration.
SQL = """
ALTER TABLE findings_vulnerabilitytemplate ADD COLUMN new_id uuid;
UPDATE findings_vulnerabilitytemplate SET new_id = gen_random_uuid();
ALTER TABLE findings_vulnerabilitytemplate ALTER COLUMN new_id SET NOT NULL;

ALTER TABLE findings_vulnerabilitytemplate_classifications ADD COLUMN new_vulnerabilitytemplate_id uuid;
UPDATE findings_vulnerabilitytemplate_classifications AS m
    SET new_vulnerabilitytemplate_id = v.new_id
    FROM findings_vulnerabilitytemplate AS v
    WHERE m.vulnerabilitytemplate_id = v.id;
ALTER TABLE findings_vulnerabilitytemplate_classifications ALTER COLUMN new_vulnerabilitytemplate_id SET NOT NULL;

ALTER TABLE findings_vulnerabilitytemplate_classifications
    DROP CONSTRAINT findings_vulnerabili_vulnerabilitytemplat_91bf7340_fk_findings_;
ALTER TABLE findings_vulnerabilitytemplate_classifications DROP COLUMN vulnerabilitytemplate_id;
ALTER TABLE findings_vulnerabilitytemplate_classifications
    RENAME COLUMN new_vulnerabilitytemplate_id TO vulnerabilitytemplate_id;

ALTER TABLE findings_vulnerabilitytemplate DROP CONSTRAINT findings_vulnerabilitytemplate_pkey;
ALTER TABLE findings_vulnerabilitytemplate ALTER COLUMN id DROP IDENTITY IF EXISTS;
ALTER TABLE findings_vulnerabilitytemplate DROP COLUMN id;
ALTER TABLE findings_vulnerabilitytemplate RENAME COLUMN new_id TO id;
ALTER TABLE findings_vulnerabilitytemplate ADD PRIMARY KEY (id);
DROP SEQUENCE IF EXISTS findings_vulnerabilitytemplate_id_seq CASCADE;

ALTER TABLE findings_vulnerabilitytemplate_classifications
    ADD CONSTRAINT findings_vulnerabilitytem_vulnerabilitytemplate_id_91bf7340_fk
    FOREIGN KEY (vulnerabilitytemplate_id) REFERENCES findings_vulnerabilitytemplate(id)
    DEFERRABLE INITIALLY DEFERRED;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('findings', '0002_seed_classification_tags'),
    ]

    operations = [
        migrations.RunSQL(
            sql=SQL,
            reverse_sql=migrations.RunSQL.noop,
            state_operations=[
                migrations.AlterField(
                    model_name='vulnerabilitytemplate',
                    name='id',
                    field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
            ],
        ),
    ]
