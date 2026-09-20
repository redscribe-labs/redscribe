from collections import defaultdict

from django.db.models.functions import TruncMonth

from apps.findings.models import ClassificationTag, Finding, RetestRecord

MONTHS_WINDOW = 12


def severity_over_time(engagements, months: int = MONTHS_WINDOW):
    findings = (
        Finding.objects.filter(engagement__in=engagements)
        .annotate(month=TruncMonth("created_at"))
        .values("month", "severity")
    )
    counts = defaultdict(lambda: defaultdict(int))
    for row in findings:
        if row["month"] is not None:
            counts[row["month"].date().replace(day=1)][row["severity"]] += 1

    if not counts:
        return []

    ordered_months = sorted(counts.keys())[-months:]
    severities = [c[0] for c in Finding.Severity.choices]
    rows = []
    for month in ordered_months:
        month_counts = counts[month]
        rows.append({
            "month": month,
            "label": month.strftime("%b %Y"),
            "counts": {sev: month_counts.get(sev, 0) for sev in severities},
            "total": sum(month_counts.values()),
        })
    return rows


def mean_time_to_remediate(engagements):
    fixed_records = (
        RetestRecord.objects.filter(
            finding__engagement__in=engagements, status=Finding.RetestStatus.FIXED
        )
        .select_related("finding")
        .order_by("finding_id", "created_at")
    )

    first_fix_days = {}
    severity_by_finding = {}
    for record in fixed_records:
        if record.finding_id in first_fix_days:
            continue
        days = (record.created_at.date() - record.finding.created_at.date()).days
        first_fix_days[record.finding_id] = days
        severity_by_finding[record.finding_id] = record.finding.severity

    if not first_fix_days:
        return {"overall_days": None, "sample_size": 0, "by_severity": []}

    overall_days = sum(first_fix_days.values()) / len(first_fix_days)

    by_severity_days = defaultdict(list)
    for finding_id, days in first_fix_days.items():
        by_severity_days[severity_by_finding[finding_id]].append(days)

    by_severity = [
        {
            "severity": sev, "label": label,
            "mean_days": round(sum(by_severity_days[sev]) / len(by_severity_days[sev]), 1),
            "sample_size": len(by_severity_days[sev]),
        }
        for sev, label in Finding.Severity.choices
        if by_severity_days[sev]
    ]

    return {
        "overall_days": round(overall_days, 1),
        "sample_size": len(first_fix_days),
        "by_severity": by_severity,
    }


def repeat_findings_by_client(engagements, min_engagements: int = 2):
    rows = (
        Finding.objects.filter(engagement__in=engagements, classifications__isnull=False)
        .values("engagement__client_name", "engagement_id", "classifications")
        .distinct()
    )

    engagement_sets = defaultdict(set)
    finding_counts = defaultdict(int)
    for row in rows:
        key = (row["engagement__client_name"], row["classifications"])
        engagement_sets[key].add(row["engagement_id"])

    finding_rows = (
        Finding.objects.filter(engagement__in=engagements, classifications__isnull=False)
        .values("engagement__client_name", "classifications")
    )
    for row in finding_rows:
        finding_counts[(row["engagement__client_name"], row["classifications"])] += 1

    tag_ids = {key[1] for key in engagement_sets}
    tags_by_id = {tag.id: tag for tag in ClassificationTag.objects.filter(id__in=tag_ids)}

    results = []
    for (client_name, tag_id), engagement_ids in engagement_sets.items():
        if len(engagement_ids) < min_engagements:
            continue
        tag = tags_by_id.get(tag_id)
        if tag is None:
            continue
        results.append({
            "client_name": client_name,
            "tag": tag,
            "engagement_count": len(engagement_ids),
            "finding_count": finding_counts[(client_name, tag_id)],
        })

    results.sort(key=lambda r: (-r["engagement_count"], -r["finding_count"], r["client_name"]))
    return results
