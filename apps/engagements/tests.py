import os

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Permission, Role
from apps.clients.models import Client as ClientCompany
from apps.crypto.services import generate_project_key

from . import lifecycle
from .models import Engagement, EngagementMembership, ScopeChangeRequest
from .permissions import can_create_engagement, is_engagement_manager

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


class PermissionHelperTests(TestCase):
    def test_can_create_engagement_matrix(self):
        self.assertTrue(can_create_engagement(make_user(User.Role.SUPERADMIN)))
        self.assertTrue(can_create_engagement(make_user(User.Role.TEAM_LEAD)))
        self.assertFalse(can_create_engagement(make_user(User.Role.CONSULTANT)))
        self.assertFalse(can_create_engagement(make_user(User.Role.SENIOR)))

    def test_is_engagement_manager_matrix(self):
        engagement = Engagement.objects.create(client_name="Acme")
        archived = Engagement.objects.create(client_name="Old Co", archived=True)

        superadmin = make_user(User.Role.SUPERADMIN)
        team_lead = make_user(User.Role.TEAM_LEAD)
        consultant = make_user(User.Role.CONSULTANT)

        self.assertTrue(is_engagement_manager(superadmin, engagement))
        self.assertTrue(is_engagement_manager(superadmin, archived))
        self.assertTrue(is_engagement_manager(team_lead, engagement))
        self.assertFalse(is_engagement_manager(team_lead, archived))
        self.assertFalse(is_engagement_manager(consultant, engagement))

    def test_is_engagement_manager_requires_engagement_access_not_just_the_permission(self):
        engagement = Engagement.objects.create(client_name="Acme")
        senior = make_user(User.Role.SENIOR)
        senior.role.permissions.add(Permission.objects.get(codename="engagements.manage"))

        self.assertFalse(is_engagement_manager(senior, engagement))

        EngagementMembership.objects.create(user=senior, engagement=engagement)
        self.assertTrue(is_engagement_manager(senior, engagement))


