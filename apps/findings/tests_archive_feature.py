"""Archive feature: retest auto-close (Part B) and the Active/Archived list tabs (Part A)."""
from django.urls import reverse
from django.test import Client, TestCase

from apps.accounts.models import User
from apps.crypto.services import generate_project_key
from apps.engagements.models import Engagement, EngagementMembership
from apps.findings.models import Finding

from . import retest
from .tests import login, make_finding, make_user


class RetestAutoCloseTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.engagement.status = Engagement.Status.AWAITING_REMEDIATION_TEST
        self.engagement.save(update_fields=["status"])
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.finding = make_finding(self.engagement, self.consultant)

    def _log(self, status):
        return retest.log_retest_result(
            self.finding, status=status, notes_ciphertext=None, tested_by=self.consultant,
        )

    def test_fixed_retest_closes_the_finding(self):
        self.assertEqual(self.finding.status, Finding.Status.OPEN)
        self._log(Finding.RetestStatus.FIXED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, Finding.Status.CLOSED)

    def test_not_fixed_retest_reopens_the_finding(self):
        self.finding.status = Finding.Status.CLOSED
        self.finding.save(update_fields=["status"])
        self._log(Finding.RetestStatus.NOT_FIXED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, Finding.Status.OPEN)

    def test_risk_accepted_leaves_status_unchanged(self):
        self.finding.status = Finding.Status.OPEN
        self.finding.save(update_fields=["status"])
        self._log(Finding.RetestStatus.RISK_ACCEPTED)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, Finding.Status.OPEN)

    def test_archived_finding_stays_active_axis_and_still_closes_on_fixed(self):
        # Closed is the open/closed axis; archived is a separate axis. A closed finding
        # is NOT archived, so it remains in reports and the portal.
        self._log(Finding.RetestStatus.FIXED)
        self.finding.refresh_from_db()
        self.assertFalse(self.finding.archived)
        self.assertEqual(self.finding.status, Finding.Status.CLOSED)


class FindingListTabsTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.user = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.user, engagement=self.engagement)
        self.active = make_finding(self.engagement, self.user, title="Active one")
        self.archived = make_finding(self.engagement, self.user, title="Archived one", archived=True)

    def test_active_tab_hides_archived(self):
        login(self.client, self.user)
        resp = self.client.get(reverse("findings:list", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Active one")
        self.assertNotContains(resp, "Archived one")
        self.assertEqual(resp.context["active_count"], 1)
        self.assertEqual(resp.context["archived_count"], 1)

    def test_archived_tab_shows_only_archived(self):
        login(self.client, self.user)
        resp = self.client.get(reverse("findings:list", args=[self.engagement.pk]), {"archived": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Archived one")
        self.assertNotContains(resp, "Active one")
