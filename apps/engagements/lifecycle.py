from django.core.exceptions import PermissionDenied

from .models import Engagement, EngagementStatusHistory
from .permissions import is_engagement_manager

Status = Engagement.Status

NEXT_STATES = {
    Status.IN_PROGRESS: [Status.IN_REVIEW],
    Status.IN_REVIEW: [Status.QA, Status.IN_PROGRESS],
    Status.QA: [Status.APPROVED, Status.IN_REVIEW],
    Status.APPROVED: [Status.DELIVERED],
    Status.DELIVERED: [Status.AWAITING_REMEDIATION_TEST, Status.CLOSED],
    Status.AWAITING_REMEDIATION_TEST: [Status.REMEDIATION_TEST, Status.CLOSED],
    Status.REMEDIATION_TEST: [Status.AWAITING_REMEDIATION_TEST, Status.CLOSED],
    Status.CLOSED: [Status.IN_PROGRESS],
}

TRANSITION_LABELS = {
    (Status.IN_PROGRESS, Status.IN_REVIEW): ("Move to Review", "primary"),
    (Status.IN_REVIEW, Status.QA): ("Move to QA", "primary"),
    (Status.IN_REVIEW, Status.IN_PROGRESS): ("Send back to In Progress", "secondary"),
    (Status.QA, Status.APPROVED): ("Approve", "primary"),
    (Status.QA, Status.IN_REVIEW): ("Send back to Review", "secondary"),
    (Status.APPROVED, Status.DELIVERED): ("Mark Delivered", "primary"),
    (Status.DELIVERED, Status.AWAITING_REMEDIATION_TEST): ("Start Remediation Test", "primary"),
    (Status.DELIVERED, Status.CLOSED): ("Close Engagement", "secondary"),
    (Status.AWAITING_REMEDIATION_TEST, Status.REMEDIATION_TEST): ("Begin Retesting", "primary"),
    (Status.AWAITING_REMEDIATION_TEST, Status.CLOSED): ("Close Engagement", "secondary"),
    (Status.REMEDIATION_TEST, Status.AWAITING_REMEDIATION_TEST): ("Send back to Awaiting Remediation Test", "secondary"),
    (Status.REMEDIATION_TEST, Status.CLOSED): ("Close Engagement", "primary"),
    (Status.CLOSED, Status.IN_PROGRESS): ("Reopen Engagement", "secondary"),
}


def available_transitions(engagement: Engagement) -> list[str]:
    if engagement.archived:
        return []
    return NEXT_STATES.get(engagement.status, [])


def transition_options(engagement: Engagement) -> list[dict]:
    return [_option_dict(engagement, to_status) for to_status in available_transitions(engagement)]


def can_transition_engagement(user, engagement: Engagement) -> bool:
    return is_engagement_manager(user, engagement)


def can_start_review(user, engagement: Engagement) -> bool:
    from apps.engagements.access import check_engagement_access

    return check_engagement_access(user, engagement).granted


def can_move_from_review(user, engagement: Engagement) -> bool:
    return bool(engagement.default_reviewer_id and user.pk == engagement.default_reviewer_id)


def can_send_back_from_qa(user, engagement: Engagement) -> bool:
    return bool(engagement.default_qa_id and user.pk == engagement.default_qa_id)


def can_approve(user, engagement: Engagement) -> bool:
    return bool(engagement.default_approver_id and user.pk == engagement.default_approver_id)


def can_act_on_transition(user, engagement: Engagement, to_status: str) -> bool:
    if can_transition_engagement(user, engagement):
        return True
    if engagement.status == Status.IN_PROGRESS and to_status == Status.IN_REVIEW:
        return can_start_review(user, engagement)
    if engagement.status == Status.IN_REVIEW and to_status in (Status.QA, Status.IN_PROGRESS):
        return can_move_from_review(user, engagement)
    if engagement.status == Status.QA and to_status == Status.APPROVED:
        return can_approve(user, engagement)
    if engagement.status == Status.QA and to_status == Status.IN_REVIEW:
        return can_send_back_from_qa(user, engagement)
    return False


def _option_dict(engagement: Engagement, to_status: str) -> dict:
    label, style = TRANSITION_LABELS[(engagement.status, to_status)]
    return {
        "to_status": str(to_status),
        "to_status_label": dict(Status.choices)[to_status],
        "label": label,
        "style": style,
        "warnings": transition_warnings(engagement, to_status),
    }


def visible_transition_options(user, engagement: Engagement) -> list[dict]:
    return [
        _option_dict(engagement, to_status)
        for to_status in available_transitions(engagement)
        if can_act_on_transition(user, engagement, to_status)
    ]


def transition_warnings(engagement: Engagement, to_status: str) -> list[str]:
    warnings = []
    if to_status == Status.DELIVERED:
        from apps.reports.services import PUBLISHABLE_STATUSES

        not_approved = engagement.findings.filter(archived=False).exclude(
            workflow_status__in=PUBLISHABLE_STATUSES
        ).count()
        if not_approved:
            warnings.append(
                f"{not_approved} finding{'s' if not_approved != 1 else ''} not yet QA-approved — "
                "these won't appear in any report generated for this engagement until they are."
            )
    return warnings


def denied_message(engagement: Engagement, to_status: str) -> str:
    if engagement.status == Status.IN_PROGRESS and to_status == Status.IN_REVIEW:
        return "You need access to this engagement to move it to Review."
    if engagement.status == Status.IN_REVIEW and to_status in (Status.QA, Status.IN_PROGRESS):
        return "Only a Superadmin, Team Lead, or this engagement's configured reviewer can do that."
    if engagement.status == Status.QA and to_status == Status.APPROVED:
        return "Only a Superadmin, Team Lead, or this engagement's configured approver can approve it."
    if engagement.status == Status.QA and to_status == Status.IN_REVIEW:
        return "Only a Superadmin, Team Lead, or this engagement's configured QA reviewer can do that."
    return "Only a Superadmin or Team Lead can change this engagement's status."


def _auto_assign_on_transition(engagement: Engagement, to_status: str, *, actor) -> None:
    if to_status == Status.IN_REVIEW and engagement.default_reviewer_id:
        from apps.findings.review import auto_assign_reviewer_for_engagement

        auto_assign_reviewer_for_engagement(engagement, engagement.default_reviewer, triggered_by=actor)
    elif to_status == Status.QA:
        if engagement.default_qa_id:
            from apps.findings.review import auto_assign_qa_for_engagement

            auto_assign_qa_for_engagement(engagement, engagement.default_qa, triggered_by=actor)
        if engagement.default_approver_id:
            from apps.notifications.services import notify_approval_ready

            notify_approval_ready(engagement, engagement.default_approver, actor=actor)


def transition_engagement(engagement: Engagement, to_status: str, *, actor) -> Engagement:
    if to_status not in Status.values:
        raise ValueError(f"Invalid status: {to_status!r}")
    if not can_act_on_transition(actor, engagement, to_status):
        raise PermissionDenied(denied_message(engagement, to_status))
    if engagement.archived:
        raise PermissionDenied("Archived engagements can't change status.")
    if to_status not in available_transitions(engagement):
        raise PermissionDenied(
            f"Can't move directly from {engagement.get_status_display()} to {dict(Status.choices)[to_status]}."
        )

    engagement.status = to_status
    engagement.save(update_fields=["status", "updated_at"])
    EngagementStatusHistory.objects.create(engagement=engagement, status=to_status, changed_by=actor)
    _auto_assign_on_transition(engagement, to_status, actor=actor)
    return engagement
