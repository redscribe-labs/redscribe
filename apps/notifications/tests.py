import os

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.crypto.services import generate_project_key
from apps.engagements.models import Engagement, EngagementMembership, ScopeChangeRequest
from apps.findings.models import ClassificationTag, Finding
from apps.findings import review

from . import services
from .models import Notification

User = get_user_model()
TEST_PASSWORD = "a-very-long-test-password-123!"


def make_user(role, **kwargs):
    kwargs.setdefault("username", f"user-{role.lower()}-{os.urandom(4).hex()}")
    kwargs.setdefault("email", f"{kwargs['username']}@example.com")
    user = User.objects.create(
        role=Role.objects.get(slug=role.lower()), auth_type=User.AuthType.LOCAL, **kwargs
    )
    user.set_password(TEST_PASSWORD)
    user.save()
    return user


def login(client: Client, user) -> None:
    from django_otp import login as otp_login
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client.force_login(user)
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    session = client.session
    request = type("R", (), {"session": session, "user": user})()
    otp_login(request, device)
    session.save()


def make_finding(engagement, created_by, **kwargs):
    tag = ClassificationTag.objects.filter(taxonomy="OWASP Top 10 2021").first()
    finding = Finding.objects.create(
        engagement=engagement,
        title=kwargs.pop("title", "Test finding"),
        severity=kwargs.pop("severity", Finding.Severity.HIGH),
        created_by=created_by,
        **kwargs,
    )
    finding.classifications.add(tag)
    return finding


class AssignmentNotificationTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant_author, title="SQL Injection")

    def test_assigning_reviewer_creates_notification_and_sends_email(self):
        senior = make_user(User.Role.SENIOR)
        with self.captureOnCommitCallbacks(execute=True):
            review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
        services.wait_for_pending_notification_emails()

        notification = Notification.objects.get(recipient=senior)
        self.assertEqual(notification.verb, Notification.Verb.REVIEWER_ASSIGNED)
        self.assertEqual(notification.finding, self.finding)
        self.assertEqual(notification.actor, self.team_lead)
        self.assertFalse(notification.read)
        self.assertIn("SQL Injection", notification.message)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(senior.email, mail.outbox[0].to)
        self.assertNotIn("SQL Injection", mail.outbox[0].body)
        self.assertNotIn("Acme", mail.outbox[0].body)
        self.assertNotIn("SQL Injection", mail.outbox[0].subject)
        self.assertNotIn("Acme", mail.outbox[0].subject)
        for alt_body, _mimetype in mail.outbox[0].alternatives:
            self.assertNotIn("SQL Injection", alt_body)
            self.assertNotIn("Acme", alt_body)
        self.assertIn("assigned as a reviewer", mail.outbox[0].body)

    def test_assigning_qa_creates_notification_and_sends_email(self):
        review.assign_reviewer(self.finding, make_user(User.Role.SENIOR), assigned_by=self.team_lead)
        review.submit_review(self.finding, self.finding.assigned_reviewer, Finding.WorkflowStatus.REVIEWED)
        mail.outbox.clear()

        qa = make_user(User.Role.SENIOR)
        with self.captureOnCommitCallbacks(execute=True):
            review.assign_qa(self.finding, qa, assigned_by=self.team_lead)
        services.wait_for_pending_notification_emails()

        notification = Notification.objects.get(recipient=qa)
        self.assertEqual(notification.verb, Notification.Verb.QA_ASSIGNED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(qa.email, mail.outbox[0].to)

    def test_no_email_sent_when_recipient_has_no_address(self):
        senior = make_user(User.Role.SENIOR, email="")
        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
        self.assertTrue(Notification.objects.filter(recipient=senior).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_user_can_opt_out_of_email_but_still_gets_in_app_notification(self):
        senior = make_user(User.Role.SENIOR)
        senior.email_notifications_enabled = False
        senior.save(update_fields=["email_notifications_enabled"])

        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)

        self.assertTrue(Notification.objects.filter(recipient=senior).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_email_send_failure_does_not_raise_or_lose_notification(self):
        from unittest.mock import patch

        senior = make_user(User.Role.SENIOR)
        with patch("apps.notifications.services.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            with self.captureOnCommitCallbacks(execute=True):
                review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)
            services.wait_for_pending_notification_emails()

        self.assertTrue(Notification.objects.filter(recipient=senior).exists())
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, senior)

    def test_disabled_feature_flag_skips_both_in_app_and_email(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.notifications = False
        flags.save()

        senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)

        self.assertFalse(Notification.objects.filter(recipient=senior).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_pending_email_threads_self_remove_instead_of_growing_forever(self):
        # Every dispatched thread used to stay in services._pending_email_threads
        # forever — only the test-only wait_for_pending_notification_emails() ever
        # drained it, so it grew unboundedly in production. Deliberately don't call
        # that helper here (it would trivially "prove" cleanup by draining the list
        # itself) — poll for the thread finishing and self-removing on its own instead.
        import time

        senior = make_user(User.Role.SENIOR)
        with self.captureOnCommitCallbacks(execute=True):
            review.assign_reviewer(self.finding, senior, assigned_by=self.team_lead)

        deadline = time.monotonic() + 5
        while services._pending_email_threads and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(services._pending_email_threads, [])


class EngagementNotificationEmailRedactionTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Very Secret Client Co")
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)

    def _assert_client_name_not_leaked(self):
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("Very Secret Client Co", mail.outbox[0].subject)
        self.assertNotIn("Very Secret Client Co", mail.outbox[0].body)
        for alt_body, _mimetype in mail.outbox[0].alternatives:
            self.assertNotIn("Very Secret Client Co", alt_body)

    def test_approval_ready_email_does_not_leak_client_name(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.notify_approval_ready(self.engagement, self.team_lead, actor=self.consultant)
        services.wait_for_pending_notification_emails()
        self._assert_client_name_not_leaked()

    def test_scope_change_approved_email_does_not_leak_client_name(self):
        scope_request = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="Add api.example.com", requested_by=self.consultant,
        )
        with self.captureOnCommitCallbacks(execute=True):
            services.notify_scope_change_approved(scope_request, actor=self.team_lead)
        services.wait_for_pending_notification_emails()
        self._assert_client_name_not_leaked()

    def test_scope_change_rejected_email_does_not_leak_client_name(self):
        scope_request = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="Add api.example.com", requested_by=self.consultant,
        )
        with self.captureOnCommitCallbacks(execute=True):
            services.notify_scope_change_rejected(scope_request, actor=self.team_lead)
        services.wait_for_pending_notification_emails()
        self._assert_client_name_not_leaked()


class BulkAssignmentEmailBatchingTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.senior = make_user(User.Role.SENIOR)
        self.findings = [make_finding(self.engagement, self.consultant_author) for _ in range(5)]

    def test_bulk_assign_reviewer_sends_one_summary_email_not_one_per_finding(self):
        with self.captureOnCommitCallbacks(execute=True):
            assigned, skipped = review.bulk_assign_reviewer(
                self.engagement, self.senior, assigned_by=self.team_lead,
            )
        services.wait_for_pending_notification_emails()

        self.assertEqual(len(assigned), 5)
        self.assertEqual(Notification.objects.filter(recipient=self.senior).count(), 5)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("5 findings", mail.outbox[0].body)

    def test_bulk_assign_qa_sends_one_summary_email_not_one_per_finding(self):
        for finding in self.findings:
            review.assign_reviewer(finding, self.senior, assigned_by=self.team_lead)
        review.bulk_submit_review(self.engagement, self.senior, Finding.WorkflowStatus.REVIEWED)
        mail.outbox.clear()

        qa_person = make_user(User.Role.SENIOR)
        with self.captureOnCommitCallbacks(execute=True):
            assigned, skipped = review.bulk_assign_qa(self.engagement, qa_person, assigned_by=self.team_lead)
        services.wait_for_pending_notification_emails()

        self.assertEqual(len(assigned), 5)
        self.assertEqual(Notification.objects.filter(recipient=qa_person).count(), 5)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("5 findings", mail.outbox[0].body)

    def test_auto_assign_qa_for_engagement_also_batches_the_email(self):
        for finding in self.findings:
            review.assign_reviewer(finding, self.senior, assigned_by=self.team_lead)
        review.bulk_submit_review(self.engagement, self.senior, Finding.WorkflowStatus.REVIEWED)
        mail.outbox.clear()

        qa_person = make_user(User.Role.SENIOR)
        with self.captureOnCommitCallbacks(execute=True):
            assigned, skipped = review.auto_assign_qa_for_engagement(
                self.engagement, qa_person, triggered_by=self.team_lead,
            )
        services.wait_for_pending_notification_emails()

        self.assertEqual(len(assigned), 5)
        self.assertEqual(len(mail.outbox), 1)

    def test_bulk_submit_review_batches_the_auto_qa_assignment_email_too(self):
        # A REVIEWED outcome can silently auto-assign QA (auto_assign_qa_if_configured,
        # called from within submit_review) when the engagement is already in QA status
        # with a default QA reviewer configured — that assignment email must be batched
        # exactly like an explicit bulk_assign_qa, not fired once per finding.
        from apps.engagements.models import Engagement

        qa_person = make_user(User.Role.SENIOR)
        self.engagement.status = Engagement.Status.QA
        self.engagement.default_qa = qa_person
        self.engagement.save(update_fields=["status", "default_qa"])
        for finding in self.findings:
            review.assign_reviewer(finding, self.senior, assigned_by=self.team_lead)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            updated, skipped = review.bulk_submit_review(
                self.engagement, self.senior, Finding.WorkflowStatus.REVIEWED,
            )
        services.wait_for_pending_notification_emails()

        self.assertEqual(len(updated), 5)
        self.assertTrue(all(f.assigned_qa_id == qa_person.pk for f in updated))
        qa_emails = [msg for msg in mail.outbox if qa_person.email in msg.to]
        self.assertEqual(len(qa_emails), 1, "expected exactly one batched QA-assignment email, not one per finding")
        self.assertIn("5 findings", qa_emails[0].body)


class ReviewAndQAOutcomeNotificationTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.senior_reviewer = make_user(User.Role.SENIOR)
        self.finding = make_finding(self.engagement, self.consultant_author, title="SQL Injection")
        review.assign_reviewer(self.finding, self.senior_reviewer, assigned_by=self.team_lead)
        mail.outbox.clear()

    def test_review_outcome_notifies_author_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            review.submit_review(self.finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED)
        services.wait_for_pending_notification_emails()

        notification = Notification.objects.get(recipient=self.consultant_author)
        self.assertEqual(notification.verb, Notification.Verb.REVIEWED)
        self.assertEqual(notification.actor, self.senior_reviewer)
        self.assertIn("SQL Injection", notification.message)
        self.assertFalse(
            Notification.objects.filter(recipient=self.senior_reviewer, verb=Notification.Verb.REVIEWED).exists()
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.consultant_author.email, mail.outbox[0].to)
        self.assertNotIn("SQL Injection", mail.outbox[0].body)
        self.assertNotIn("Acme", mail.outbox[0].body)

    def test_review_changes_requested_notifies_author(self):
        with self.captureOnCommitCallbacks(execute=True):
            review.submit_review(
                self.finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEW_CHANGES_REQUESTED,
            )
        services.wait_for_pending_notification_emails()

        notification = Notification.objects.get(recipient=self.consultant_author)
        self.assertEqual(notification.verb, Notification.Verb.REVIEW_CHANGES_REQUESTED)
        self.assertEqual(len(mail.outbox), 1)

    def test_qa_outcome_notifies_both_author_and_reviewer(self):
        review.submit_review(self.finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED)
        qa_person = make_user(User.Role.SENIOR)
        review.assign_qa(self.finding, qa_person, assigned_by=self.team_lead)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            review.submit_qa(self.finding, qa_person, Finding.WorkflowStatus.QA_APPROVED)
        services.wait_for_pending_notification_emails()

        self.assertTrue(Notification.objects.filter(
            recipient=self.consultant_author, verb=Notification.Verb.QA_APPROVED,
        ).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.senior_reviewer, verb=Notification.Verb.QA_APPROVED,
        ).exists())
        self.assertEqual(len(mail.outbox), 2)
        recipients = {addr for msg in mail.outbox for addr in msg.to}
        self.assertEqual(recipients, {self.consultant_author.email, self.senior_reviewer.email})

    def test_qa_outcome_dedupes_when_author_is_also_the_reviewer(self):
        # Only a role with the "review own findings" permission (e.g. Team Lead) can be both
        # a finding's author and its reviewer.
        self_reviewed_finding = make_finding(self.engagement, self.team_lead, title="Self reviewed")
        review.assign_reviewer(self_reviewed_finding, self.team_lead, assigned_by=self.team_lead)
        review.submit_review(self_reviewed_finding, self.team_lead, Finding.WorkflowStatus.REVIEWED)
        qa_person = make_user(User.Role.SENIOR)
        review.assign_qa(self_reviewed_finding, qa_person, assigned_by=self.team_lead)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            review.submit_qa(self_reviewed_finding, qa_person, Finding.WorkflowStatus.QA_APPROVED)
        services.wait_for_pending_notification_emails()

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.team_lead, finding=self_reviewed_finding, verb=Notification.Verb.QA_APPROVED,
            ).count(),
            1,
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_bulk_submit_review_sends_one_summary_email_per_author(self):
        # Take self.finding out of contention first so it doesn't get swept into the bulk action.
        review.submit_review(self.finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED)
        mail.outbox.clear()
        Notification.objects.all().delete()

        other_author = make_user(User.Role.CONSULTANT)
        findings = [
            make_finding(self.engagement, self.consultant_author) for _ in range(3)
        ] + [make_finding(self.engagement, other_author) for _ in range(2)]
        for finding in findings:
            review.assign_reviewer(finding, self.senior_reviewer, assigned_by=self.team_lead)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            updated, skipped = review.bulk_submit_review(
                self.engagement, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED,
            )
        services.wait_for_pending_notification_emails()

        self.assertEqual(len(updated), 5)
        self.assertEqual(Notification.objects.filter(recipient=self.consultant_author).count(), 3)
        self.assertEqual(Notification.objects.filter(recipient=other_author).count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        bodies = [msg.body for msg in mail.outbox]
        self.assertTrue(any("3 findings" in body for body in bodies))
        self.assertTrue(any("2 findings" in body for body in bodies))

    def test_bulk_submit_qa_batches_across_authors_and_reviewers(self):
        qa_person = make_user(User.Role.SENIOR)
        findings = [make_finding(self.engagement, self.consultant_author) for _ in range(3)]
        for finding in findings:
            review.assign_reviewer(finding, self.senior_reviewer, assigned_by=self.team_lead)
            review.submit_review(finding, self.senior_reviewer, Finding.WorkflowStatus.REVIEWED)
            review.assign_qa(finding, qa_person, assigned_by=self.team_lead)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            updated, skipped = review.bulk_submit_qa(
                self.engagement, qa_person, Finding.WorkflowStatus.QA_APPROVED,
            )
        services.wait_for_pending_notification_emails()

        self.assertEqual(len(updated), 3)
        self.assertEqual(len(mail.outbox), 2)
        recipients = {addr for msg in mail.outbox for addr in msg.to}
        self.assertEqual(recipients, {self.consultant_author.email, self.senior_reviewer.email})


class NotificationViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant_author = make_user(User.Role.CONSULTANT)
        self.finding = make_finding(self.engagement, self.consultant_author)
        self.senior = make_user(User.Role.SENIOR)
        review.assign_reviewer(self.finding, self.senior, assigned_by=self.team_lead)
        self.notification = Notification.objects.get(recipient=self.senior)

    def test_user_only_sees_own_notifications(self):
        other = make_user(User.Role.SENIOR)
        client = Client()
        login(client, other)
        resp = client.get(reverse("notifications:list"))
        self.assertNotContains(resp, self.notification.message)

    def test_opening_notification_marks_read_and_redirects_to_finding(self):
        client = Client()
        login(client, self.senior)
        resp = client.get(reverse("notifications:open", args=[self.notification.pk]))
        self.assertRedirects(resp, reverse("findings:detail", args=[self.engagement.pk, self.finding.pk]))
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.read)
        self.assertIsNotNone(self.notification.read_at)

    def test_opening_scope_change_notification_redirects_to_engagement(self):
        from apps.engagements.models import EngagementMembership

        EngagementMembership.objects.create(user=self.consultant_author, engagement=self.engagement)
        from apps.engagements.models import ScopeChangeRequest
        from apps.notifications.services import notify_scope_change_approved

        req = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="new scope", requested_by=self.consultant_author,
        )
        notify_scope_change_approved(req, actor=self.team_lead)
        notification = Notification.objects.get(recipient=self.consultant_author)

        client = Client()
        login(client, self.consultant_author)
        resp = client.get(reverse("notifications:open", args=[notification.pk]))
        self.assertRedirects(resp, reverse("engagements:detail", args=[self.engagement.pk]))

    def test_cannot_open_someone_elses_notification(self):
        other = make_user(User.Role.SENIOR)
        client = Client()
        login(client, other)
        resp = client.get(reverse("notifications:open", args=[self.notification.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_mark_all_read(self):
        client = Client()
        login(client, self.senior)
        resp = client.post(reverse("notifications:mark_all_read"))
        self.assertEqual(resp.status_code, 302)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.read)

    def test_mark_all_read_ignores_malicious_next_open_redirect(self):
        client = Client()
        login(client, self.senior)
        resp = client.post(
            reverse("notifications:mark_all_read"), {"next": "https://evil.example/phish"},
        )
        self.assertRedirects(resp, reverse("notifications:list"))

    def test_mark_all_read_honours_legitimate_same_site_next(self):
        client = Client()
        login(client, self.senior)
        target = reverse("findings:detail", args=[self.engagement.pk, self.finding.pk])
        resp = client.post(reverse("notifications:mark_all_read"), {"next": target})
        self.assertRedirects(resp, target)

    def test_unread_count_in_context(self):
        client = Client()
        login(client, self.senior)
        resp = client.get(reverse("accounts:dashboard"))
        self.assertEqual(resp.context["unread_notification_count"], 1)
