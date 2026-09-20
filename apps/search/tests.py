import os

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.crypto.services import generate_project_key
from apps.engagements.models import Engagement, EngagementMembership
from apps.findings.models import ClassificationTag, Finding

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


class GlobalSearchTests(TestCase):
    def setUp(self):
        self.acme = Engagement.objects.create(client_name="Acme Corp", reference_number="PT-2026-001")
        generate_project_key(self.acme)
        self.globex = Engagement.objects.create(client_name="Globex Inc", reference_number="PT-2026-002")
        generate_project_key(self.globex)

        self.consultant = make_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.consultant, engagement=self.acme)

        self.acme_finding = make_finding(self.acme, self.consultant, title="SQL Injection in login")
        self.globex_finding = make_finding(self.globex, make_user(User.Role.TEAM_LEAD), title="XSS in search box")

    def test_blank_query_shows_prompt_no_results(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"))
        self.assertEqual(list(resp.context["engagements"]), [])
        self.assertEqual(list(resp.context["findings"]), [])

    def test_finds_engagement_by_client_name(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"), {"q": "Acme"})
        self.assertEqual(list(resp.context["engagements"]), [self.acme])

    def test_finds_engagement_by_reference_number(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"), {"q": "PT-2026-001"})
        self.assertEqual(list(resp.context["engagements"]), [self.acme])

    def test_finds_finding_by_title(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"), {"q": "Injection"})
        self.assertEqual(list(resp.context["findings"]), [self.acme_finding])

    def test_finds_finding_by_cve_id(self):
        self.acme_finding.cve_id = "CVE-2024-1234"
        self.acme_finding.save(update_fields=["cve_id"])
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"), {"q": "CVE-2024-1234"})
        self.assertEqual(list(resp.context["findings"]), [self.acme_finding])

    def test_consultant_cannot_see_engagement_or_finding_from_engagement_they_are_not_a_member_of(self):
        client = Client()
        login(client, self.consultant)

        resp = client.get(reverse("search:results"), {"q": "Globex"})
        self.assertEqual(list(resp.context["engagements"]), [])

        resp = client.get(reverse("search:results"), {"q": "XSS"})
        self.assertEqual(list(resp.context["findings"]), [])

    def test_superadmin_sees_everything(self):
        superadmin = make_user(User.Role.SUPERADMIN)
        client = Client()
        login(client, superadmin)

        resp = client.get(reverse("search:results"), {"q": "Corp"})
        self.assertIn(self.acme, resp.context["engagements"])

        resp = client.get(reverse("search:results"), {"q": "XSS"})
        self.assertIn(self.globex_finding, resp.context["findings"])

    def test_result_totals_reflect_full_match_count_not_just_page_slice(self):
        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"), {"q": "Acme"})
        self.assertEqual(resp.context["engagement_total"], 1)

    def test_anonymous_user_redirected_to_login(self):
        client = Client()
        resp = client.get(reverse("search:results"), {"q": "Acme"})
        self.assertEqual(resp.status_code, 302)

    def test_disabled_feature_flag_blocks_search(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.global_search = False
        flags.save()

        client = Client()
        login(client, self.consultant)
        resp = client.get(reverse("search:results"), {"q": "Acme"})
        self.assertEqual(resp.status_code, 403)
