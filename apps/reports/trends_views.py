from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from apps.engagements.access import visible_engagements
from apps.engagements.models import Engagement
from apps.feature_flags.models import FeatureFlags

from . import trends


def _severity_style(severity_value):
    from .colors import severity_rgba

    return f"background-color:{severity_rgba(severity_value, 'open')}"


def _severity_trend_chart(severity_months):
    from apps.findings.models import Finding

    max_total = max((m["total"] for m in severity_months), default=0)

    present = {sev for m in severity_months for sev, count in m["counts"].items() if count}
    legend = [
        {"label": label, "style": _severity_style(sev)}
        for sev, label in Finding.Severity.choices
        if sev in present
    ]

    columns = []
    for m in severity_months:
        segments = []
        for sev, label in Finding.Severity.choices:
            count = m["counts"].get(sev, 0)
            if count == 0:
                continue
            height_pct = round(count / max_total * 100, 2) if max_total else 0
            segments.append({
                "label": label, "count": count, "height_pct": height_pct,
                "style": _severity_style(sev),
            })
        columns.append({"label": m["label"], "total": m["total"], "segments": segments})

    return {"legend": legend, "columns": columns}


def _with_mttr_bars(mttr):
    max_days = max((row["mean_days"] for row in mttr["by_severity"]), default=0)
    for row in mttr["by_severity"]:
        row["style"] = _severity_style(row["severity"])
        row["bar_pct"] = round(row["mean_days"] / max_days * 100, 1) if max_days else 0
    return mttr


@login_required
def trends_view(request):
    if not FeatureFlags.get_solo().recurrence_and_trends:
        raise PermissionDenied("Trend reporting is currently disabled.")

    user = request.user
    if not user.has_permission("reports.trends"):
        raise PermissionDenied("You don't have permission to view trend reporting.")

    if user.is_superadmin_role:
        engagements = Engagement.objects.all()
        scope_label = "All engagements"
    else:
        engagements = visible_engagements(user)
        scope_label = "Engagements you have access to"

    severity_months = trends.severity_over_time(engagements)

    return render(
        request, "reports/trends.html",
        {
            "scope_label": scope_label,
            "severity_chart": _severity_trend_chart(severity_months),
            "mttr": _with_mttr_bars(trends.mean_time_to_remediate(engagements)),
            "repeat_findings": trends.repeat_findings_by_client(engagements),
            "breadcrumbs": [{"label": "Trends"}],
        },
    )
