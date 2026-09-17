import json
import os

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import Role
from apps.crypto.services import encrypt_bytes, generate_project_key, get_data_key
from apps.engagements.access import check_engagement_access, visible_engagements
from apps.engagements.models import Engagement
from apps.feature_flags.models import FeatureFlags
from apps.findings.models import Finding

from .access import (
    check_engagement_or_portal_access,
    check_portal_engagement_access,
    record_client_finding_view,
    visible_client_engagements,
    visible_client_findings,
)
from .models import Client, FindingClientView
from .permissions import require_client_manager


def setUpModule():
    from apps.findings.models import ContentSectionDefinition

    ContentSectionDefinition.objects.get_or_create(
        slug="technical-details",
        defaults={"label": "Technical details", "order": 10, "supports_image_upload": True, "is_import_target": True},
    )

User = get_user_model()
TEST_PASSWORD = "a-very-long-test-password-123!"


def make_user(role, **kwargs):
    kwargs.setdefault("username", f"user-{role.lower()}-{os.urandom(4).hex()}")
    kwargs.setdefault("email", f"{kwargs['username']}@example.com")
    role_obj = Role.objects.get(slug=role.lower())
    user = User.objects.create(role=role_obj, auth_type=User.AuthType.LOCAL, **kwargs)
    user.set_password(TEST_PASSWORD)
    user.save()
    if role_obj.requires_mfa:
        TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    return user


def login(http_client, user):
    from django_otp import login as otp_login

    http_client.force_login(user)
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device:
        session = http_client.session
        request = type("R", (), {"session": session, "user": user})()
        otp_login(request, device)
        session.save()
    return user


def make_client_user(client_company, **kwargs):
    user = make_user("client", client=client_company, **kwargs)
    return user


def make_finding(engagement, **kwargs):
    return Finding.objects.create(
        engagement=engagement,
        title=kwargs.pop("title", "Test finding"),
        severity=kwargs.pop("severity", Finding.Severity.HIGH),
        **kwargs,
    )


class EngagementAccessClientRoleTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.other = Client.objects.create(name="Other Corp")
        self.client_user = make_client_user(self.acme)
        self.engagement = Engagement.objects.create(client_name="Acme", client=self.acme)

    def test_client_denied_by_check_engagement_access_even_for_matching_engagement(self):
        decision = check_engagement_access(self.client_user, self.engagement)
        self.assertFalse(decision.granted)
        self.assertEqual(decision.reason, "client_role_never")

    def test_client_denied_for_other_clients_engagement(self):
        other_engagement = Engagement.objects.create(client_name="Other", client=self.other)
        decision = check_engagement_access(self.client_user, other_engagement)
        self.assertFalse(decision.granted)

    def test_client_with_no_client_fk_denied(self):
        orphan = make_user("client")
        decision = check_engagement_access(orphan, self.engagement)
        self.assertFalse(decision.granted)

    def test_archived_engagement_denied_to_client(self):
        self.engagement.archived = True
        self.engagement.save()
        decision = check_engagement_access(self.client_user, self.engagement)
        self.assertFalse(decision.granted)
        self.assertEqual(decision.reason, "archived_superadmin_only")

    def test_visible_engagements_is_staff_only_now(self):
        result = visible_engagements(self.client_user)
        self.assertEqual(list(result), [])


class PortalEngagementAccessTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.other = Client.objects.create(name="Other Corp")
        self.client_user = make_client_user(self.acme)
        self.engagement = Engagement.objects.create(
            client_name="Acme", client=self.acme, client_release_approved=True,
        )

    def test_client_granted_for_matching_engagement(self):
        decision = check_portal_engagement_access(self.client_user, self.engagement)
        self.assertTrue(decision.granted)
        self.assertEqual(decision.reason, "client_portal_match")

    def test_client_denied_when_engagement_not_released(self):
        self.engagement.client_release_approved = False
        self.engagement.save()
        decision = check_portal_engagement_access(self.client_user, self.engagement)
        self.assertFalse(decision.granted)
        self.assertEqual(decision.reason, "not_released_to_client")

    def test_client_denied_for_other_clients_engagement(self):
        other_engagement = Engagement.objects.create(client_name="Other", client=self.other)
        decision = check_portal_engagement_access(self.client_user, other_engagement)
        self.assertFalse(decision.granted)
        self.assertEqual(decision.reason, "client_no_match")

    def test_client_with_no_client_fk_denied(self):
        orphan = make_user("client")
        decision = check_portal_engagement_access(orphan, self.engagement)
        self.assertFalse(decision.granted)

    def test_archived_engagement_denied_to_client_even_if_matching(self):
        self.engagement.archived = True
        self.engagement.save()
        decision = check_portal_engagement_access(self.client_user, self.engagement)
        self.assertFalse(decision.granted)

    def test_inactive_client_company_denied(self):
        self.acme.is_active = False
        self.acme.save()
        decision = check_portal_engagement_access(self.client_user, self.engagement)
        self.assertFalse(decision.granted)
        self.assertEqual(decision.reason, "no_active_client")

    def test_staff_user_denied_by_portal_only_check(self):
        staff = make_user("superadmin")
        decision = check_portal_engagement_access(staff, self.engagement)
        self.assertFalse(decision.granted)

    def test_or_access_grants_matching_client(self):
        decision = check_engagement_or_portal_access(self.client_user, self.engagement)
        self.assertTrue(decision.granted)

    def test_or_access_grants_staff_via_normal_path(self):
        staff = make_user("superadmin")
        decision = check_engagement_or_portal_access(staff, self.engagement)
        self.assertTrue(decision.granted)
        self.assertEqual(decision.reason, "superadmin_bypass")

    def test_or_access_denies_non_matching_client(self):
        other_user = make_client_user(self.other)
        decision = check_engagement_or_portal_access(other_user, self.engagement)
        self.assertFalse(decision.granted)


class InternalViewDeniesClientRoleTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme)
        self.engagement = Engagement.objects.create(client_name="Acme", client=self.acme)
        generate_project_key(self.engagement)

        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()

        self.http = HttpClient()
        self.http.force_login(self.client_user)

    def test_finding_create_denied(self):
        resp = self.http.get(reverse("findings:create", args=[self.engagement.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_finding_edit_denied(self):
        finding = make_finding(self.engagement, workflow_status=Finding.WorkflowStatus.DRAFT)
        resp = self.http.get(reverse("findings:edit", args=[self.engagement.pk, finding.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_check_engagement_access_itself_denies_matching_client(self):
        decision = check_engagement_access(self.client_user, self.engagement)
        self.assertFalse(decision.granted)


class VisibleClientHelpersTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.other = Client.objects.create(name="Other Corp")
        self.client_user = make_client_user(self.acme)
        self.engagement = Engagement.objects.create(
            client_name="Acme", client=self.acme, client_release_approved=True,
        )

    def test_visible_client_engagements_filters_by_client_and_archived(self):
        archived = Engagement.objects.create(client_name="Acme Archived", client=self.acme, archived=True)
        Engagement.objects.create(client_name="Other", client=self.other)

        result = list(visible_client_engagements(self.client_user))
        self.assertIn(self.engagement, result)
        self.assertNotIn(archived, result)
        self.assertEqual(len(result), 1)

    def test_visible_client_engagements_empty_when_client_fk_is_none(self):
        orphan = make_user("client")
        self.assertIsNone(orphan.client_id)
        Engagement.objects.create(client_name="Unlinked", client=None)

        result = list(visible_client_engagements(orphan))
        self.assertEqual(result, [])

    def test_visible_client_engagements_empty_when_client_company_inactive(self):
        self.acme.is_active = False
        self.acme.save()

        result = list(visible_client_engagements(self.client_user))
        self.assertEqual(result, [])

    def test_visible_client_engagements_excludes_not_released(self):
        self.engagement.client_release_approved = False
        self.engagement.save()

        result = list(visible_client_engagements(self.client_user))
        self.assertEqual(result, [])

    def test_visible_client_findings_only_qa_approved_and_not_archived(self):
        approved = make_finding(self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)
        make_finding(self.engagement, workflow_status=Finding.WorkflowStatus.DRAFT)
        make_finding(self.engagement, workflow_status=Finding.WorkflowStatus.REVIEWED)
        archived_but_approved = make_finding(
            self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=True,
        )

        result = list(visible_client_findings(self.engagement))
        self.assertEqual(result, [approved])
        self.assertNotIn(archived_but_approved, result)


class RecordClientFindingViewTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme)
        engagement = Engagement.objects.create(client_name="Acme", client=self.acme)
        self.finding = make_finding(engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)

    def test_first_call_creates_row(self):
        self.assertFalse(FindingClientView.objects.filter(finding=self.finding, client_user=self.client_user).exists())
        record_client_finding_view(self.finding, self.client_user)
        view = FindingClientView.objects.get(finding=self.finding, client_user=self.client_user)
        self.assertIsNotNone(view.first_viewed_at)
        self.assertIsNotNone(view.last_viewed_at)

    def test_second_call_updates_last_viewed_not_first_viewed(self):
        record_client_finding_view(self.finding, self.client_user)
        first = FindingClientView.objects.get(finding=self.finding, client_user=self.client_user)
        original_first_viewed_at = first.first_viewed_at
        original_last_viewed_at = first.last_viewed_at

        record_client_finding_view(self.finding, self.client_user)
        second = FindingClientView.objects.get(finding=self.finding, client_user=self.client_user)

        self.assertEqual(second.first_viewed_at, original_first_viewed_at)
        self.assertGreaterEqual(second.last_viewed_at, original_last_viewed_at)
        self.assertEqual(FindingClientView.objects.filter(finding=self.finding, client_user=self.client_user).count(), 1)


class RequireClientManagerTests(TestCase):
    def test_superadmin_and_team_lead_allowed(self):
        require_client_manager(make_user("superadmin"), "manage clients")
        require_client_manager(make_user("team_lead"), "manage clients")

    def test_other_roles_denied(self):
        acme = Client.objects.create(name="Acme Corp")
        for role, kwargs in [
            ("senior", {}), ("consultant", {}), ("client", {"client": acme}),
        ]:
            with self.subTest(role=role):
                with self.assertRaises(PermissionDenied):
                    require_client_manager(make_user(role, **kwargs), "manage clients")

    def test_delegable_via_clients_manage_permission(self):
        from apps.accounts.models import Permission

        role = Role.objects.create(name=f"Custom {os.urandom(4).hex()}")
        role.slug = Role.unique_slug_from_name(role.name)
        role.save()
        role.permissions.add(Permission.objects.get(codename="clients.manage"))
        user = User.objects.create(username=f"custom-{os.urandom(4).hex()}", role=role, auth_type=User.AuthType.LOCAL)
        require_client_manager(user, "manage clients")


class ClientLoginFeatureFlagTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme, username="portal-user")
        self.http = HttpClient()

    def test_client_login_blocked_when_flag_off(self):
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = False
        flags.save()

        resp = self.http.post(
            reverse("accounts:login"), {"username": self.client_user.username, "password": TEST_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid username or password.")
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_client_login_allowed_when_flag_on(self):
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()

        resp = self.http.post(
            reverse("accounts:login"), {"username": self.client_user.username, "password": TEST_PASSWORD},
        )
        self.assertRedirects(resp, reverse("clients_portal:dashboard"))


class ClientPortalAccessMiddlewareTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme)
        self.http = HttpClient()

    def test_non_allowlisted_url_is_403_when_enabled(self):
        FeatureFlags.get_solo()
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.http.force_login(self.client_user)

        engagement = Engagement.objects.create(client_name="Acme", client=self.acme)
        resp = self.http.get(reverse("engagements:detail", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_allowlisted_url_passes_through_when_enabled(self):
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.http.force_login(self.client_user)

        resp = self.http.get(reverse("accounts:logout"))
        self.assertNotEqual(resp.status_code, 403)

    def test_authenticated_client_session_logged_out_when_flag_off(self):
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.http.force_login(self.client_user)

        flags.client_portal_enabled = False
        flags.save()

        resp = self.http.get(reverse("accounts:dashboard"))
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_non_client_user_unaffected_regardless_of_flag(self):
        consultant = make_user("consultant")
        http = HttpClient()
        http.force_login(consultant)

        for value in (True, False):
            flags = FeatureFlags.get_solo()
            flags.client_portal_enabled = value
            flags.save()
            resp = http.get(reverse("accounts:dashboard"))
            self.assertEqual(resp.status_code, 200)


class ManagementViewsAccessTests(TestCase):
    def setUp(self):
        self.http = HttpClient()

    def test_superadmin_can_reach_client_list_and_create(self):
        login(self.http, make_user("superadmin"))
        self.assertEqual(self.http.get(reverse("clients:list")).status_code, 200)
        self.assertEqual(self.http.get(reverse("clients:create")).status_code, 200)

    def test_team_lead_can_reach_client_list_and_create(self):
        self.http.force_login(make_user("team_lead"))
        self.assertEqual(self.http.get(reverse("clients:list")).status_code, 200)
        self.assertEqual(self.http.get(reverse("clients:create")).status_code, 200)

    def test_other_roles_forbidden(self):
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()

        acme = Client.objects.create(name="Acme Corp")
        for role, kwargs in [("senior", {}), ("consultant", {}), ("client", {"client": acme})]:
            with self.subTest(role=role):
                http = HttpClient()
                http.force_login(make_user(role, **kwargs))
                resp = http.get(reverse("clients:list"))
                self.assertEqual(resp.status_code, 403)


class ClientCompanyCrudTests(TestCase):
    def setUp(self):
        self.http = HttpClient()
        self.manager = make_user("team_lead")
        self.http.force_login(self.manager)

    def test_create_client(self):
        resp = self.http.post(reverse("clients:create"), {"name": "New Co"})
        client = Client.objects.get(name="New Co")
        self.assertRedirects(resp, reverse("clients:detail", args=[client.pk]))
        self.assertTrue(client.is_active)
        self.assertEqual(client.created_by, self.manager)

    def test_edit_client(self):
        company = Client.objects.create(name="Old Name")
        resp = self.http.post(
            reverse("clients:edit", args=[company.pk]), {"name": "New Name", "is_active": False},
        )
        self.assertRedirects(resp, reverse("clients:detail", args=[company.pk]))
        company.refresh_from_db()
        self.assertEqual(company.name, "New Name")
        self.assertFalse(company.is_active)

    def test_detail_shows_engagements_and_portal_users(self):
        company = Client.objects.create(name="Acme Corp")
        engagement = Engagement.objects.create(client_name="Acme", client=company)
        portal_user = make_client_user(company)

        resp = self.http.get(reverse("clients:detail", args=[company.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, engagement.client_name)
        self.assertContains(resp, portal_user.username)


class ClientUserCrudTests(TestCase):
    def setUp(self):
        self.http = HttpClient()
        login(self.http, make_user("superadmin"))
        self.acme = Client.objects.create(name="Acme Corp")

    def test_create_client_user_gets_client_role_and_company(self):
        mail.outbox = []
        resp = self.http.post(
            reverse("clients:user_create", args=[self.acme.pk]),
            {
                "username": "portal-newbie", "email": "newbie@acme.example",
                "first_name": "New", "last_name": "Bie", "client": self.acme.pk,
            },
        )
        user = User.objects.get(username="portal-newbie")
        self.assertRedirects(resp, reverse("clients:user_detail", args=[user.uuid]))
        self.assertEqual(user.role.slug, "client")
        self.assertEqual(user.client, self.acme)
        self.assertEqual(user.auth_type, User.AuthType.LOCAL)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertIn("/invite/", mail.outbox[0].body)

    def test_client_user_detail_404s_for_non_client_user(self):
        consultant = make_user("consultant")
        resp = self.http.get(reverse("clients:user_detail", args=[consultant.uuid]))
        self.assertEqual(resp.status_code, 404)

    def test_client_user_edit_updates_company(self):
        other = Client.objects.create(name="Other Corp")
        target = make_client_user(self.acme)
        resp = self.http.post(
            reverse("clients:user_edit", args=[target.uuid]),
            {"email": target.email, "first_name": "A", "last_name": "B", "client": other.pk},
        )
        self.assertRedirects(resp, reverse("clients:user_detail", args=[target.uuid]))
        target.refresh_from_db()
        self.assertEqual(target.client, other)

    def test_deactivate_and_reactivate(self):
        target = make_client_user(self.acme)
        self.http.post(reverse("clients:user_deactivate", args=[target.uuid]))
        target.refresh_from_db()
        self.assertFalse(target.is_active)

        self.http.post(reverse("clients:user_reactivate", args=[target.uuid]))
        target.refresh_from_db()
        self.assertTrue(target.is_active)

    def test_deactivate_404s_for_non_client_user(self):
        consultant = make_user("consultant")
        resp = self.http.post(reverse("clients:user_deactivate", args=[consultant.uuid]))
        self.assertEqual(resp.status_code, 404)

    def test_send_password_reset(self):
        target = make_client_user(self.acme)
        resp = self.http.post(reverse("clients:user_send_password_reset", args=[target.uuid]))
        self.assertRedirects(resp, reverse("clients:user_detail", args=[target.uuid]))

    def test_clear_mfa(self):
        target = make_client_user(self.acme)
        resp = self.http.post(reverse("clients:user_clear_mfa", args=[target.uuid]))
        self.assertRedirects(resp, reverse("clients:user_detail", args=[target.uuid]))


class EngagementClientFieldFormTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")

    def test_client_field_optional_on_edit_form(self):
        from apps.engagements.forms import EngagementEditForm

        form = EngagementEditForm(data={
            "client_name": "Acme", "reference_number": "REF-1",
            "start_date": "", "end_date": "", "status": "IN_PROGRESS",
        })
        self.assertIn("client", form.fields)
        self.assertFalse(form.fields["client"].required)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["client"])

    def test_client_field_required_on_create_form(self):
        from apps.engagements.forms import EngagementCreateForm

        form = EngagementCreateForm(data={
            "reference_number": "REF-1", "scope": "in scope", "start_date": "", "end_date": "",
        })
        self.assertIn("client", form.fields)
        self.assertTrue(form.fields["client"].required)
        self.assertFalse(form.is_valid())
        self.assertIn("client", form.errors)

    def test_saving_with_client_links_engagement(self):
        from apps.engagements.forms import EngagementCreateForm

        form = EngagementCreateForm(data={
            "client": self.acme.pk, "reference_number": "REF-2",
            "scope": "in scope", "start_date": "", "end_date": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        engagement = form.save(commit=False)
        self.assertEqual(engagement.client, self.acme)


def make_portal_finding(engagement, **kwargs):
    from apps.crypto.services import record_aad
    from apps.findings.models import ContentSectionDefinition, FindingSection

    key = get_data_key(engagement)
    finding = Finding.objects.create(
        engagement=engagement,
        title=kwargs.pop("title", "Test finding"),
        severity=kwargs.pop("severity", Finding.Severity.HIGH),
        **kwargs,
    )
    definition = ContentSectionDefinition.objects.get(slug="technical-details")
    FindingSection.objects.create(
        finding=finding, definition=definition,
        content_ciphertext=encrypt_bytes(
            json.dumps({"type": "doc", "content": []}).encode("utf-8"), key,
            associated_data=record_aad("finding", finding.pk, definition.slug),
        ),
    )
    return finding


class PortalDashboardTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.other = Client.objects.create(name="Other Corp")
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.client_user = make_client_user(self.acme)
        self.http = HttpClient()

    def _url(self):
        return reverse("clients_portal:dashboard")

    def test_client_sees_only_own_companys_non_archived_engagements(self):
        mine = Engagement.objects.create(client_name="Acme project", client=self.acme, client_release_approved=True)
        Engagement.objects.create(client_name="Acme archived", client=self.acme, archived=True, client_release_approved=True)
        Engagement.objects.create(client_name="Other project", client=self.other, client_release_approved=True)

        self.http.force_login(self.client_user)
        resp = self.http.get(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["engagements"]), [mine])

    def test_client_from_other_company_sees_none_of_this_companys_engagements(self):
        Engagement.objects.create(client_name="Acme project", client=self.acme)
        other_user = make_client_user(self.other)

        self.http.force_login(other_user)
        resp = self.http.get(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["engagements"]), [])

    def test_non_client_user_gets_403(self):
        login(self.http, make_user("superadmin"))
        resp = self.http.get(self._url())
        self.assertEqual(resp.status_code, 403)


class PortalEngagementDetailTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.other = Client.objects.create(name="Other Corp")
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.client_user = make_client_user(self.acme)
        self.engagement = Engagement.objects.create(
            client_name="Acme", client=self.acme, client_release_approved=True,
        )
        generate_project_key(self.engagement)
        self.http = HttpClient()

    def _url(self, engagement=None):
        return reverse("clients_portal:engagement_detail", args=[(engagement or self.engagement).pk])

    def test_shows_only_qa_approved_non_archived_findings(self):
        approved = make_portal_finding(self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)
        make_portal_finding(self.engagement, title="Draft one", workflow_status=Finding.WorkflowStatus.DRAFT)
        make_portal_finding(self.engagement, title="Reviewed one", workflow_status=Finding.WorkflowStatus.REVIEWED)
        make_portal_finding(
            self.engagement, title="QA changes requested",
            workflow_status=Finding.WorkflowStatus.QA_CHANGES_REQUESTED,
        )
        make_portal_finding(
            self.engagement, title="Archived approved",
            workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=True,
        )

        self.http.force_login(self.client_user)
        resp = self.http.get(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["findings"]), [approved])

    def test_client_from_other_company_gets_403(self):
        other_user = make_client_user(self.other)
        self.http.force_login(other_user)
        resp = self.http.get(self._url())
        self.assertEqual(resp.status_code, 403)


class PortalFindingDetailTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.client_user = make_client_user(self.acme)
        self.engagement = Engagement.objects.create(
            client_name="Acme", client=self.acme, client_release_approved=True,
        )
        generate_project_key(self.engagement)
        self.http = HttpClient()

    def _url(self, finding):
        return reverse("clients_portal:finding_detail", args=[self.engagement.pk, finding.pk])

    def test_viewing_qa_approved_finding_succeeds_and_records_view(self):
        finding = make_portal_finding(self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)
        self.http.force_login(self.client_user)

        resp = self.http.get(self._url(finding))

        self.assertEqual(resp.status_code, 200)
        view = FindingClientView.objects.get(finding=finding, client_user=self.client_user)
        self.assertIsNotNone(view.last_viewed_at)

    def test_non_approved_finding_404s(self):
        finding = make_portal_finding(self.engagement, workflow_status=Finding.WorkflowStatus.DRAFT)
        self.http.force_login(self.client_user)
        resp = self.http.get(self._url(finding))
        self.assertEqual(resp.status_code, 404)

    def test_archived_finding_404s(self):
        finding = make_portal_finding(
            self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED, archived=True,
        )
        self.http.force_login(self.client_user)
        resp = self.http.get(self._url(finding))
        self.assertEqual(resp.status_code, 404)

    def test_second_visit_updates_without_duplicate_row(self):
        finding = make_portal_finding(self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)
        self.http.force_login(self.client_user)

        self.http.get(self._url(finding))
        first = FindingClientView.objects.get(finding=finding, client_user=self.client_user)

        self.http.get(self._url(finding))
        self.assertEqual(
            FindingClientView.objects.filter(finding=finding, client_user=self.client_user).count(), 1,
        )
        second = FindingClientView.objects.get(finding=finding, client_user=self.client_user)
        self.assertEqual(second.first_viewed_at, first.first_viewed_at)
        self.assertGreaterEqual(second.last_viewed_at, first.last_viewed_at)

    def test_staff_preview_does_not_record_client_view(self):
        finding = make_portal_finding(self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)
        staff = make_user("superadmin")
        login(self.http, staff)

        resp = self.http.get(self._url(finding))

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(FindingClientView.objects.filter(finding=finding).exists())


class ClientLoginRedirectTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme, username="portal-redirect-user")
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.http = HttpClient()

    def test_login_redirects_to_portal_dashboard(self):
        resp = self.http.post(
            reverse("accounts:login"), {"username": self.client_user.username, "password": TEST_PASSWORD},
        )
        self.assertRedirects(resp, reverse("clients_portal:dashboard"))


class ClientPortalMiddlewareRealRoutesTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme)
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.http = HttpClient()
        self.http.force_login(self.client_user)

    def test_dashboard_reachable(self):
        resp = self.http.get(reverse("clients_portal:dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_engagement_and_finding_detail_reachable(self):
        engagement = Engagement.objects.create(client_name="Acme", client=self.acme, client_release_approved=True)
        generate_project_key(engagement)
        finding = make_portal_finding(engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)

        resp = self.http.get(reverse("clients_portal:engagement_detail", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 200)
        resp = self.http.get(reverse("clients_portal:finding_detail", args=[engagement.pk, finding.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_accounts_dashboard_no_longer_allowlisted(self):
        resp = self.http.get(reverse("accounts:dashboard"))
        self.assertEqual(resp.status_code, 403)


class ClientPortal403EscapeHatchTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.client_user = make_client_user(self.acme)
        flags = FeatureFlags.get_solo()
        flags.client_portal_enabled = True
        flags.save()
        self.http = HttpClient()
        self.http.force_login(self.client_user)

    def test_403_escape_hatch_points_to_portal_dashboard_for_client(self):
        resp = self.http.get(reverse("accounts:dashboard"))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, reverse("clients_portal:dashboard"), status_code=403)
        self.assertNotContains(resp, 'href="/"', status_code=403)

        follow_up = self.http.get(reverse("clients_portal:dashboard"))
        self.assertEqual(follow_up.status_code, 200)

    def test_403_escape_hatch_still_plain_root_for_staff(self):
        team_lead = make_user("team_lead")
        http = HttpClient()
        http.force_login(team_lead)
        engagement = Engagement.objects.create(client_name="Acme", client=self.acme, archived=True)

        resp = http.get(reverse("engagements:permanent_delete", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, 'href="/"', status_code=403)


class FindingDetailClientVisibilityPanelTests(TestCase):
    def setUp(self):
        self.acme = Client.objects.create(name="Acme Corp")
        self.engagement = Engagement.objects.create(client_name="Acme", client=self.acme)
        generate_project_key(self.engagement)
        self.http = HttpClient()

    def test_shows_client_view_info_when_present(self):
        finding = make_portal_finding(self.engagement, workflow_status=Finding.WorkflowStatus.QA_APPROVED)
        client_user = make_client_user(self.acme, username="viewer-1")
        record_client_finding_view(finding, client_user)

        login(self.http, make_user("superadmin"))
        resp = self.http.get(reverse("findings:detail", args=[self.engagement.pk, finding.pk]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Client visibility")
        self.assertContains(resp, str(client_user))
