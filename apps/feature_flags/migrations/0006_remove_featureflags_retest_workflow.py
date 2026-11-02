from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("feature_flags", "0005_alter_featureflags_mfa_required"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="featureflags",
            name="retest_workflow",
        ),
    ]
