from apps.engagements.access import AccessDecision, check_engagement_access

from .models import FindingClientView


def visible_client_engagements(user):
    from apps.engagements.models import Engagement

    if user.client_id is None:
        return Engagement.objects.none()

    return Engagement.objects.filter(
        client=user.client, client__is_active=True, archived=False, client_release_approved=True,
    )


def check_portal_engagement_access(user, engagement) -> AccessDecision:
    if not (user.is_authenticated and user.is_active):
        return AccessDecision(False, "not_authenticated")

    if not user.is_client_role:
        return AccessDecision(False, "not_client_role")

    if user.client_id is None or not user.client.is_active:
        return AccessDecision(False, "no_active_client")

    if engagement.archived:
        return AccessDecision(False, "archived")

    if engagement.client_id != user.client_id:
        return AccessDecision(False, "client_no_match")

    if not engagement.client_release_approved:
        return AccessDecision(False, "not_released_to_client")

    return AccessDecision(True, "client_portal_match")


def check_engagement_or_portal_access(user, engagement) -> AccessDecision:
    staff_decision = check_engagement_access(user, engagement)
    if staff_decision.granted:
        return staff_decision
    return check_portal_engagement_access(user, engagement)


def visible_client_findings(engagement):
    from apps.findings.models import Finding

    return engagement.findings.filter(workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=False)


def record_client_finding_view(finding, client_user):
    FindingClientView.objects.update_or_create(finding=finding, client_user=client_user)


def _attach_engagement_and_key_for_portal(request, engagement_id):
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import get_object_or_404

    from apps.crypto.access import _unauthenticated_response
    from apps.crypto.services import get_data_key
    from apps.engagements.models import Engagement

    if not request.user.is_authenticated:
        return _unauthenticated_response(request)

    engagement = get_object_or_404(Engagement, pk=engagement_id)

    decision = check_engagement_or_portal_access(request.user, engagement)
    if not decision.granted:
        raise PermissionDenied(decision.reason)

    request.engagement = engagement
    request.project_key = get_data_key(engagement)
    return None


def portal_engagement_access_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, engagement_id=None, **kwargs):
        early_response = _attach_engagement_and_key_for_portal(request, engagement_id)
        if early_response is not None:
            return early_response
        return view_func(request, *args, engagement_id=engagement_id, **kwargs)

    return wrapper
