from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.engagements.models import Engagement, EngagementMembership
from apps.engagements.permissions import is_engagement_manager
from apps.notifications.services import (
    notify_bulk_qa_assigned,
    notify_bulk_qa_outcome,
    notify_bulk_review_outcome,
    notify_bulk_reviewer_assigned,
    notify_qa_assigned,
    notify_qa_outcome,
    notify_review_outcome,
    notify_reviewer_assigned,
)

from .models import Finding


def _is_eligible(candidate, finding: Finding, permission: str, own_permission: str) -> bool:
    if not candidate.has_permission(permission):
        return False
    author = finding.created_by
    if author is None:
        return False
    if candidate.pk == author.pk and not candidate.has_permission(own_permission):
        return False
    return True


def is_eligible_reviewer(candidate, finding: Finding) -> bool:
    return _is_eligible(candidate, finding, "findings.review", "findings.review_own")


def is_eligible_qa_reviewer(candidate, finding: Finding) -> bool:
    return _is_eligible(candidate, finding, "findings.qa", "findings.qa_own")


def _eligible_candidates(finding: Finding, permission: str, own_permission: str):
    User = get_user_model()
    author = finding.created_by
    if author is None:
        return User.objects.none()

    candidates = User.objects.filter(is_active=True).exclude(role__slug="client").filter(
        Q(role__is_superadmin=True) | Q(role__permissions__codename=permission)
    ).distinct()

    author_can_self_serve = author.has_permission(permission) and author.has_permission(own_permission)
    if not author_can_self_serve:
        candidates = candidates.exclude(pk=author.pk)
    return candidates


def _scoped_to_existing_members_if_non_manager(candidates, engagement, assigned_by):
    if assigned_by is None or is_engagement_manager(assigned_by, engagement):
        return candidates
    member_ids = EngagementMembership.objects.filter(engagement=engagement).values_list("user_id", flat=True)
    return candidates.filter(pk__in=member_ids)


def eligible_reviewer_candidates(finding: Finding, assigned_by=None):
    candidates = _eligible_candidates(finding, "findings.review", "findings.review_own")
    return _scoped_to_existing_members_if_non_manager(candidates, finding.engagement, assigned_by)


def eligible_qa_candidates(finding: Finding, assigned_by=None):
    candidates = _eligible_candidates(finding, "findings.qa", "findings.qa_own")
    return _scoped_to_existing_members_if_non_manager(candidates, finding.engagement, assigned_by)


