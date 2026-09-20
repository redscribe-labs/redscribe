from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render

from apps.engagements.access import visible_engagements
from apps.feature_flags.models import FeatureFlags
from apps.findings.models import Finding

RESULT_LIMIT = 25


@login_required
def search_results(request):
    if not FeatureFlags.get_solo().global_search:
        raise PermissionDenied("Global search is currently disabled.")

    query = request.GET.get("q", "").strip()
    engagements = []
    findings = []
    engagement_total = finding_total = 0

    if query:
        visible = visible_engagements(request.user)

        engagement_qs = visible.filter(
            Q(client_name__icontains=query) | Q(reference_number__icontains=query)
        )
        engagement_total = engagement_qs.count()
        engagements = engagement_qs[:RESULT_LIMIT]

        finding_qs = Finding.objects.filter(engagement__in=visible).filter(
            Q(title__icontains=query) | Q(cve_id__icontains=query)
        ).select_related("engagement")
        finding_total = finding_qs.count()
        findings = finding_qs[:RESULT_LIMIT]

    return render(
        request, "search/results.html",
        {
            "query": query,
            "engagements": engagements,
            "findings": findings,
            "engagement_total": engagement_total,
            "finding_total": finding_total,
            "result_limit": RESULT_LIMIT,
            "breadcrumbs": [{"label": "Search"}],
        },
    )
