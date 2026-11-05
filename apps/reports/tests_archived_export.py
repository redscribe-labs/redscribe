"""Archive feature (Part C): archived findings must never reach the report export,
even when they are QA-approved. The client portal already excludes them
(see apps/clients/tests.py::test_visible_client_findings_only_qa_approved_and_not_archived)."""
from django.test import TestCase

from apps.accounts.models import User
from apps.crypto.services import generate_project_key
from apps.engagements.models import Engagement
from apps.findings.models import Finding

from .assembly import _select_findings
from .tests import make_finding, make_user


class ReportExcludesArchivedFindingsTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.author = make_user(User.Role.CONSULTANT)
        self.approved = make_finding(
            self.engagement, self.author, title="Approved, active",
            workflow_status=Finding.WorkflowStatus.QA_APPROVED,
        )
        self.archived_approved = make_finding(
            self.engagement, self.author, title="Approved but archived",
            workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=True,
        )

    def test_select_findings_omits_archived_even_when_qa_approved(self):
        result = _select_findings(self.engagement, {})
        self.assertIn(self.approved, result)
        self.assertNotIn(self.archived_approved, result)

    def test_select_findings_omits_archived_when_explicitly_included(self):
        # Even if the saved builder selection names the archived finding's id, it stays out.
        cfg = {"included_ids": [str(self.approved.id), str(self.archived_approved.id)]}
        result = _select_findings(self.engagement, cfg)
        self.assertEqual(result, [self.approved])
