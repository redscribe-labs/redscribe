from django.db.models import Count, Q

from .models import Finding, VulnerabilityTemplate


def similar_catalogue_entries(finding: Finding, limit: int = 5):
    tag_ids = list(finding.classifications.values_list("id", flat=True))
    if not tag_ids:
        return []
    return list(
        VulnerabilityTemplate.objects.filter(classifications__id__in=tag_ids)
        .annotate(shared_tags=Count("classifications", filter=Q(classifications__id__in=tag_ids), distinct=True))
        .order_by("-shared_tags", "title")[:limit]
    )


def repeat_findings_for_client(finding: Finding, limit: int = 5):
    tag_ids = list(finding.classifications.values_list("id", flat=True))
    if not tag_ids:
        return []
    return list(
        Finding.objects.filter(engagement__client_name=finding.engagement.client_name, classifications__id__in=tag_ids)
        .exclude(pk=finding.pk)
        .annotate(shared_tags=Count("classifications", filter=Q(classifications__id__in=tag_ids), distinct=True))
        .select_related("engagement")
        .order_by("-shared_tags", "-created_at")[:limit]
    )
