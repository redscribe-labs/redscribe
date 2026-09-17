from django.db import migrations

# https://owasp.org/Top10/2025/ — official ordered list.
OWASP_TOP10_2025 = [
    ("A01:2025", "Broken Access Control"),
    ("A02:2025", "Security Misconfiguration"),
    ("A03:2025", "Software Supply Chain Failures"),
    ("A04:2025", "Cryptographic Failures"),
    ("A05:2025", "Injection"),
    ("A06:2025", "Insecure Design"),
    ("A07:2025", "Authentication Failures"),
    ("A08:2025", "Software or Data Integrity Failures"),
    ("A09:2025", "Security Logging and Alerting Failures"),
    ("A10:2025", "Mishandling of Exceptional Conditions"),
]


def seed_2025(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")

    # Relabel the existing (2021) rows to be explicitly dated now that a
    # second revision exists — values are untouched, so any finding already
    # classified under one of these keeps its original, historically
    # accurate code (e.g. "A03:2021 – Injection"); only the taxonomy name
    # they're grouped under becomes unambiguous.
    ClassificationTag.objects.filter(taxonomy="OWASP Top 10").update(taxonomy="OWASP Top 10 2021")

    for code, label in OWASP_TOP10_2025:
        ClassificationTag.objects.get_or_create(
            taxonomy="OWASP Top 10 2025", value=f"{code} – {label}",
        )


def unseed_2025(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2025").delete()
    ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").update(taxonomy="OWASP Top 10")


class Migration(migrations.Migration):
    dependencies = [("findings", "0009_classificationtag_free_taxonomy")]
    operations = [migrations.RunPython(seed_2025, unseed_2025)]
