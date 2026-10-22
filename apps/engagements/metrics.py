"""Per-engagement counts for list views, computed in a single annotated query.

Every Count uses distinct=True: the findings and checklist joins multiply
rows, and distinct keeps each total correct regardless of the other join.
"""
from django.db.models import Count, Q

from apps.checklist.models import ChecklistItem
from apps.findings.models import Finding

SEVERITY_FIELDS = [
    ("open_critical", Finding.Severity.CRITICAL, "C", "Critical"),
    ("open_high", Finding.Severity.HIGH, "H", "High"),
    ("open_medium", Finding.Severity.MEDIUM, "M", "Medium"),
    ("open_low", Finding.Severity.LOW, "L", "Low"),
    ("open_info", Finding.Severity.INFORMATIONAL, "I", "Informational"),
]


def with_metrics(engagements):
    open_finding = Q(findings__status=Finding.Status.OPEN)
    annotations = {
        "findings_total": Count("findings", distinct=True),
        "checklist_total": Count("checklist_runs__items", distinct=True),
        "checklist_tested": Count(
            "checklist_runs__items",
            filter=~Q(checklist_runs__items__status=ChecklistItem.Status.NOT_TESTED),
            distinct=True,
        ),
    }
    for field, severity, _short, _label in SEVERITY_FIELDS:
        annotations[field] = Count("findings", filter=open_finding & Q(findings__severity=severity), distinct=True)
    return engagements.annotate(**annotations)


def severity_counts(engagement):
    """[(value, short, label, count)] for an engagement annotated by with_metrics()."""
    return [(severity, short, label, getattr(engagement, field)) for field, severity, short, label in SEVERITY_FIELDS]


def checklist_pct(engagement):
    total = engagement.checklist_total
    return round(engagement.checklist_tested / total * 100) if total else None


def stage_index(engagement):
    values = [value for value, _ in type(engagement).Status.choices]
    return values.index(engagement.status) if engagement.status in values else 0
