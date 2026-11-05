"""Tests for the assessment-remediation changes (H-1, H-2, M-5b, Part C counts).

Kept in a separate module so the existing tests.py is untouched.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from apps.crypto.services import generate_project_key
from apps.findings.models import Finding

from . import lifecycle
from .metrics import with_metrics
from .models import Engagement, EngagementMembership, ScopeChangeRequest
from .tests import User, login, make_user


def _make_engagement(**kwargs):
    kwargs.setdefault("client_name", "Acme")
    engagement = Engagement.objects.create(**kwargs)
    generate_project_key(engagement)
    return engagement


class CompletenessGateTests(TestCase):
    """H-2: QA->APPROVED and APPROVED->DELIVERED require all active findings QA-approved."""

    def setUp(self):
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.engagement = _make_engagement(status=Engagement.Status.QA)
        self.author = make_user(User.Role.CONSULTANT)

    def test_qa_to_approved_blocked_by_non_qa_approved_active_finding(self):
        Finding.objects.create(
            engagement=self.engagement, title="SQLi", severity=Finding.Severity.HIGH,
            created_by=self.author, workflow_status=Finding.WorkflowStatus.DRAFT,
        )
        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(
                self.engagement, Engagement.Status.APPROVED, actor=self.team_lead
            )

    def test_qa_to_approved_allowed_when_all_active_findings_qa_approved(self):
        Finding.objects.create(
            engagement=self.engagement, title="SQLi", severity=Finding.Severity.HIGH,
            created_by=self.author, workflow_status=Finding.WorkflowStatus.QA_APPROVED,
        )
        lifecycle.transition_engagement(
            self.engagement, Engagement.Status.APPROVED, actor=self.team_lead
        )
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.APPROVED)

    def test_archived_non_approved_finding_does_not_block(self):
        Finding.objects.create(
            engagement=self.engagement, title="SQLi", severity=Finding.Severity.HIGH,
            created_by=self.author, workflow_status=Finding.WorkflowStatus.DRAFT, archived=True,
        )
        lifecycle.transition_engagement(
            self.engagement, Engagement.Status.APPROVED, actor=self.team_lead
        )
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.APPROVED)

    def test_approved_to_delivered_blocked(self):
        engagement = _make_engagement(status=Engagement.Status.APPROVED)
        Finding.objects.create(
            engagement=engagement, title="XSS", severity=Finding.Severity.MEDIUM,
            created_by=self.author, workflow_status=Finding.WorkflowStatus.REVIEWED,
        )
        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(
                engagement, Engagement.Status.DELIVERED, actor=self.team_lead
            )

    def test_non_gated_transition_still_works(self):
        engagement = _make_engagement(status=Engagement.Status.IN_PROGRESS)
        Finding.objects.create(
            engagement=engagement, title="XSS", severity=Finding.Severity.MEDIUM,
            created_by=self.author, workflow_status=Finding.WorkflowStatus.DRAFT,
        )
        lifecycle.transition_engagement(engagement, Engagement.Status.IN_REVIEW, actor=self.team_lead)
        engagement.refresh_from_db()
        self.assertEqual(engagement.status, Engagement.Status.IN_REVIEW)


class ScopeChangeApprovalTests(TestCase):
    """Any engagement manager may approve a scope change, including its submitter
    (small teams rely on self-serve; reviewer independence isn't enforced here)."""

    def setUp(self):
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.other_lead = make_user(User.Role.TEAM_LEAD)
        self.engagement = _make_engagement(status=Engagement.Status.IN_PROGRESS)

    def _request_for(self, user):
        return ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="app.acme.com/*", requested_by=user,
        )

    def test_submitter_can_approve_own_scope_change(self):
        req = self._request_for(self.team_lead)
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:scope_change_approve", args=[self.engagement.pk, req.pk])
        )
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ScopeChangeRequest.Status.APPROVED)

    def test_different_manager_can_approve(self):
        req = self._request_for(self.team_lead)
        client = Client()
        login(client, self.other_lead)
        resp = client.post(
            reverse("engagements:scope_change_approve", args=[self.engagement.pk, req.pk])
        )
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ScopeChangeRequest.Status.APPROVED)


class MemberRemovalCleanupTests(TestCase):
    """M-5b: removing a member clears their default roles and finding assignments."""

    def setUp(self):
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.member = make_user(User.Role.SENIOR)
        self.author = make_user(User.Role.CONSULTANT)
        self.engagement = _make_engagement(status=Engagement.Status.IN_PROGRESS)
        self.engagement.default_reviewer = self.member
        self.engagement.default_qa = self.member
        self.engagement.save(update_fields=["default_reviewer", "default_qa"])
        self.membership = EngagementMembership.objects.create(
            user=self.member, engagement=self.engagement
        )
        self.finding = Finding.objects.create(
            engagement=self.engagement, title="SQLi", severity=Finding.Severity.HIGH,
            created_by=self.author, assigned_reviewer=self.member, assigned_qa=self.member,
        )

    def test_removal_nulls_defaults_and_assignments(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:member_remove", args=[self.engagement.pk, self.membership.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertIsNone(self.engagement.default_reviewer_id)
        self.assertIsNone(self.engagement.default_qa_id)
        self.finding.refresh_from_db()
        self.assertIsNone(self.finding.assigned_reviewer_id)
        self.assertIsNone(self.finding.assigned_qa_id)


class ArchivedCountTests(TestCase):
    """Part C: engagement finding counts exclude archived findings."""

    def setUp(self):
        self.author = make_user(User.Role.CONSULTANT)
        self.engagement = _make_engagement(status=Engagement.Status.IN_PROGRESS)
        Finding.objects.create(
            engagement=self.engagement, title="Active", severity=Finding.Severity.CRITICAL,
            created_by=self.author, status=Finding.Status.OPEN,
        )
        Finding.objects.create(
            engagement=self.engagement, title="Archived", severity=Finding.Severity.CRITICAL,
            created_by=self.author, status=Finding.Status.OPEN, archived=True,
        )

    def test_with_metrics_excludes_archived_from_totals(self):
        annotated = with_metrics(Engagement.objects.filter(pk=self.engagement.pk)).get()
        self.assertEqual(annotated.findings_total, 1)
        self.assertEqual(annotated.open_critical, 1)
