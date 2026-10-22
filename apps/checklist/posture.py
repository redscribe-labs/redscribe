"""Testing-posture summaries for a checklist run: coverage per category, where
findings came from, and what's still untested. Built from one run's items
(with their linked findings prefetched), so no per-item queries."""
from apps.findings.models import Finding

from .models import ChecklistItem
from .services import decrypt_item_text

Status = ChecklistItem.Status

# Highest first. Drives "worst severity" and the risk ranking.
SEVERITY_RANK = {
    Finding.Severity.CRITICAL: 4,
    Finding.Severity.HIGH: 3,
    Finding.Severity.MEDIUM: 2,
    Finding.Severity.LOW: 1,
    Finding.Severity.INFORMATIONAL: 0,
}

# (status, short key used by the template/CSS, label) in display order.
OUTCOMES = [
    (Status.TESTED_NO_FINDING, "pass", "No finding"),
    (Status.TESTED_FINDING_RAISED, "finding", "Finding raised"),
    (Status.BLOCKED, "blocked", "Blocked"),
    (Status.NOT_APPLICABLE, "na", "Not applicable"),
    (Status.NOT_TESTED, "open", "Not tested"),
]
_KEY = {status: key for status, key, _ in OUTCOMES}


def _worst(severities):
    return max(severities, key=lambda s: SEVERITY_RANK.get(s, -1), default=None)


def run_posture(run, project_key=None):
    """project_key, when given, is used to decrypt Blocked reasons."""
    items = list(run.items.select_related("tested_by").prefetch_related("findings"))
    counts = {status: 0 for status, _, _ in OUTCOMES}
    categories = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
        linked = list(item.findings.all())
        cat = categories.setdefault(item.category, {"name": item.category, "cells": [], "findings": {}})
        for finding in linked:
            cat["findings"][finding.pk] = finding
        cat["cells"].append({
            "item": item,
            "key": _KEY.get(item.status, "open"),
            "worst": _worst([f.severity for f in linked]),
            "finding_titles": [f.title for f in linked],
        })

    rows = []
    for cat in categories.values():
        cells = cat["cells"]
        per = {key: 0 for _, key, _ in OUTCOMES}
        for cell in cells:
            per[cell["key"]] += 1
        total = len(cells)
        done = total - per["open"]
        worst = _worst([f.severity for f in cat["findings"].values()])
        rows.append({
            "name": cat["name"],
            "cells": cells,
            "counts": per,
            "total": total,
            "done": done,
            "pct": round(done / total * 100) if total else 0,
            "findings": sorted(cat["findings"].values(), key=lambda f: -SEVERITY_RANK.get(f.severity, -1)),
            "worst": worst,
        })

    total = len(items)
    done = total - counts[Status.NOT_TESTED]
    breakdown = [
        {"key": key, "label": label, "count": counts[status], "pct": round(counts[status] / total * 100) if total else 0}
        for status, key, label in OUTCOMES
    ]
    risk = sorted((r for r in rows if r["findings"]), key=lambda r: -SEVERITY_RANK.get(r["worst"], -1))
    untested = sorted((r for r in rows if r["counts"]["open"]), key=lambda r: -r["counts"]["open"])
    all_findings = {f.pk: f for r in rows for f in r["findings"]}
    blocked = [
        {"item": item, "reason": decrypt_item_text(item, "blocked_reason", project_key) if project_key else ""}
        for item in items if item.status == Status.BLOCKED
    ]
    return {
        "run": run,
        "rows": rows,
        "total": total,
        "done": done,
        "pct": round(done / total * 100) if total else 0,
        "breakdown": breakdown,
        "finding_checks": counts[Status.TESTED_FINDING_RAISED],
        "open": counts[Status.NOT_TESTED],
        "blocked": blocked,
        "worst": _worst([f.severity for f in all_findings.values()]),
        "risk": risk,
        "untested": untested[:6],
    }
