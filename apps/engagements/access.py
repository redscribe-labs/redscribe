from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Engagement, EngagementMembership


@dataclass
class AccessDecision:
    granted: bool
    reason: str


def check_engagement_access(user, engagement: Engagement) -> AccessDecision:
    if not user.is_authenticated or not user.is_active:
        return AccessDecision(False, "not_authenticated")

    if user.is_superadmin_role:
        return AccessDecision(True, "superadmin_bypass")

    if user.is_client_role:
        return AccessDecision(False, "client_role_never")

    if engagement.archived:
        if user.has_permission("engagements.access_archived"):
            return AccessDecision(True, "access_archived_permission")
        return AccessDecision(False, "archived_no_permission")

    if user.has_permission("engagements.view_all"):
        return AccessDecision(True, "view_all_blanket")

    if EngagementMembership.objects.filter(user=user, engagement=engagement).exists():
        return AccessDecision(True, "member")

    return AccessDecision(False, "no_membership")


def visible_engagements(user):
    if user.is_superadmin_role:
        return Engagement.objects.all()
    if user.is_client_role:
        return Engagement.objects.none()
    if user.has_permission("engagements.view_all"):
        active = Q(archived=False)
    else:
        member_ids = EngagementMembership.objects.filter(user=user).values_list("engagement_id", flat=True)
        active = Q(archived=False, id__in=member_ids)
    # engagements.access_archived mirrors the Superadmin's blanket access to archived
    # engagements (not scoped to membership), consistent with check_engagement_access.
    if user.has_permission("engagements.access_archived"):
        return Engagement.objects.filter(active | Q(archived=True))
    return Engagement.objects.filter(active)


def users_with_access(engagement: Engagement):
    User = get_user_model()
    active_staff = User.objects.filter(is_active=True).exclude(role__slug="client")
    superadmins = active_staff.filter(role__is_superadmin=True)
    if engagement.archived:
        return superadmins.distinct().order_by("username")

    member_ids = EngagementMembership.objects.filter(engagement=engagement).values_list("user_id", flat=True)
    return (
        superadmins
        | active_staff.filter(role__permissions__codename="engagements.view_all")
        | active_staff.filter(id__in=member_ids)
    ).distinct().order_by("username")
