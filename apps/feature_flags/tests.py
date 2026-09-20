import os

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role

from .models import FeatureFlags

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


class FeatureFlagsModelTests(TestCase):
    def test_all_flags_default_enabled(self):
        flags = FeatureFlags.get_solo()
        self.assertTrue(flags.retest_workflow)
        self.assertTrue(flags.notifications)
        self.assertTrue(flags.recurrence_and_trends)
        self.assertTrue(flags.cvss_calculator)
        self.assertTrue(flags.global_search)
        self.assertTrue(flags.scan_import)

    def test_mfa_required_defaults_on(self):
        self.assertTrue(FeatureFlags.get_solo().mfa_required)

    def test_get_solo_is_a_singleton(self):
        first = FeatureFlags.get_solo()
        first.scan_import = False
        first.save()
        second = FeatureFlags.get_solo()
        self.assertEqual(first.pk, second.pk)
        self.assertFalse(second.scan_import)
        self.assertEqual(FeatureFlags.objects.count(), 1)


class FeatureFlagsViewTests(TestCase):
    def setUp(self):
        self.url = reverse("feature_flags:edit")

    def test_superadmin_can_view_and_toggle(self):
        client = Client()
        login(client, make_user(User.Role.SUPERADMIN))
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 200)

        resp = client.post(self.url, {
            "retest_workflow": "on",
            "notifications": "on",
            "recurrence_and_trends": "on",
            "cvss_calculator": "on",
            "global_search": "on",
            "mfa_required": "on",
        })
        self.assertEqual(resp.status_code, 302)
        flags = FeatureFlags.get_solo()
        self.assertFalse(flags.scan_import)
        self.assertTrue(flags.retest_workflow)
        self.assertTrue(flags.mfa_required)

    def test_superadmin_can_disable_mfa(self):
        client = Client()
        login(client, make_user(User.Role.SUPERADMIN))
        resp = client.post(self.url, {
            "retest_workflow": "on", "notifications": "on", "recurrence_and_trends": "on",
            "cvss_calculator": "on", "global_search": "on", "scan_import": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(FeatureFlags.get_solo().mfa_required)

    def test_team_lead_cannot_view(self):
        client = Client()
        login(client, make_user(User.Role.TEAM_LEAD))
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_consultant_cannot_view(self):
        client = Client()
        login(client, make_user(User.Role.CONSULTANT))
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 403)