def _require_assigner(user, finding: Finding):
    if not is_engagement_manager(user, finding.engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can do this.")


def _require_reviewer_assigner(user, finding: Finding):
    if is_engagement_manager(user, finding.engagement):
        return
    if finding.created_by_id and user.pk == finding.created_by_id:
        return
    raise PermissionDenied("Only a Superadmin, Team Lead, or this finding's author can assign a reviewer.")


def _require_qa_assigner(user, finding: Finding):
    if is_engagement_manager(user, finding.engagement):
        return
    if finding.assigned_reviewer_id and user.pk == finding.assigned_reviewer_id:
        return
    if finding.created_by_id and user.pk == finding.created_by_id:
        return
    raise PermissionDenied("Only a Superadmin, Team Lead, this finding's reviewer, or its author can assign QA.")


def _bulk_eligible_candidates(permission: str):
    User = get_user_model()
    return User.objects.filter(is_active=True).exclude(role__slug="client").filter(
        Q(role__is_superadmin=True) | Q(role__permissions__codename=permission)
    ).distinct()


def bulk_eligible_reviewer_candidates():
    return _bulk_eligible_candidates("findings.review")


def bulk_eligible_qa_candidates():
    return _bulk_eligible_candidates("findings.qa")


def bulk_assign_reviewer(engagement, reviewer, *, assigned_by) -> tuple[list, list]:
    """Assigns `reviewer` across every eligible candidate finding in one team-lead action.

    Each finding still gets its own in-app Notification, but the reviewer gets a single
    summary email rather than one per finding.
    """
    if not is_engagement_manager(assigned_by, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can assign reviewers/QA.")
    candidates = engagement.findings.filter(
        workflow_status__in=[Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED],
        archived=False,
    )
    assigned, skipped = [], []
    for finding in candidates:
        try:
            assign_reviewer(finding, reviewer, assigned_by=assigned_by, send_email=False)
        except PermissionDenied:
            skipped.append(finding)
        else:
            assigned.append(finding)
    notify_bulk_reviewer_assigned(reviewer, len(assigned), actor=assigned_by)
    return assigned, skipped


def bulk_assign_qa(engagement, qa_reviewer, *, assigned_by) -> tuple[list, list]:
    """Assigns `qa_reviewer` across every eligible candidate finding in one team-lead action.

    Each finding still gets its own in-app Notification, but the QA reviewer gets a single
    summary email rather than one per finding.
    """
    if not is_engagement_manager(assigned_by, engagement):
        raise PermissionDenied("Only a Superadmin or Team Lead can assign reviewers/QA.")
    candidates = engagement.findings.filter(
        workflow_status__in=[Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED],
        archived=False,
    )
    assigned, skipped = [], []
    for finding in candidates:
        try:
            assign_qa(finding, qa_reviewer, assigned_by=assigned_by, send_email=False)
        except PermissionDenied:
            skipped.append(finding)
        else:
            assigned.append(finding)
    notify_bulk_qa_assigned(qa_reviewer, len(assigned), actor=assigned_by)
    return assigned, skipped


def bulk_submit_review(engagement, user, outcome: str) -> tuple[list, list]:
    """Submits the same review outcome across every candidate finding in one team action.

    Each finding still gets its own in-app Notification, but each author gets a single
    summary email rather than one per finding. A REVIEWED outcome can also silently
    auto-assign QA (see auto_assign_qa_if_configured, called from within submit_review) —
    that's batched into its own summary too, the same way bulk_assign_qa's real QA
    assignments are, rather than firing one "assigned as QA approver" email per finding.
    """
    candidates = engagement.findings.filter(
        workflow_status__in=[Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED],
        archived=False,
    )
    if not user.has_permission("findings.act_any_assignment"):
        candidates = candidates.filter(assigned_reviewer=user)
    updated, skipped = [], []
    author_counts = {}
    qa_auto_assign_counts = {}
    for finding in candidates:
        had_qa_before = finding.assigned_qa_id
        try:
            submit_review(finding, user, outcome, send_email=False)
        except PermissionDenied:
            skipped.append(finding)
        else:
            updated.append(finding)
            author = finding.created_by
            if author is not None:
                entry = author_counts.setdefault(author.pk, [author, 0])
                entry[1] += 1
            if not had_qa_before and finding.assigned_qa_id:
                qa_entry = qa_auto_assign_counts.setdefault(finding.assigned_qa_id, [finding.assigned_qa, 0])
                qa_entry[1] += 1
    for author, count in author_counts.values():
        notify_bulk_review_outcome(author, count, outcome, actor=user)
    for qa_reviewer, count in qa_auto_assign_counts.values():
        notify_bulk_qa_assigned(qa_reviewer, count, actor=user)
    return updated, skipped


def bulk_submit_qa(engagement, user, outcome: str) -> tuple[list, list]:
    """Submits the same QA outcome across every candidate finding in one team action.

    Each finding still gets its own in-app Notification, but each author/reviewer gets a
    single summary email rather than one per finding.
    """
    candidates = engagement.findings.filter(
        workflow_status__in=[Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED],
        archived=False,
    )
    if not user.has_permission("findings.act_any_assignment"):
        candidates = candidates.filter(assigned_qa=user)
    updated, skipped = [], []
    recipient_counts = {}
    for finding in candidates:
        try:
            submit_qa(finding, user, outcome, send_email=False)
        except PermissionDenied:
            skipped.append(finding)
        else:
            updated.append(finding)
            for person in {finding.created_by, finding.assigned_reviewer}:
                if person is not None:
                    entry = recipient_counts.setdefault(person.pk, [person, 0])
                    entry[1] += 1
    for person, count in recipient_counts.values():
        notify_bulk_qa_outcome(person, count, outcome, actor=user)
    return updated, skipped


def _grant_engagement_access(user, engagement, granted_by):
    EngagementMembership.objects.get_or_create(
        user=user, engagement=engagement, defaults={"added_by": granted_by}
    )


def _require_existing_access_if_non_manager(candidate, engagement, assigned_by, *, action: str):
    if is_engagement_manager(assigned_by, engagement):
        return
    if EngagementMembership.objects.filter(user=candidate, engagement=engagement).exists():
        return
    raise PermissionDenied(
        f"{candidate} doesn't already have access to this engagement — only a Superadmin or "
        f"Team Lead can grant that as part of {action}."
    )


def _do_assign_reviewer(finding: Finding, reviewer, *, assigned_by, send_email=True) -> Finding:
    finding.assigned_reviewer = reviewer
    finding.save(update_fields=["assigned_reviewer"])
    _grant_engagement_access(reviewer, finding.engagement, assigned_by)
    notify_reviewer_assigned(finding, reviewer, assigned_by=assigned_by, send_email=send_email)
    return finding


def assign_reviewer(finding: Finding, reviewer, *, assigned_by, send_email=True) -> Finding:
    _require_reviewer_assigner(assigned_by, finding)
    if finding.workflow_status not in {Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED}:
        raise PermissionDenied("Reviewer can only be (re)assigned while the finding is in Draft.")
    if not is_eligible_reviewer(reviewer, finding):
        raise PermissionDenied(f"{reviewer} is not an eligible reviewer for this finding.")
    _require_existing_access_if_non_manager(reviewer, finding.engagement, assigned_by, action="a reviewer assignment")
    return _do_assign_reviewer(finding, reviewer, assigned_by=assigned_by, send_email=send_email)


def submit_review(finding: Finding, user, outcome: str, *, send_email=True) -> Finding:
    if outcome not in {Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED}:
        raise ValueError("Invalid review outcome provided.")
    if not (user.has_permission("findings.act_any_assignment") or (finding.assigned_reviewer_id and user.pk == finding.assigned_reviewer_id)):
        raise PermissionDenied("Only the assigned reviewer (or a Superadmin) can submit this review.")
    if finding.workflow_status not in {Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED}:
        raise PermissionDenied("This finding isn't awaiting review.")

    finding.workflow_status = outcome
    finding.save(update_fields=["workflow_status"])
    if outcome == Finding.WorkflowStatus.REVIEWED:
        auto_assign_qa_if_configured(finding, send_email=send_email)
    notify_review_outcome(finding, outcome, actor=user, send_email=send_email)
    return finding


def _do_assign_qa(finding: Finding, qa_reviewer, *, assigned_by, send_email=True) -> Finding:
    finding.assigned_qa = qa_reviewer
    finding.save(update_fields=["assigned_qa"])
    _grant_engagement_access(qa_reviewer, finding.engagement, assigned_by)
    notify_qa_assigned(finding, qa_reviewer, assigned_by=assigned_by, send_email=send_email)
    return finding


def assign_qa(finding: Finding, qa_reviewer, *, assigned_by, send_email=True) -> Finding:
    _require_qa_assigner(assigned_by, finding)
    if finding.workflow_status not in {Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED}:
        raise PermissionDenied("QA can only be assigned once the finding has been Reviewed.")
    if not is_eligible_qa_reviewer(qa_reviewer, finding):
        raise PermissionDenied(f"{qa_reviewer} is not an eligible QA reviewer for this finding.")
    _require_existing_access_if_non_manager(qa_reviewer, finding.engagement, assigned_by, action="a QA assignment")
    return _do_assign_qa(finding, qa_reviewer, assigned_by=assigned_by, send_email=send_email)


def submit_qa(finding: Finding, user, outcome: str, *, send_email=True) -> Finding:
    if outcome not in {Finding.WorkflowStatus.QA_APPROVED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED}:
        raise ValueError("Invalid QA outcome provided.")
    if not (user.has_permission("findings.act_any_assignment") or (finding.assigned_qa_id and user.pk == finding.assigned_qa_id)):
        raise PermissionDenied("Only the assigned QA reviewer (or a Superadmin) can submit this QA decision.")
    if finding.workflow_status not in {Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED}:
        raise PermissionDenied("This finding isn't awaiting QA.")

    finding.workflow_status = outcome
    finding.save(update_fields=["workflow_status"])
    notify_qa_outcome(finding, outcome, actor=user, send_email=send_email)
    return finding


def assignments_for_user(user):
    to_review = Finding.objects.filter(
        assigned_reviewer=user,
        workflow_status__in=[Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED],
    ).select_related("engagement")
    to_qa = Finding.objects.filter(
        assigned_qa=user,
        workflow_status__in=[Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED],
    ).select_related("engagement")
    return to_review, to_qa


def reopen_to_draft(finding: Finding, user) -> Finding:
    _require_assigner(user, finding)
    if finding.workflow_status == Finding.WorkflowStatus.DRAFT:
        raise PermissionDenied("This finding is already a Draft.")

    finding.workflow_status = Finding.WorkflowStatus.DRAFT
    finding.assigned_reviewer = None
    finding.assigned_qa = None
    finding.save(update_fields=["workflow_status", "assigned_reviewer", "assigned_qa"])
    return finding


def auto_assign_reviewer_for_engagement(engagement, reviewer, *, triggered_by) -> tuple[list, list]:
    """Bulk-assigns every eligible candidate finding to `reviewer` in one go.

    Each finding still gets its own in-app Notification, but the recipient gets a single
    summary email rather than one per finding — moving a large engagement to Review shouldn't
    fire dozens of individual emails at the reviewer.
    """
    candidates = engagement.findings.filter(
        workflow_status__in=[Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED],
        archived=False,
    )
    assigned, skipped = [], []
    for finding in candidates:
        if not is_eligible_reviewer(reviewer, finding):
            skipped.append(finding)
            continue
        _do_assign_reviewer(finding, reviewer, assigned_by=triggered_by, send_email=False)
        assigned.append(finding)
    notify_bulk_reviewer_assigned(reviewer, len(assigned), actor=triggered_by)
    return assigned, skipped


def auto_assign_qa_for_engagement(engagement, qa_reviewer, *, triggered_by) -> tuple[list, list]:
    """Bulk-assigns every eligible candidate finding to `qa_reviewer` in one go.

    Each finding still gets its own in-app Notification, but the recipient gets a single
    summary email rather than one per finding — moving a large engagement to QA shouldn't
    fire dozens of individual emails at the QA reviewer.
    """
    candidates = engagement.findings.filter(
        workflow_status__in=[Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED],
        archived=False,
    )
    assigned, skipped = [], []
    for finding in candidates:
        if not is_eligible_qa_reviewer(qa_reviewer, finding):
            skipped.append(finding)
            continue
        _do_assign_qa(finding, qa_reviewer, assigned_by=triggered_by, send_email=False)
        assigned.append(finding)
    notify_bulk_qa_assigned(qa_reviewer, len(assigned), actor=triggered_by)
    return assigned, skipped


def auto_assign_reviewer_if_configured(finding: Finding) -> None:
    if finding.assigned_reviewer_id:
        return
    engagement = finding.engagement
    if engagement.status != Engagement.Status.IN_REVIEW or not engagement.default_reviewer_id:
        return
    if finding.workflow_status not in {Finding.WorkflowStatus.DRAFT, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED}:
        return
    if not is_eligible_reviewer(engagement.default_reviewer, finding):
        return
    _do_assign_reviewer(finding, engagement.default_reviewer, assigned_by=finding.created_by)


def auto_assign_qa_if_configured(finding: Finding, *, send_email=True) -> None:
    if finding.assigned_qa_id:
        return
    engagement = finding.engagement
    if engagement.status != Engagement.Status.QA or not engagement.default_qa_id:
        return
    if finding.workflow_status not in {Finding.WorkflowStatus.REVIEWED, Finding.WorkflowStatus.QA_CHANGES_REQUESTED}:
        return
    if not is_eligible_qa_reviewer(engagement.default_qa, finding):
        return
    _do_assign_qa(finding, engagement.default_qa, assigned_by=finding.assigned_reviewer, send_email=send_email)
