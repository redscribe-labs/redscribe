from django.db import migrations

OWASP_TOP10_2021 = [
    ("A01:2021", "Broken Access Control"),
    ("A02:2021", "Cryptographic Failures"),
    ("A03:2021", "Injection"),
    ("A04:2021", "Insecure Design"),
    ("A05:2021", "Security Misconfiguration"),
    ("A06:2021", "Vulnerable and Outdated Components"),
    ("A07:2021", "Identification and Authentication Failures"),
    ("A08:2021", "Software and Data Integrity Failures"),
    ("A09:2021", "Security Logging and Monitoring Failures"),
    ("A10:2021", "Server-Side Request Forgery"),
]

# Enterprise ATT&CK tactics (stable, high-level) rather than the much
# larger and faster-changing technique catalogue — more usable for
# tagging a web-app pentest finding than picking from hundreds of
# techniques, and extendable via the admin if finer-grained tagging is
# wanted later.
MITRE_ATTACK_TACTICS = [
    ("TA0043", "Reconnaissance"),
    ("TA0042", "Resource Development"),
    ("TA0001", "Initial Access"),
    ("TA0002", "Execution"),
    ("TA0003", "Persistence"),
    ("TA0004", "Privilege Escalation"),
    ("TA0005", "Defense Evasion"),
    ("TA0006", "Credential Access"),
    ("TA0007", "Discovery"),
    ("TA0008", "Lateral Movement"),
    ("TA0009", "Collection"),
    ("TA0011", "Command and Control"),
    ("TA0010", "Exfiltration"),
    ("TA0040", "Impact"),
]

# Curated set of CWEs that come up repeatedly in web application pentest
# findings. Not exhaustive (the full CWE catalogue is 900+ entries) —
# more can be added via the admin as needed.
MITRE_CWE_COMMON = [
    ("CWE-20", "Improper Input Validation"),
    ("CWE-22", "Path Traversal"),
    ("CWE-78", "OS Command Injection"),
    ("CWE-79", "Cross-site Scripting"),
    ("CWE-89", "SQL Injection"),
    ("CWE-90", "LDAP Injection"),
    ("CWE-94", "Code Injection"),
    ("CWE-200", "Exposure of Sensitive Information"),
    ("CWE-201", "Insertion of Sensitive Information Into Sent Data"),
    ("CWE-209", "Generation of Error Message Containing Sensitive Information"),
    ("CWE-259", "Use of Hard-coded Password"),
    ("CWE-269", "Improper Privilege Management"),
    ("CWE-284", "Improper Access Control"),
    ("CWE-285", "Improper Authorization"),
    ("CWE-287", "Improper Authentication"),
    ("CWE-295", "Improper Certificate Validation"),
    ("CWE-306", "Missing Authentication for Critical Function"),
    ("CWE-307", "Improper Restriction of Excessive Authentication Attempts"),
    ("CWE-311", "Missing Encryption of Sensitive Data"),
    ("CWE-321", "Use of Hard-coded Cryptographic Key"),
    ("CWE-326", "Inadequate Encryption Strength"),
    ("CWE-327", "Use of a Broken or Risky Cryptographic Algorithm"),
    ("CWE-330", "Use of Insufficiently Random Values"),
    ("CWE-352", "Cross-Site Request Forgery"),
    ("CWE-359", "Exposure of Private Personal Information"),
    ("CWE-400", "Uncontrolled Resource Consumption"),
    ("CWE-434", "Unrestricted Upload of File with Dangerous Type"),
    ("CWE-441", "Server-Side Request Forgery"),
    ("CWE-502", "Deserialization of Untrusted Data"),
    ("CWE-521", "Weak Password Requirements"),
    ("CWE-598", "Use of GET Request Method With Sensitive Query Strings"),
    ("CWE-601", "Open Redirect"),
    ("CWE-611", "Improper Restriction of XML External Entity Reference"),
    ("CWE-613", "Insufficient Session Expiration"),
    ("CWE-639", "Insecure Direct Object Reference (IDOR)"),
    ("CWE-732", "Incorrect Permission Assignment for Critical Resource"),
    ("CWE-798", "Use of Hard-coded Credentials"),
    ("CWE-862", "Missing Authorization"),
    ("CWE-863", "Incorrect Authorization"),
    ("CWE-918", "Server-Side Request Forgery (SSRF)"),
    ("CWE-1021", "Improper Restriction of Rendered UI Layers (Clickjacking)"),
]


def seed(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    rows = (
        [("OWASP_TOP10", code, label) for code, label in OWASP_TOP10_2021]
        + [("MITRE_ATTACK", code, label) for code, label in MITRE_ATTACK_TACTICS]
        + [("MITRE_CWE", code, label) for code, label in MITRE_CWE_COMMON]
    )
    ClassificationTag.objects.bulk_create(
        [ClassificationTag(taxonomy=t, code=c, label=l) for t, c, l in rows]
    )


def unseed(apps, schema_editor):
    ClassificationTag = apps.get_model("findings", "ClassificationTag")
    ClassificationTag.objects.filter(
        taxonomy__in=["OWASP_TOP10", "MITRE_ATTACK", "MITRE_CWE"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("findings", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
