import logging
import threading

from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string

from apps.feature_flags.models import FeatureFlags

from .models import Notification

logger = logging.getLogger(__name__)

# Emails leave RedScribe's control (SMTP relay, the recipient's inbox, any backup of it), so they
# must never carry client names, finding titles, or other engagement-identifying detail — if a
# mailbox is compromised, that would hand over every client's vulnerability data. The in-app
# Notification.message field stays detailed since viewing it already requires authentication.
_GENERIC_EMAIL_SUMMARIES = {
    Notification.Verb.REVIEWER_ASSIGNED: "You've been assigned as a reviewer on a finding.",
    Notification.Verb.QA_ASSIGNED: "You've been assigned as a QA approver on a finding.",
    Notification.Verb.APPROVAL_READY: "An engagement you approve has moved to QA and is ready for review.",
    Notification.Verb.SCOPE_CHANGE_APPROVED: "A scope change request you submitted was approved.",
    Notification.Verb.SCOPE_CHANGE_REJECTED: "A scope change request you submitted was rejected.",
    Notification.Verb.REVIEWED: "A finding you authored was reviewed.",
    Notification.Verb.REVIEW_CHANGES_REQUESTED: "A finding you authored needs changes after review.",
    Notification.Verb.QA_APPROVED: "A finding was QA approved.",
    Notification.Verb.QA_CHANGES_REQUESTED: "A finding needs changes after QA review.",
}
_DEFAULT_EMAIL_SUMMARY = "You have a new notification."

_pending_email_threads: list[threading.Thread] = []
_pending_email_threads_lock = threading.Lock()


def _dispatch_email(recipient_email, subject, text_body, html_body) -> None:
    """Hand the actual SMTP send off to a background thread once the transaction commits.

    A bulk action (e.g. auto-assigning QA across an entire engagement) can trigger dozens of
    these; sending synchronously blocked the request on that many round-trips to the mail
    server. Fire-and-forget on failure matches the prior behavior (logged, never raised —
    see test_email_send_failure_does_not_raise_or_lose_notification), just off the request thread.
    """
    def _send():
        try:
            email = EmailMultiAlternatives(subject, text_body, None, [recipient_email])
            email.attach_alternative(html_body, "text/html")
            email.send(fail_silently=False)
        except Exception:
            logger.exception("Failed to send notification email to %s", recipient_email)
        finally:
            # Every dispatched thread used to stay in this list forever — only
            # wait_for_pending_notification_emails() (test-only) ever drained it, so in
            # production it grew unboundedly for the life of the process. Each thread now
            # removes its own completed entry, so the list only ever holds genuinely
            # in-flight sends.
            with _pending_email_threads_lock:
                current = threading.current_thread()
                if current in _pending_email_threads:
                    _pending_email_threads.remove(current)

    def _start():
        thread = threading.Thread(target=_send, daemon=True)
        with _pending_email_threads_lock:
            _pending_email_threads.append(thread)
        thread.start()

    transaction.on_commit(_start)


def wait_for_pending_notification_emails(timeout=5) -> None:
    """Test helper: block until every background email dispatched so far has finished sending.

    Emails go out on a daemon thread (see _dispatch_email) so the request isn't blocked on SMTP;
    tests need a deterministic way to observe the result instead of racing that thread.
    """
    with _pending_email_threads_lock:
        threads, _pending_email_threads[:] = list(_pending_email_threads), []
    for thread in threads:
        thread.join(timeout)


def _send_notification_email(recipient, actor, summary) -> None:
    if not (recipient.email and recipient.email_notifications_enabled):
        return
    from apps.reports.branding import get_branding

    branding = get_branding()
    email_context = {"recipient": recipient, "actor": actor, "summary": summary, "branding": branding}
    text_body = render_to_string("notifications/email/assignment.txt", email_context)
    html_body = render_to_string("notifications/email/assignment.html", email_context)
    _dispatch_email(recipient.email, f"{branding['display_name']}: New notification", text_body, html_body)


def _notify(
    *, recipient, actor, verb, message, finding=None, engagement=None, send_email=True,
) -> Notification | None:
    if not FeatureFlags.get_solo().notifications:
        return None

    notification = Notification.objects.create(
        recipient=recipient, actor=actor, finding=finding, engagement=engagement, verb=verb, message=message,
    )
    if send_email:
        summary = _GENERIC_EMAIL_SUMMARIES.get(verb, _DEFAULT_EMAIL_SUMMARY)
        _send_notification_email(recipient, actor, summary)
    return notification


def notify_reviewer_assigned(finding, reviewer, *, assigned_by, send_email=True) -> Notification | None:
    message = f"You were assigned as reviewer for \"{finding.title}\" ({finding.engagement.client_name})."
    return _notify(
        recipient=reviewer, actor=assigned_by, finding=finding,
        verb=Notification.Verb.REVIEWER_ASSIGNED, message=message, send_email=send_email,
    )


def notify_qa_assigned(finding, qa_reviewer, *, assigned_by, send_email=True) -> Notification | None:
    message = f"You were assigned as QA approver for \"{finding.title}\" ({finding.engagement.client_name})."
    return _notify(
        recipient=qa_reviewer, actor=assigned_by, finding=finding,
        verb=Notification.Verb.QA_ASSIGNED, message=message, send_email=send_email,
    )


