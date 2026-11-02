from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_background_qualifications_to_tiptap"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="erased_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
