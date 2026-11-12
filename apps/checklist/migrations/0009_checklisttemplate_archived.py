from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checklist", "0008_checklistitemevent_assignee_users"),
    ]

    operations = [
        migrations.AddField(
            model_name="checklisttemplate",
            name="archived",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterModelOptions(
            name="checklisttemplate",
            options={"ordering": ["archived", "name"]},
        ),
    ]