class EngagementCreateViewTests(TestCase):
    def test_team_lead_create_goes_straight_to_in_progress_with_project_key_and_derived_client_name(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        acme = ClientCompany.objects.create(name="Acme Corp")
        client = Client()
        login(client, team_lead)

        resp = client.post(
            reverse("engagements:create"),
            {"client": acme.pk, "scope": "app.acme.com", "start_date": "", "end_date": ""},
        )
        self.assertEqual(resp.status_code, 302)

        engagement = Engagement.objects.get(client=acme)
        self.assertEqual(engagement.client_name, "Acme Corp")
        self.assertEqual(engagement.status, Engagement.Status.IN_PROGRESS)
        self.assertTrue(hasattr(engagement, "project_key"))
        self.assertFalse(
            EngagementMembership.objects.filter(user=team_lead, engagement=engagement).exists()
        )

    def test_senior_cannot_create_engagement(self):
        senior = make_user(User.Role.SENIOR)
        client = Client()
        login(client, senior)

        resp = client.post(reverse("engagements:create"), {"client_name": "Denied Co"})
        self.assertEqual(resp.status_code, 403)

    def test_consultant_cannot_create_engagement(self):
        consultant = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, consultant)

        resp = client.get(reverse("engagements:create"))
        self.assertEqual(resp.status_code, 403)
        resp = client.post(reverse("engagements:create"), {"client_name": "Denied Co"})
        self.assertEqual(resp.status_code, 403)

    def test_end_date_before_start_date_rejected(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        backwards_co = ClientCompany.objects.create(name="Backwards Co")
        client = Client()
        login(client, team_lead)

        resp = client.post(
            reverse("engagements:create"),
            {
                "client": backwards_co.pk, "scope": "",
                "start_date": "2026-06-10", "end_date": "2026-06-01",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context["form"], "end_date", "End date can't be earlier than the start date.")
        self.assertFalse(Engagement.objects.filter(client=backwards_co).exists())

    def test_missing_client_rejected(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        client = Client()
        login(client, team_lead)

        resp = client.post(
            reverse("engagements:create"),
            {"scope": "", "start_date": "", "end_date": ""},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context["form"], "client", "This field is required.")

    def test_client_field_hidden_for_delegated_non_client_manager(self):
        senior = make_user(User.Role.SENIOR)
        senior.role.permissions.add(Permission.objects.get(codename="engagements.create"))

        client = Client()
        login(client, senior)

        resp = client.get(reverse("engagements:create"))
        self.assertEqual(resp.status_code, 403)

        resp = client.post(reverse("engagements:create"), {"scope": "", "start_date": "", "end_date": ""})
        self.assertEqual(resp.status_code, 403)


class EngagementEditViewTests(TestCase):
    def test_end_date_before_start_date_rejected(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        client = Client()
        login(client, team_lead)

        resp = client.post(
            reverse("engagements:edit", args=[engagement.pk]),
            {
                "client_name": "Acme", "reference_number": "", "status": Engagement.Status.IN_PROGRESS,
                "start_date": "2026-06-10", "end_date": "2026-06-01",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context["form"], "end_date", "End date can't be earlier than the start date.")

    def test_client_field_hidden_from_rendered_form_for_delegated_non_client_manager(self):
        senior = make_user(User.Role.SENIOR)
        senior.role.permissions.add(Permission.objects.get(codename="engagements.manage"))
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        EngagementMembership.objects.create(user=senior, engagement=engagement)
        client = Client()
        login(client, senior)

        resp = client.get(reverse("engagements:edit", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("client", resp.context["form"].fields)
        self.assertNotContains(resp, 'name="client"')

    def test_client_field_present_for_team_lead(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        client = Client()
        login(client, team_lead)

        resp = client.get(reverse("engagements:edit", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("client", resp.context["form"].fields)
        self.assertContains(resp, 'name="client"')


class EngagementArchiveViewTests(TestCase):
    def test_team_lead_can_archive_and_only_superadmin_can_unarchive(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        superadmin = make_user(User.Role.SUPERADMIN)
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)

        client = Client()
        login(client, team_lead)
        resp = client.post(reverse("engagements:archive", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        engagement.refresh_from_db()
        self.assertTrue(engagement.archived)
        self.assertIsNotNone(engagement.archived_at)

        resp = client.post(reverse("engagements:unarchive", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 403)

        client2 = Client()
        login(client2, superadmin)
        resp = client2.post(reverse("engagements:unarchive", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        engagement.refresh_from_db()
        self.assertFalse(engagement.archived)
        self.assertIsNone(engagement.archived_at)

    def test_consultant_cannot_archive(self):
        consultant = make_user(User.Role.CONSULTANT)
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        EngagementMembership.objects.create(user=consultant, engagement=engagement)

        client = Client()
        login(client, consultant)
        resp = client.post(reverse("engagements:archive", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Engagement.objects.filter(client_name="Denied Co").exists())

    def test_archiving_last_active_engagement_deactivates_portal_users(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        company = ClientCompany.objects.create(name="Acme Co")
        portal_user = User.objects.create(
            username="acme-portal", role=Role.objects.get(slug="client"), client=company,
        )
        engagement = Engagement.objects.create(client_name="Acme", client=company)
        generate_project_key(engagement)

        client = Client()
        login(client, team_lead)
        resp = client.post(reverse("engagements:archive", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 302)

        portal_user.refresh_from_db()
        self.assertFalse(portal_user.is_active)
        self.assertIsNotNone(portal_user.deactivated_at)

    def test_archiving_one_of_several_engagements_keeps_portal_users_active(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        company = ClientCompany.objects.create(name="Acme Co")
        portal_user = User.objects.create(
            username="acme-portal", role=Role.objects.get(slug="client"), client=company,
        )
        engagement_to_archive = Engagement.objects.create(client_name="Acme", client=company)
        generate_project_key(engagement_to_archive)
        still_active = Engagement.objects.create(client_name="Acme", client=company)
        generate_project_key(still_active)

        client = Client()
        login(client, team_lead)
        resp = client.post(reverse("engagements:archive", args=[engagement_to_archive.pk]))
        self.assertEqual(resp.status_code, 302)

        portal_user.refresh_from_db()
        self.assertTrue(portal_user.is_active)

    def test_archiving_engagement_with_no_linked_client_does_not_error(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        engagement = Engagement.objects.create(client_name="Freelance walk-in")
        generate_project_key(engagement)

        client = Client()
        login(client, team_lead)
        resp = client.post(reverse("engagements:archive", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        engagement.refresh_from_db()
        self.assertTrue(engagement.archived)


class EngagementClientReleaseTests(TestCase):
    def setUp(self):
        self.company = ClientCompany.objects.create(name="Acme Co")
        self.engagement = Engagement.objects.create(client_name="Acme", client=self.company)
        generate_project_key(self.engagement)

    def test_team_lead_can_release_and_revoke(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        client = Client()
        login(client, team_lead)

        resp = client.post(reverse("engagements:release_to_client", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertTrue(self.engagement.client_release_approved)
        self.assertEqual(self.engagement.client_release_approved_by, team_lead)
        self.assertIsNotNone(self.engagement.client_release_approved_at)

        resp = client.post(reverse("engagements:revoke_client_release", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertFalse(self.engagement.client_release_approved)
        self.assertIsNone(self.engagement.client_release_approved_by)
        self.assertIsNone(self.engagement.client_release_approved_at)

    def test_senior_with_qa_permission_and_membership_can_release(self):
        senior = make_user(User.Role.SENIOR)
        self.assertFalse(is_engagement_manager(senior, self.engagement))
        EngagementMembership.objects.create(user=senior, engagement=self.engagement)

        client = Client()
        login(client, senior)
        resp = client.post(reverse("engagements:release_to_client", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertTrue(self.engagement.client_release_approved)

    def test_senior_with_qa_permission_but_no_engagement_access_cannot_release(self):
        senior = make_user(User.Role.SENIOR)
        client = Client()
        login(client, senior)
        resp = client.post(reverse("engagements:release_to_client", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 403)
        self.engagement.refresh_from_db()
        self.assertFalse(self.engagement.client_release_approved)

    def test_delegable_via_engagements_release_to_client_permission(self):
        role = Role.objects.create(name=f"Custom {os.urandom(4).hex()}")
        role.slug = Role.unique_slug_from_name(role.name)
        role.save()
        role.permissions.add(Permission.objects.get(codename="engagements.release_to_client"))
        holder = User.objects.create(
            username=f"holder-{os.urandom(4).hex()}", email=f"holder-{os.urandom(4).hex()}@example.com",
            role=role, auth_type=User.AuthType.LOCAL,
        )
        EngagementMembership.objects.create(user=holder, engagement=self.engagement)

        client = Client()
        login(client, holder)
        resp = client.post(reverse("engagements:release_to_client", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertTrue(self.engagement.client_release_approved)

    def test_consultant_cannot_release(self):
        consultant = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, consultant)
        resp = client.post(reverse("engagements:release_to_client", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 403)
        self.engagement.refresh_from_db()
        self.assertFalse(self.engagement.client_release_approved)


class EngagementPermanentDeleteViewTests(TestCase):
    def _archived_engagement(self):
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        engagement.archived = True
        engagement.save(update_fields=["archived"])
        return engagement

    def test_superadmin_can_permanently_delete_archived_engagement(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        engagement = self._archived_engagement()
        pk = engagement.pk

        client = Client()
        login(client, superadmin)
        resp = client.post(
            reverse("engagements:permanent_delete", args=[pk]),
            {"confirm_client_name": "Acme"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Engagement.objects.filter(pk=pk).exists())

    def test_team_lead_cannot_permanently_delete(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        engagement = self._archived_engagement()

        client = Client()
        login(client, team_lead)
        resp = client.post(
            reverse("engagements:permanent_delete", args=[engagement.pk]),
            {"confirm_client_name": "Acme"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Engagement.objects.filter(pk=engagement.pk).exists())

    def test_cannot_delete_a_non_archived_engagement(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)

        client = Client()
        login(client, superadmin)
        resp = client.post(
            reverse("engagements:permanent_delete", args=[engagement.pk]),
            {"confirm_client_name": "Acme"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Engagement.objects.filter(pk=engagement.pk).exists())

    def test_mismatched_confirmation_text_does_not_delete(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        engagement = self._archived_engagement()

        client = Client()
        login(client, superadmin)
        resp = client.post(
            reverse("engagements:permanent_delete", args=[engagement.pk]),
            {"confirm_client_name": "Wrong Name"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Engagement.objects.filter(pk=engagement.pk).exists())

    def test_delete_cascades_to_findings_and_checklist(self):
        from apps.checklist.models import ChecklistTemplate, ChecklistTemplateItem
        from apps.checklist.services import instantiate_checklist
        from apps.findings.models import Finding

        superadmin = make_user(User.Role.SUPERADMIN)
        template = ChecklistTemplate.objects.create(name="Delete Cascade Test Template", is_default=True)
        ChecklistTemplateItem.objects.create(template=template, category="Cat A", title="Item", order=0)
        engagement = self._archived_engagement()
        finding = Finding.objects.create(
            engagement=engagement, title="Test finding", severity=Finding.Severity.LOW,
        )
        run = instantiate_checklist(engagement)

        client = Client()
        login(client, superadmin)
        client.post(
            reverse("engagements:permanent_delete", args=[engagement.pk]),
            {"confirm_client_name": "Acme"},
        )
        self.assertFalse(Finding.objects.filter(pk=finding.pk).exists())
        self.assertFalse(run.__class__.objects.filter(pk=run.pk).exists())

    def test_get_renders_confirm_page(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        engagement = self._archived_engagement()

        client = Client()
        login(client, superadmin)
        resp = client.get(reverse("engagements:permanent_delete", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Permanently delete")


class EngagementListViewTests(TestCase):
    def setUp(self):
        self.active = Engagement.objects.create(client_name="Active Co")
        generate_project_key(self.active)
        self.archived = Engagement.objects.create(client_name="Archived Co", archived=True)
        generate_project_key(self.archived)
        self.member_only = Engagement.objects.create(client_name="Members Only Co")
        generate_project_key(self.member_only)

    def test_superadmin_sees_everything_including_archived(self):
        user = make_user(User.Role.SUPERADMIN)
        client = Client()
        login(client, user)
        resp = client.get(reverse("engagements:list"))
        names = {e.client_name for e in resp.context["page_obj"].object_list}
        self.assertEqual(names, {"Active Co", "Archived Co", "Members Only Co"})

    def test_team_lead_does_not_see_archived(self):
        user = make_user(User.Role.TEAM_LEAD)
        client = Client()
        login(client, user)
        resp = client.get(reverse("engagements:list"))
        names = {e.client_name for e in resp.context["page_obj"].object_list}
        self.assertEqual(names, {"Active Co", "Members Only Co"})

    def test_consultant_only_sees_memberships(self):
        user = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=user, engagement=self.member_only)
        client = Client()
        login(client, user)
        resp = client.get(reverse("engagements:list"))
        names = {e.client_name for e in resp.context["page_obj"].object_list}
        self.assertEqual(names, {"Members Only Co"})

    def test_search_filters_by_client_name(self):
        user = make_user(User.Role.SUPERADMIN)
        client = Client()
        login(client, user)
        resp = client.get(reverse("engagements:list"), {"q": "Active"})
        names = {e.client_name for e in resp.context["page_obj"].object_list}
        self.assertEqual(names, {"Active Co"})

    def test_pagination_caps_at_ten_per_page(self):
        for i in range(12):
            e = Engagement.objects.create(client_name=f"Bulk Co {i}")
            generate_project_key(e)

        user = make_user(User.Role.SUPERADMIN)
        client = Client()
        login(client, user)
        resp = client.get(reverse("engagements:list"))
        page_obj = resp.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), 10)
        self.assertEqual(page_obj.paginator.num_pages, 2)  # 15 total engagements


class MemberManagementTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)

    def test_team_lead_can_add_member(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:member_add", args=[self.engagement.pk]),
            {"user": self.consultant.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            EngagementMembership.objects.filter(user=self.consultant, engagement=self.engagement).exists()
        )

    def test_non_manager_cannot_add_member(self):
        senior = make_user(User.Role.SENIOR)
        EngagementMembership.objects.create(user=senior, engagement=self.engagement)
        client = Client()
        login(client, senior)
        resp = client.post(
            reverse("engagements:member_add", args=[self.engagement.pk]),
            {"user": self.consultant.pk},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            EngagementMembership.objects.filter(user=self.consultant, engagement=self.engagement).exists()
        )

    def test_client_role_user_cannot_be_added_as_member(self):
        company = ClientCompany.objects.create(name="Acme Co")
        client_user = User.objects.create(
            username="client-portal-user", role=Role.objects.get(slug="client"), client=company,
        )
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:member_add", args=[self.engagement.pk]),
            {"user": client_user.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            EngagementMembership.objects.filter(user=client_user, engagement=self.engagement).exists()
        )

    def test_team_lead_can_remove_member(self):
        membership = EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:member_remove", args=[self.engagement.pk, membership.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(EngagementMembership.objects.filter(pk=membership.pk).exists())

    def test_cannot_manage_members_on_archived_engagement_as_team_lead(self):
        self.engagement.archived = True
        self.engagement.save()
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:member_add", args=[self.engagement.pk]),
            {"user": self.consultant.pk},
        )
        self.assertEqual(resp.status_code, 403)


class ScopeChangeWorkflowTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme", scope="original scope")
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)

    def test_member_can_propose_scope_change(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("engagements:scope_change_create", args=[self.engagement.pk]),
            {"proposed_scope": "app.acme.com/*"},
        )
        self.assertEqual(resp.status_code, 302)
        req = ScopeChangeRequest.objects.get(engagement=self.engagement)
        self.assertEqual(req.status, ScopeChangeRequest.Status.PENDING)
        self.assertEqual(req.requested_by, self.consultant)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.scope, "original scope")

    def test_non_member_cannot_propose_scope_change(self):
        outsider = make_user(User.Role.CONSULTANT)
        client = Client()
        login(client, outsider)
        resp = client.post(
            reverse("engagements:scope_change_create", args=[self.engagement.pk]),
            {"proposed_scope": "app.acme.com/*"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_team_lead_approval_applies_scope_and_records_review(self):
        req = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="app.acme.com/*", requested_by=self.consultant
        )
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:scope_change_approve", args=[self.engagement.pk, req.pk])
        )
        self.assertEqual(resp.status_code, 302)

        self.engagement.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(self.engagement.scope, "app.acme.com/*")
        self.assertEqual(req.status, ScopeChangeRequest.Status.APPROVED)
        self.assertEqual(req.reviewed_by, self.team_lead)
        self.assertIsNotNone(req.reviewed_at)

        detail_resp = client.get(reverse("engagements:detail", args=[self.engagement.pk]))
        self.assertContains(detail_resp, f"Approved by {self.team_lead}")

    def test_consultant_cannot_approve_scope_change(self):
        req = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="app.acme.com/*", requested_by=self.consultant
        )
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("engagements:scope_change_approve", args=[self.engagement.pk, req.pk])
        )
        self.assertEqual(resp.status_code, 403)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.scope, "original scope")

    def test_rejection_does_not_apply_scope(self):
        req = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="app.acme.com/*", requested_by=self.consultant
        )
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:scope_change_reject", args=[self.engagement.pk, req.pk])
        )
        self.assertEqual(resp.status_code, 302)

        self.engagement.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(self.engagement.scope, "original scope")
        self.assertEqual(req.status, ScopeChangeRequest.Status.REJECTED)

    def test_approval_notifies_requester(self):
        from apps.notifications.models import Notification

        req = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="app.acme.com/*", requested_by=self.consultant
        )
        client = Client()
        login(client, self.team_lead)
        client.post(reverse("engagements:scope_change_approve", args=[self.engagement.pk, req.pk]))

        notification = Notification.objects.get(recipient=self.consultant)
        self.assertEqual(notification.verb, Notification.Verb.SCOPE_CHANGE_APPROVED)
        self.assertEqual(notification.engagement, self.engagement)
        self.assertIsNone(notification.finding)
        self.assertEqual(notification.actor, self.team_lead)

    def test_rejection_notifies_requester(self):
        from apps.notifications.models import Notification

        req = ScopeChangeRequest.objects.create(
            engagement=self.engagement, proposed_scope="app.acme.com/*", requested_by=self.consultant
        )
        client = Client()
        login(client, self.team_lead)
        client.post(reverse("engagements:scope_change_reject", args=[self.engagement.pk, req.pk]))

        notification = Notification.objects.get(recipient=self.consultant)
        self.assertEqual(notification.verb, Notification.Verb.SCOPE_CHANGE_REJECTED)
        self.assertEqual(notification.engagement, self.engagement)


class EngagementLifecycleDomainTests(TestCase):
    def test_every_next_states_edge_has_a_label(self):
        for from_status, targets in lifecycle.NEXT_STATES.items():
            for to_status in targets:
                self.assertIn(
                    (from_status, to_status), lifecycle.TRANSITION_LABELS,
                    f"Missing TRANSITION_LABELS entry for {from_status} -> {to_status}",
                )

    def test_closed_can_be_reopened(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.CLOSED)
        self.assertEqual(lifecycle.available_transitions(engagement), [Engagement.Status.IN_PROGRESS])
        team_lead = make_user(User.Role.TEAM_LEAD)
        lifecycle.transition_engagement(engagement, Engagement.Status.IN_PROGRESS, actor=team_lead)
        engagement.refresh_from_db()
        self.assertEqual(engagement.status, Engagement.Status.IN_PROGRESS)

    def test_archived_engagement_has_no_transitions(self):
        engagement = Engagement.objects.create(
            client_name="Acme", status=Engagement.Status.IN_PROGRESS, archived=True,
        )
        self.assertEqual(lifecycle.available_transitions(engagement), [])

    def test_transition_engagement_rejects_invalid_status_string(self):
        engagement = Engagement.objects.create(client_name="Acme")
        team_lead = make_user(User.Role.TEAM_LEAD)
        with self.assertRaises(ValueError):
            lifecycle.transition_engagement(engagement, "NOT_A_REAL_STATUS", actor=team_lead)

    def test_transition_engagement_rejects_non_manager(self):
        engagement = Engagement.objects.create(client_name="Acme")
        consultant = make_user(User.Role.CONSULTANT)
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(engagement, Engagement.Status.IN_REVIEW, actor=consultant)

    def test_engagement_member_can_start_review(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=consultant, engagement=engagement)

        lifecycle.transition_engagement(engagement, Engagement.Status.IN_REVIEW, actor=consultant)
        engagement.refresh_from_db()
        self.assertEqual(engagement.status, Engagement.Status.IN_REVIEW)

    def test_non_member_still_rejected_from_starting_review(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        consultant = make_user(User.Role.CONSULTANT)
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(engagement, Engagement.Status.IN_REVIEW, actor=consultant)

    def test_engagement_member_cannot_do_other_transitions(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_REVIEW)
        consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=consultant, engagement=engagement)
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(engagement, Engagement.Status.QA, actor=consultant)

    def test_transition_engagement_rejects_skipping_a_stage(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        team_lead = make_user(User.Role.TEAM_LEAD)
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(engagement, Engagement.Status.QA, actor=team_lead)

    def test_valid_forward_transition_succeeds(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        team_lead = make_user(User.Role.TEAM_LEAD)
        lifecycle.transition_engagement(engagement, Engagement.Status.IN_REVIEW, actor=team_lead)
        engagement.refresh_from_db()
        self.assertEqual(engagement.status, Engagement.Status.IN_REVIEW)

    def test_kick_back_transition_succeeds(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_REVIEW)
        team_lead = make_user(User.Role.TEAM_LEAD)
        lifecycle.transition_engagement(engagement, Engagement.Status.IN_PROGRESS, actor=team_lead)
        engagement.refresh_from_db()
        self.assertEqual(engagement.status, Engagement.Status.IN_PROGRESS)

    def test_delivered_warns_about_non_qa_approved_findings(self):
        from apps.findings.models import Finding

        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.APPROVED)
        Finding.objects.create(
            engagement=engagement, title="Still in draft", severity=Finding.Severity.LOW,
        )
        warnings = lifecycle.transition_warnings(engagement, Engagement.Status.DELIVERED)
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 finding", warnings[0])

    def test_delivered_no_warning_when_all_findings_qa_approved(self):
        from apps.findings.models import Finding

        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.APPROVED)
        Finding.objects.create(
            engagement=engagement, title="Done", severity=Finding.Severity.LOW,
            workflow_status=Finding.WorkflowStatus.QA_APPROVED,
        )
        self.assertEqual(lifecycle.transition_warnings(engagement, Engagement.Status.DELIVERED), [])

    def test_no_warnings_for_non_delivered_transitions(self):
        engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        self.assertEqual(lifecycle.transition_warnings(engagement, Engagement.Status.IN_REVIEW), [])


class EngagementTransitionViewTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)

    def test_get_is_not_allowed(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.get(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.IN_REVIEW])
        )
        self.assertEqual(resp.status_code, 405)

    def test_detail_page_embeds_transition_options_and_modal(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.get(reverse("engagements:detail", args=[self.engagement.pk]))
        self.assertContains(resp, 'id="transition-options-data"')
        self.assertContains(resp, 'id="transition-modal"')
        self.assertContains(resp, "Move to Review")

    def test_detail_page_shows_move_to_review_for_member_consultant(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("engagements:detail", args=[self.engagement.pk]))
        self.assertContains(resp, "Move to Review")

    def test_post_performs_transition(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.IN_REVIEW])
        )
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.IN_REVIEW)

    def test_engagement_member_can_start_review(self):
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.IN_REVIEW])
        )
        self.assertEqual(resp.status_code, 302)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.IN_REVIEW)

    def test_non_member_gets_403(self):
        client = Client()
        login(client, self.consultant)
        EngagementMembership.objects.filter(user=self.consultant, engagement=self.engagement).delete()
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.IN_REVIEW])
        )
        self.assertEqual(resp.status_code, 403)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.IN_PROGRESS)

    def test_engagement_member_still_rejected_from_other_transitions(self):
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["status"])
        client = Client()
        login(client, self.consultant)
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.QA])
        )
        self.assertEqual(resp.status_code, 403)

    def test_skipping_a_stage_gets_403(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.QA])
        )
        self.assertEqual(resp.status_code, 403)

    def test_garbage_status_gets_400(self):
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, "NOT_A_REAL_STATUS"])
        )
        self.assertEqual(resp.status_code, 400)

    def test_archived_engagement_cannot_transition(self):
        self.engagement.archived = True
        self.engagement.save(update_fields=["archived"])
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:transition", args=[self.engagement.pk, Engagement.Status.IN_REVIEW])
        )
        self.assertEqual(resp.status_code, 403)

    def test_edit_form_no_longer_exposes_status(self):
        from .forms import EngagementEditForm

        self.assertNotIn("status", EngagementEditForm.Meta.fields)


class EngagementDefaultRolesTests(TestCase):
    def setUp(self):
        from apps.findings.models import ClassificationTag, Finding

        self.Finding = Finding
        self.engagement = Engagement.objects.create(client_name="Acme", status=Engagement.Status.IN_PROGRESS)
        generate_project_key(self.engagement)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.engagement)
        self.reviewer = make_user(User.Role.SENIOR)
        self.qa_person = make_user(User.Role.SENIOR)
        self.approver = make_user(User.Role.SENIOR)
        tag = ClassificationTag.objects.first()
        self.finding = Finding.objects.create(
            engagement=self.engagement, title="SQLi", severity=Finding.Severity.HIGH,
            created_by=self.consultant,
        )
        if tag:
            self.finding.classifications.add(tag)

    def test_transition_to_review_auto_assigns_default_reviewer(self):
        self.engagement.default_reviewer = self.reviewer
        self.engagement.save(update_fields=["default_reviewer"])

        lifecycle.transition_engagement(self.engagement, Engagement.Status.IN_REVIEW, actor=self.team_lead)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_reviewer, self.reviewer)

    def test_transition_to_qa_auto_assigns_default_qa_and_notifies_approver(self):
        from apps.notifications.models import Notification

        self.engagement.default_qa = self.qa_person
        self.engagement.default_approver = self.approver
        self.engagement.save(update_fields=["default_qa", "default_approver"])
        self.finding.workflow_status = self.Finding.WorkflowStatus.REVIEWED
        self.finding.save(update_fields=["workflow_status"])
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["status"])

        lifecycle.transition_engagement(self.engagement, Engagement.Status.QA, actor=self.team_lead)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.assigned_qa, self.qa_person)
        notification = Notification.objects.get(recipient=self.approver)
        self.assertEqual(notification.verb, Notification.Verb.APPROVAL_READY)
        self.assertEqual(notification.engagement, self.engagement)

    def test_no_default_configured_is_a_no_op(self):
        lifecycle.transition_engagement(self.engagement, Engagement.Status.IN_REVIEW, actor=self.team_lead)
        self.finding.refresh_from_db()
        self.assertIsNone(self.finding.assigned_reviewer)

    def test_configuring_default_roles_grants_engagement_access(self):
        self.assertFalse(
            EngagementMembership.objects.filter(user=self.approver, engagement=self.engagement).exists()
        )
        client = Client()
        login(client, self.team_lead)
        resp = client.post(
            reverse("engagements:edit", args=[self.engagement.pk]),
            {
                "client_name": "Acme", "reference_number": "", "start_date": "", "end_date": "",
                "default_approver": self.approver.pk,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            EngagementMembership.objects.filter(user=self.approver, engagement=self.engagement).exists()
        )

    def test_default_approver_can_approve(self):
        self.engagement.default_approver = self.approver
        self.engagement.status = Engagement.Status.QA
        self.engagement.save(update_fields=["default_approver", "status"])

        lifecycle.transition_engagement(self.engagement, Engagement.Status.APPROVED, actor=self.approver)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.APPROVED)

    def test_non_approver_member_cannot_approve(self):
        from django.core.exceptions import PermissionDenied

        self.engagement.default_approver = self.approver
        self.engagement.status = Engagement.Status.QA
        self.engagement.save(update_fields=["default_approver", "status"])

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(self.engagement, Engagement.Status.APPROVED, actor=self.consultant)

    def test_default_reviewer_can_move_engagement_to_qa(self):
        self.engagement.default_reviewer = self.reviewer
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["default_reviewer", "status"])

        lifecycle.transition_engagement(self.engagement, Engagement.Status.QA, actor=self.reviewer)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.QA)

    def test_default_reviewer_can_send_engagement_back_to_in_progress(self):
        self.engagement.default_reviewer = self.reviewer
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["default_reviewer", "status"])

        lifecycle.transition_engagement(self.engagement, Engagement.Status.IN_PROGRESS, actor=self.reviewer)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.IN_PROGRESS)

    def test_non_reviewer_member_cannot_move_engagement_from_review(self):
        from django.core.exceptions import PermissionDenied

        self.engagement.default_reviewer = self.reviewer
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["default_reviewer", "status"])

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(self.engagement, Engagement.Status.QA, actor=self.consultant)

    def test_default_qa_can_send_engagement_back_to_review(self):
        self.engagement.default_qa = self.qa_person
        self.engagement.status = Engagement.Status.QA
        self.engagement.save(update_fields=["default_qa", "status"])

        lifecycle.transition_engagement(self.engagement, Engagement.Status.IN_REVIEW, actor=self.qa_person)
        self.engagement.refresh_from_db()
        self.assertEqual(self.engagement.status, Engagement.Status.IN_REVIEW)

    def test_default_qa_cannot_approve(self):
        from django.core.exceptions import PermissionDenied

        self.engagement.default_qa = self.qa_person
        self.engagement.status = Engagement.Status.QA
        self.engagement.save(update_fields=["default_qa", "status"])

        with self.assertRaises(PermissionDenied):
            lifecycle.transition_engagement(self.engagement, Engagement.Status.APPROVED, actor=self.qa_person)

    def test_visible_transition_options_shows_reviewer_both_exits(self):
        self.engagement.default_reviewer = self.reviewer
        self.engagement.status = Engagement.Status.IN_REVIEW
        self.engagement.save(update_fields=["default_reviewer", "status"])

        options = lifecycle.visible_transition_options(self.reviewer, self.engagement)
        to_statuses = {o["to_status"] for o in options}
        self.assertEqual(to_statuses, {str(Engagement.Status.QA), str(Engagement.Status.IN_PROGRESS)})


class VisibleEngagementsArchivedAndClientRoleTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        self.member = make_user("consultant")
        EngagementMembership.objects.create(user=self.member, engagement=self.engagement)

    def test_archived_engagement_drops_out_of_visible_engagements_for_a_former_member(self):
        from .access import visible_engagements

        self.assertIn(self.engagement, visible_engagements(self.member))

        self.engagement.archived = True
        self.engagement.save(update_fields=["archived"])

        self.assertNotIn(self.engagement, visible_engagements(self.member))

    def test_client_role_granted_view_all_still_sees_nothing(self):
        from apps.clients.models import Client as ClientCompany

        from .access import check_engagement_access, visible_engagements

        client_role = Role.objects.get(slug="client")
        client_role.permissions.add(Permission.objects.get(codename="engagements.view_all"))
        company = ClientCompany.objects.create(name="Acme Corp")
        client_user = User.objects.create(
            username=f"client-{os.urandom(4).hex()}", email=f"client-{os.urandom(4).hex()}@example.com",
            role=client_role, auth_type=User.AuthType.LOCAL, client=company,
        )

        decision = check_engagement_access(client_user, self.engagement)
        self.assertFalse(decision.granted)
        self.assertEqual(decision.reason, "client_role_never")
        self.assertEqual(list(visible_engagements(client_user)), [])
