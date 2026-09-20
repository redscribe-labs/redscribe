from dataclasses import dataclass

from django.contrib.auth import get_user_model

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

    if engagement.archived:
        return AccessDecision(False, "archived_superadmin_only")

    if user.is_client_role:
        return AccessDecision(False, "client_role_never")

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
        return Engagement.objects.filter(archived=False)
    member_ids = EngagementMembership.objects.filter(user=user).values_list("engagement_id", flat=True)
    return Engagement.objects.filter(id__in=member_ids, archived=False)


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
