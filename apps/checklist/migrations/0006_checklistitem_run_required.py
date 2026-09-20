import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checklist", "0005_backfill_checklist_run"),
    ]

    operations = [
        migrations.AlterField(
            model_name="checklistitem",
            name="run",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items", to="checklist.checklistrun",
            ),
        ),
        migrations.RemoveField(
            model_name="checklistitem",
            name="engagement",
        ),
    ]
