from django.core.exceptions import PermissionDenied

from apps.engagements.models import Engagement

from .models import Finding, RetestRecord

RETEST_ENGAGEMENT_STATUSES = {
    Engagement.Status.AWAITING_REMEDIATION_TEST,
    Engagement.Status.REMEDIATION_TEST,
}


def can_log_retest_result(user, finding: Finding) -> bool:
    if not user.is_authenticated:
        return False
    if finding.archived:
        return False
    return finding.engagement.status in RETEST_ENGAGEMENT_STATUSES


def log_retest_result(finding: Finding, *, status: str, notes_ciphertext, tested_by) -> RetestRecord:
    if finding.engagement.status not in RETEST_ENGAGEMENT_STATUSES:
        raise PermissionDenied(
            "Retest results can only be logged while the engagement is Awaiting Remediation Test "
            "or in Remediation Test."
        )
    if finding.archived:
        raise PermissionDenied("This finding is archived and can't be retested.")
    if status not in Finding.RetestStatus.values or status == Finding.RetestStatus.NOT_RETESTED:
        raise ValueError(f"Invalid retest status: {status!r}")

    record = RetestRecord.objects.create(
        finding=finding, status=status, notes_ciphertext=notes_ciphertext, tested_by=tested_by,
    )
    finding.retest_status = status
    if status == Finding.RetestStatus.FIXED:
        finding.status = Finding.Status.CLOSED
    elif status in (Finding.RetestStatus.NOT_FIXED, Finding.RetestStatus.PARTIALLY_FIXED):
        finding.status = Finding.Status.OPEN
    # RISK_ACCEPTED is a decision, not a fix: leave status unchanged.
    finding.save(update_fields=["retest_status", "status"])
    return record
