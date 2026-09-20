from django.core.exceptions import PermissionDenied

from apps.engagements.models import Engagement
from apps.feature_flags.models import FeatureFlags

from .models import Finding, RetestRecord

RETEST_ENGAGEMENT_STATUSES = {
    Engagement.Status.AWAITING_REMEDIATION_TEST,
    Engagement.Status.REMEDIATION_TEST,
}


def can_log_retest_result(user, finding: Finding) -> bool:
    if not FeatureFlags.get_solo().retest_workflow:
        return False
    if not user.is_authenticated:
        return False
    if finding.archived:
        return False
    return finding.engagement.status in RETEST_ENGAGEMENT_STATUSES


def log_retest_result(finding: Finding, *, status: str, notes_ciphertext, tested_by) -> RetestRecord:
    if not FeatureFlags.get_solo().retest_workflow:
        raise PermissionDenied("Retest tracking is currently disabled.")
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
    finding.save(update_fields=["retest_status"])
    return record
