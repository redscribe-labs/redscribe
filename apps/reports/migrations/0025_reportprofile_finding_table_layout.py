from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0024_reportprofile_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportprofile",
            name="finding_table_layout",
            field=models.CharField(
                choices=[("table", "Table"), ("list", "List")],
                default="table",
                max_length=16,
                help_text="How each finding's severity/CVSS/classification/status details are displayed: "
                          "a two-column table, or a plain list.",
            ),
        ),
    ]
