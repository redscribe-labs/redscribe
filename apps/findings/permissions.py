from apps.engagements.permissions import is_engagement_manager


def can_bulk_manage_catalogue(user) -> bool:
    return user.is_authenticated and user.has_permission("catalogue.bulk_manage")


def can_create_catalogue_entry(user) -> bool:
    return user.is_authenticated


def can_approve_catalogue_entry(user) -> bool:
    return user.is_authenticated and user.has_permission("catalogue.approve")


def can_submit_catalogue_qa(user, template) -> bool:
    return can_edit_catalogue_entry(user, template)


def can_edit_catalogue_entry(user, template) -> bool:
    if not user.is_authenticated:
        return False
    if user.has_permission("catalogue.manage"):
        return True
    return template.created_by_id == user.pk


def can_delete_catalogue_entry(user, template) -> bool:
    if not user.is_authenticated:
        return False
    if template.created_by_id == user.pk:
        return True
    return user.has_permission("catalogue.delete_any")


def can_delete_comment_thread(user, thread) -> bool:
    if not user.is_authenticated:
        return False
    if thread.created_by_id == user.pk:
        return True
    return is_engagement_manager(user, thread.finding.engagement)


def can_edit_finding_content(user, finding) -> bool:
    if finding.archived:
        return False
    return user.is_authenticated


def can_archive_finding(user, finding) -> bool:
    if not user.is_authenticated:
        return False
    if finding.created_by_id == user.pk:
        return True
    return is_engagement_manager(user, finding.engagement)


def can_delete_finding(user, finding) -> bool:
    if not user.is_authenticated:
        return False
    if finding.created_by_id == user.pk:
        return True
    return is_engagement_manager(user, finding.engagement)