def notify_bulk_reviewer_assigned(reviewer, count, *, actor) -> None:
    """One summary email for a whole batch of per-finding reviewer assignments, instead of one each."""
    if not count or not FeatureFlags.get_solo().notifications:
        return
    plural = "s" if count != 1 else ""
    _send_notification_email(reviewer, actor, f"You've been assigned as a reviewer on {count} finding{plural}.")


def notify_bulk_qa_assigned(qa_reviewer, count, *, actor) -> None:
    """One summary email for a whole batch of per-finding QA assignments, instead of one each."""
    if not count or not FeatureFlags.get_solo().notifications:
        return
    plural = "s" if count != 1 else ""
    _send_notification_email(qa_reviewer, actor, f"You've been assigned as a QA approver on {count} finding{plural}.")


def notify_approval_ready(engagement, approver, *, actor) -> Notification | None:
    message = f"\"{engagement.client_name}\" has moved to QA — you're the configured approver for this engagement."
    return _notify(
        recipient=approver, actor=actor, engagement=engagement,
        verb=Notification.Verb.APPROVAL_READY, message=message,
    )


def notify_scope_change_approved(scope_request, *, actor) -> Notification | None:
    if scope_request.requested_by_id is None:
        return None
    engagement = scope_request.engagement
    message = f"Your scope change for \"{engagement.client_name}\" was approved."
    return _notify(
        recipient=scope_request.requested_by, actor=actor, engagement=engagement,
        verb=Notification.Verb.SCOPE_CHANGE_APPROVED, message=message,
    )


_REVIEW_OUTCOME_LABELS = {
    Notification.Verb.REVIEWED: "reviewed",
    Notification.Verb.REVIEW_CHANGES_REQUESTED: "sent back with changes requested",
    Notification.Verb.QA_APPROVED: "QA approved",
    Notification.Verb.QA_CHANGES_REQUESTED: "sent back from QA with changes requested",
}


def notify_review_outcome(finding, outcome: str, *, actor, send_email=True) -> Notification | None:
    """Tell the finding's author what its reviewer decided (Reviewed / Changes Requested)."""
    author = finding.created_by
    if author is None:
        return None
    verb = Notification.Verb(outcome)
    label = _REVIEW_OUTCOME_LABELS[verb]
    message = f"Your finding \"{finding.title}\" ({finding.engagement.client_name}) was {label} by {actor}."
    return _notify(
        recipient=author, actor=actor, finding=finding, verb=verb, message=message, send_email=send_email,
    )


def notify_qa_outcome(finding, outcome: str, *, actor, send_email=True) -> list[Notification]:
    """Tell the finding's author and its reviewer what QA decided (QA Approved / Changes Requested)."""
    verb = Notification.Verb(outcome)
    label = _REVIEW_OUTCOME_LABELS[verb]
    recipients = {}
    author = finding.created_by
    if author is not None:
        recipients[author.pk] = (
            author, f"Your finding \"{finding.title}\" ({finding.engagement.client_name}) was {label} by {actor}."
        )
    reviewer = finding.assigned_reviewer
    if reviewer is not None and reviewer.pk not in recipients:
        recipients[reviewer.pk] = (
            reviewer,
            f"A finding you reviewed, \"{finding.title}\" ({finding.engagement.client_name}), was {label} by {actor}.",
        )
    return [
        _notify(recipient=recipient, actor=actor, finding=finding, verb=verb, message=message, send_email=send_email)
        for recipient, message in recipients.values()
    ]


def notify_bulk_review_outcome(author, count, outcome: str, *, actor) -> None:
    """One summary email per author when a reviewer clears several findings at once with the same outcome."""
    if not count or not FeatureFlags.get_solo().notifications:
        return
    verb = Notification.Verb(outcome)
    label = _REVIEW_OUTCOME_LABELS[verb]
    plural = "s" if count != 1 else ""
    was_were = "were" if count != 1 else "was"
    _send_notification_email(author, actor, f"{count} finding{plural} you authored {was_were} {label}.")


def notify_bulk_qa_outcome(recipient, count, outcome: str, *, actor) -> None:
    """One summary email per author/reviewer when a QA approver clears several findings at once."""
    if not count or not FeatureFlags.get_solo().notifications:
        return
    verb = Notification.Verb(outcome)
    label = _REVIEW_OUTCOME_LABELS[verb]
    plural = "s" if count != 1 else ""
    was_were = "were" if count != 1 else "was"
    _send_notification_email(recipient, actor, f"{count} finding{plural} you're involved in {was_were} {label}.")


def notify_scope_change_rejected(scope_request, *, actor) -> Notification | None:
    if scope_request.requested_by_id is None:
        return None
    engagement = scope_request.engagement
    message = f"Your scope change for \"{engagement.client_name}\" was rejected."
    return _notify(
        recipient=scope_request.requested_by, actor=actor, engagement=engagement,
        verb=Notification.Verb.SCOPE_CHANGE_REJECTED, message=message,
    )
