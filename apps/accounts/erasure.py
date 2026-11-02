from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.integrity import append_with_chain
from apps.engagements.models import EngagementMembership
from apps.notifications.models import Notification

from .models import LoginAttempt, MFAAttempt, User, UserSession


class ErasureError(Exception):
    pass


def erasure_blocker(target: User, actor: User) -> str | None:
    """Why `target` can't be erased right now, or None if it can."""
    if target.erased_at:
        return "This account has already been erased."
    if target.pk == actor.pk:
        return "You can't erase your own account."
    if target.is_active:
        return "Only deactivated accounts can be erased. Deactivate it first."
    return None


def verify_erase_confirmation(request, target: User) -> str | None:
    """Why the typed confirmation in `request.POST` doesn't allow erasure, or None if it does."""
    if request.POST.get("confirm_username") != target.username:
        return "The username you typed didn't match"
    return None


def erase_user(
    target: User, *, actor: User,
    action: str = "user_management:erase_user", route: str = "user-management",
) -> None:
    """Irreversibly strip a deactivated account of personal data, keeping the row.

    The row, id and uuid stay so audit entries (whose hash covers actor_id),
    finding authorship, comments and checklist history keep pointing at it.
    Existing audit rows are never rewritten: their username snapshot is part
    of the hash chain and ages out under normal retention.
    """
    with transaction.atomic():
        target = User.objects.select_for_update().get(pk=target.pk)
        blocker = erasure_blocker(target, actor)
        if blocker:
            raise ErasureError(blocker)

        old_username = target.username
        old_label = str(target)
        old_names = {name for name in (old_label, old_username) if name}
        new_username = f"erased-{target.uuid.hex}"

        target.username = new_username
        target.email = f"{new_username}@erased.invalid"
        target.first_name = ""
        target.last_name = ""
        target.qualifications = ""
        target.background = ""
        target.email_notifications_enabled = False
        target.oauth_invite_pending = False
        target.mfa_enrolled_at = None
        target.last_login = None
        target.set_unusable_password()
        target.erased_at = timezone.now()
        target.save()

        stale_keys = list(UserSession.objects.filter(user=target).values_list("session_key", flat=True))
        Session.objects.filter(session_key__in=stale_keys).delete()
        UserSession.objects.filter(user=target).delete()
        TOTPDevice.objects.filter(user=target).delete()
        MFAAttempt.objects.filter(user=target).delete()
        Notification.objects.filter(recipient=target).delete()
        # Notifications this person caused stay in other people's lists, but their name goes.
        old_suffix, new_suffix = f" by {old_label}.", f" by {target.erased_label}."
        for notification in Notification.objects.filter(actor=target).only("pk", "message"):
            if notification.message.endswith(old_suffix):
                notification.message = notification.message[:-len(old_suffix)] + new_suffix
                notification.save(update_fields=["message"])
        # Engagements this person worked on, kept for redacting older checklist history below.
        engagement_ids = set(
            EngagementMembership.objects.filter(user=target).values_list("engagement_id", flat=True)
        )
        EngagementMembership.objects.filter(user=target).delete()
        LoginAttempt.objects.filter(Q(user=target) | Q(username_attempted=old_username)).update(
            username_attempted=new_username, ip_address=None,
        )

        # Checklist Activity snapshots an assignee's name as plain text. Entries that link the
        # user are redacted exactly. Older ones have no link, so match the name, but only on
        # engagements this person was on, so a namesake elsewhere keeps their history.
        from apps.checklist.models import ChecklistItem, ChecklistItemEvent

        engagement_ids |= set(
            ChecklistItem.objects.filter(assignee=target).values_list("run__engagement_id", flat=True)
        )
        label = target.erased_label
        assignee_events = ChecklistItemEvent.objects.filter(kind=ChecklistItemEvent.Kind.ASSIGNEE)
        assignee_events.filter(from_user=target).update(from_value=label)
        assignee_events.filter(to_user=target).update(to_value=label)
        legacy = assignee_events.filter(item__run__engagement_id__in=engagement_ids)
        legacy.filter(from_user__isnull=True, from_value__in=old_names).update(from_value=label, from_user=target)
        legacy.filter(to_user__isnull=True, to_value__in=old_names).update(to_value=label, to_user=target)

        from allauth.account.models import EmailAddress
        from allauth.socialaccount.models import SocialAccount

        EmailAddress.objects.filter(user=target).delete()
        SocialAccount.objects.filter(user=target).delete()

        append_with_chain(
            actor=actor,
            actor_username=actor.username,
            actor_role=str(actor.role)[:32],
            action=action,
            method="POST",
            path=f"/{route}/{target.uuid}/erase/",
            status_code=302,
            object_ref=f"user_uuid={target.uuid}",
        )
