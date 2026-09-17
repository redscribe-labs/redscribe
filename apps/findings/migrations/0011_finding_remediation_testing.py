from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('findings', '0010_owasp_top10_2025'),
    ]

    operations = [
        migrations.AddField(
            model_name='finding',
            name='remediation_testing_ciphertext',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='commentthread',
            name='field_name',
            field=models.CharField(choices=[('vulnerability_description', 'vulnerability_description'), ('business_impact', 'business_impact'), ('testing_summary', 'testing_summary'), ('technical_details', 'technical_details'), ('remediation_testing', 'remediation_testing'), ('recommendations', 'recommendations'), ('references', 'references'), ('note', 'note')], max_length=32),
        ),
    ]
