from .access import check_engagement_access
from .models import Engagement


def can_create_engagement(user) -> bool:
    return user.is_authenticated and user.has_permission("engagements.create")


def is_engagement_manager(user, engagement: Engagement) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superadmin_role:
        return True
    if engagement.archived:
        return False
    if not user.has_permission("engagements.manage"):
        return False
    return check_engagement_access(user, engagement).granted


def can_archive_engagement(user, engagement: Engagement) -> bool:
    return is_engagement_manager(user, engagement)


def can_release_engagement_to_client(user, engagement: Engagement) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superadmin_role:
        return True
    if engagement.archived:
        return False
    if not (user.has_permission("engagements.release_to_client") or user.has_permission("findings.qa")):
        return False
    return check_engagement_access(user, engagement).granted


def can_permanently_delete_engagement(user) -> bool:
    return user.is_authenticated and user.is_superadmin_role
