import hashlib
import os
import re
import time
import urllib.error
from unittest.mock import patch

import django_otp
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts import security
from apps.accounts.models import LoginAttempt, Permission, Role
from apps.accounts.permissions_registry import PERMISSIONS
from apps.accounts.password_validators import PwnedPasswordValidator

User = get_user_model()
TEST_PASSWORD = "a-very-long-test-password-123!"
NEW_PASSWORD = "a-different-long-password-456!"


def make_user(role=User.Role.CONSULTANT, **kwargs):
    kwargs.setdefault("username", f"user-{role.lower()}-{os.urandom(4).hex()}")
    kwargs.setdefault("email", f"{kwargs['username']}@example.com")
    auth_type = kwargs.pop("auth_type", User.AuthType.LOCAL)
    user = User.objects.create(role=Role.objects.get(slug=role.lower()), auth_type=auth_type, **kwargs)
    user.set_password(TEST_PASSWORD)
    user.save()
    return user


def login(client: Client, user) -> None:
    from django_otp import login as otp_login
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from .models import UserSession

    client.force_login(user)
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    session = client.session
    request = type("R", (), {"session": session, "user": user})()
    otp_login(request, device)
    session.save()
    # force_login() bypasses the real login views, which are the only place
    # UserSession rows normally get written (see security.invalidate_other_sessions) —
    # record it here too so a test client set up this way is indistinguishable from one
    # that went through a real login, for tests that exercise session revocation.
    UserSession.objects.update_or_create(session_key=session.session_key, defaults={"user": user})


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = Client()
        login(self.client, self.user)

    def test_wrong_old_password_rejected(self):
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": "not-the-real-password",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(TEST_PASSWORD))

    def test_weak_new_password_rejected(self):
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": TEST_PASSWORD,
            "new_password1": "short",
            "new_password2": "short",
        })
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(TEST_PASSWORD))

    def test_successful_change_updates_password_and_keeps_current_session(self):
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": TEST_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertRedirects(resp, reverse("accounts:dashboard"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        resp2 = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(resp2.status_code, 200)

    def test_successful_change_invalidates_other_sessions(self):
        other_client = Client()
        login(other_client, self.user)
        other_session_key = other_client.session.session_key
        self.assertTrue(Session.objects.filter(pk=other_session_key).exists())

        self.client.post(reverse("accounts:password_change"), {
            "old_password": TEST_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })

        self.assertFalse(Session.objects.filter(pk=other_session_key).exists())
        resp = other_client.get(reverse("accounts:dashboard"))
        self.assertNotEqual(resp.status_code, 200)

    def test_successful_change_sends_notification_email(self):
        mail.outbox = []
        self.client.post(reverse("accounts:password_change"), {
            "old_password": TEST_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_oauth_user_cannot_reach_local_password_change(self):
        oauth_user = make_user(auth_type=User.AuthType.OAUTH)
        client = Client()
        login(client, oauth_user)
        resp = client.get(reverse("accounts:password_change"))
        self.assertRedirects(resp, reverse("accounts:dashboard"))


class NotificationPreferencesTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = Client()
        login(self.client, self.user)
        self.url = reverse("accounts:notification_preferences")

    def test_enabled_by_default(self):
        self.assertTrue(self.user.email_notifications_enabled)

    def test_user_can_opt_out(self):
        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_notifications_enabled)

    def test_user_can_opt_back_in(self):
        self.user.email_notifications_enabled = False
        self.user.save(update_fields=["email_notifications_enabled"])
        resp = self.client.post(self.url, {"email_notifications_enabled": "on"})
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_notifications_enabled)

    def test_any_authenticated_user_can_reach_it_regardless_of_role(self):
        for role in [User.Role.SUPERADMIN, User.Role.TEAM_LEAD, User.Role.SENIOR, User.Role.CONSULTANT]:
            client = Client()
            login(client, make_user(role))
            resp = client.get(self.url)
            self.assertEqual(resp.status_code, 200)


class MFAFeatureFlagTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = Client()
        self.client.force_login(self.user)

    def test_mfa_not_required_when_flag_disabled(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.mfa_required = False
        flags.save()

        resp = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_sidebar_renders_for_unverified_local_user_when_mfa_not_required(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.mfa_required = False
        flags.save()

        resp = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(resp, 'id="sidebar"')
        self.assertContains(resp, "sidebar-link-active")

    def test_enabling_flag_blocks_unenrolled_local_user(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.mfa_required = True
        flags.save()

        resp = self.client.get(reverse("accounts:dashboard"))
        self.assertRedirects(resp, reverse("accounts:mfa_enroll"))

    def test_disabling_flag_again_lets_the_user_back_through(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.mfa_required = True
        flags.save()
        self.client.get(reverse("accounts:dashboard"))

        flags.mfa_required = False
        flags.save()
        resp = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_sidebar_hidden_on_mfa_verify_for_role_required_user_even_when_global_flag_off(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from apps.feature_flags.models import FeatureFlags

        from .models import Role

        flags = FeatureFlags.get_solo()
        flags.mfa_required = False
        flags.save()

        superadmin = make_user("superadmin")
        TOTPDevice.objects.create(user=superadmin, name="default", confirmed=True)
        self.assertTrue(Role.objects.get(slug="superadmin").requires_mfa)

        client = Client()
        client.force_login(superadmin)
        resp = client.get(reverse("accounts:dashboard"))
        self.assertRedirects(resp, reverse("accounts:mfa_verify"))

        verify_resp = client.get(reverse("accounts:mfa_verify"))
        self.assertNotContains(verify_resp, 'id="sidebar"')
        self.assertNotContains(verify_resp, "User Management")
        self.assertNotContains(verify_resp, "Superadmin")

    def test_banner_shown_only_when_disabled(self):
        from apps.feature_flags.models import FeatureFlags

        flags = FeatureFlags.get_solo()
        flags.mfa_required = False
        flags.save()

        resp = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(resp, "MFA is currently disabled instance-wide")

        flags.mfa_required = True
        flags.save()
        verified_client = Client()
        login(verified_client, make_user())
        resp = verified_client.get(reverse("accounts:dashboard"))
        self.assertNotContains(resp, "MFA is currently disabled instance-wide")


class ForgotPasswordTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = Client()
        mail.outbox = []

    def _request_reset(self, email):
        return self.client.post(reverse("accounts:password_reset_request"), {"email": email})

    def _extract_reset_url(self):
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"https?://\S+/password/reset/\S+/\S+/", mail.outbox[0].body)
        self.assertIsNotNone(match)
        return match.group(0)

    def test_known_local_email_sends_reset_link(self):
        resp = self._request_reset(self.user.email)
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.username, mail.outbox[0].body)

    def test_unknown_email_gives_same_response_and_sends_nothing(self):
        resp = self._request_reset("nobody@example.com")
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertEqual(len(mail.outbox), 0)

    def test_oauth_email_sends_nothing(self):
        oauth_user = make_user(auth_type=User.AuthType.OAUTH)
        resp = self._request_reset(oauth_user.email)
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow_changes_password_and_logs_in_with_new_one(self):
        self._request_reset(self.user.email)
        reset_url = self._extract_reset_url()

        get_resp = self.client.get(reset_url)
        self.assertEqual(get_resp.status_code, 200)

        confirm_resp = self.client.post(reset_url, {
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        })
        self.assertRedirects(confirm_resp, reverse("accounts:login"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(TEST_PASSWORD))

    def test_reset_link_is_single_use(self):
        self._request_reset(self.user.email)
        reset_url = self._extract_reset_url()

        self.client.post(reset_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

        second_attempt = self.client.post(reset_url, {
            "new_password1": "yet-another-long-password-789!",
            "new_password2": "yet-another-long-password-789!",
        })
        self.assertEqual(second_attempt.status_code, 400)

    def test_tampered_token_rejected(self):
        self._request_reset(self.user.email)
        reset_url = self._extract_reset_url()
        bad_url = reset_url[:-2] + "xx/"
        resp = self.client.get(bad_url)
        self.assertEqual(resp.status_code, 400)

    def test_reset_kills_active_sessions(self):
        other_client = Client()
        login(other_client, self.user)
        other_session_key = other_client.session.session_key

        self._request_reset(self.user.email)
        reset_url = self._extract_reset_url()
        self.client.post(reset_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

        self.assertFalse(Session.objects.filter(pk=other_session_key).exists())

    def test_weak_new_password_rejected_on_reset(self):
        self._request_reset(self.user.email)
        reset_url = self._extract_reset_url()
        resp = self.client.post(reset_url, {"new_password1": "short", "new_password2": "short"})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(TEST_PASSWORD))


class AccountSetupConfirmTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.user.set_unusable_password()
        self.user.save()
        self.client = Client()

    def _setup_url(self):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        token = security.account_setup_token_generator.make_token(self.user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        return reverse("accounts:account_setup_confirm", kwargs={"uidb64": uidb64, "token": token})

    def test_full_setup_flow_sets_password_and_sends_confirmation(self):
        mail.outbox = []
        url = self._setup_url()
        self.assertEqual(self.client.get(url).status_code, 200)

        resp = self.client.post(url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        self.assertRedirects(resp, reverse("accounts:login"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.username, mail.outbox[0].body)

    def test_link_is_single_use(self):
        url = self._setup_url()
        self.client.post(url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

        second_attempt = self.client.post(url, {
            "new_password1": "yet-another-long-password-789!",
            "new_password2": "yet-another-long-password-789!",
        })
        self.assertEqual(second_attempt.status_code, 400)

    def test_tampered_token_rejected(self):
        bad_url = self._setup_url()[:-2] + "xx/"
        self.assertEqual(self.client.get(bad_url).status_code, 400)

    def test_survives_past_the_shorter_password_reset_timeout(self):
        from datetime import datetime, timedelta

        url = self._setup_url()
        future = datetime.now() + timedelta(hours=2)
        with patch.object(security.AccountSetupTokenGenerator, "_now", return_value=future):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_expires_after_24_hours(self):
        from datetime import datetime, timedelta

        url = self._setup_url()
        future = datetime.now() + timedelta(hours=25)
        with patch.object(security.AccountSetupTokenGenerator, "_now", return_value=future):
            self.assertEqual(self.client.get(url).status_code, 400)


class PasswordPolicyTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = Client()
        login(self.client, self.user)

    def test_password_over_max_length_rejected(self):
        too_long = "Aa1!" * 40
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": TEST_PASSWORD,
            "new_password1": too_long,
            "new_password2": too_long,
        })
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(TEST_PASSWORD))

    @patch("apps.accounts.password_validators.urllib.request.urlopen")
    def test_breached_password_rejected(self, mock_urlopen):
        candidate = "correct-horse-battery-staple-1!"
        sha1 = hashlib.sha1(candidate.encode()).hexdigest().upper()
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            f"{sha1[5:]}:12345\r\n".encode()
        )

        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": TEST_PASSWORD,
            "new_password1": candidate,
            "new_password2": candidate,
        })
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(TEST_PASSWORD))


class PwnedPasswordValidatorTests(TestCase):
    def setUp(self):
        self.validator = PwnedPasswordValidator()

    @patch("apps.accounts.password_validators.urllib.request.urlopen")
    def test_password_not_in_range_response_is_allowed(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b"0000000000000000000000000000000000A:5\r\n"
        )
        self.validator.validate("a-genuinely-unique-passphrase!")

    @patch("apps.accounts.password_validators.urllib.request.urlopen")
    def test_zero_count_padding_entry_is_allowed(self, mock_urlopen):
        candidate = "some-password-1!"
        sha1 = hashlib.sha1(candidate.encode()).hexdigest().upper()
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            f"{sha1[5:]}:0\r\n".encode()
        )
        self.validator.validate(candidate)

    @patch("apps.accounts.password_validators.urllib.request.urlopen")
    def test_network_failure_fails_open(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("no network")
        self.validator.validate("literally-anything-1!")

    @override_settings(PWNED_PASSWORD_CHECK_ENABLED=False)
    @patch("apps.accounts.password_validators.urllib.request.urlopen")
    def test_disabled_via_setting_skips_network_call_entirely(self, mock_urlopen):
        self.validator.validate("literally-anything-1!")
        mock_urlopen.assert_not_called()


class LoginFormWhitespaceTests(TestCase):
    def test_password_with_trailing_whitespace_is_not_stripped(self):
        password_with_space = TEST_PASSWORD + " "
        user = make_user()
        user.set_password(password_with_space)
        user.save()

        resp = Client().post(reverse("accounts:login"), {
            "username": user.username,
            "password": password_with_space,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("accounts:dashboard"))


class SuperadminSetupTests(TestCase):
    def _form_data(self, **overrides):
        data = {
            "username": "first-admin",
            "email": "first-admin@example.com",
            "password1": "a-genuinely-strong-passphrase-1!",
            "password2": "a-genuinely-strong-passphrase-1!",
        }
        data.update(overrides)
        return data

    def test_setup_page_reachable_when_no_superadmin_exists(self):
        resp = Client().get(reverse("accounts:setup"))
        self.assertEqual(resp.status_code, 200)

    def test_setup_creates_superadmin_and_logs_them_in(self):
        from apps.feature_flags.models import FeatureFlags
        FeatureFlags.objects.update_or_create(pk=1, defaults={"mfa_required": True})

        client = Client()
        resp = client.post(reverse("accounts:setup"), self._form_data())
        self.assertRedirects(resp, reverse("accounts:dashboard"), target_status_code=302)

        user = User.objects.get(username="first-admin")
        self.assertTrue(user.is_superadmin_role)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.auth_type, User.AuthType.LOCAL)

        dashboard_resp = client.get(reverse("accounts:dashboard"))
        self.assertRedirects(dashboard_resp, reverse("accounts:mfa_enroll"))

    def test_setup_unreachable_once_a_superadmin_exists(self):
        make_user(role=User.Role.SUPERADMIN)
        client = Client()

        get_resp = client.get(reverse("accounts:setup"))
        self.assertRedirects(get_resp, reverse("accounts:login"))

        post_resp = client.post(reverse("accounts:setup"), self._form_data())
        self.assertRedirects(post_resp, reverse("accounts:login"))
        self.assertFalse(User.objects.filter(username="first-admin").exists())

    def test_mismatched_passwords_rejected(self):
        client = Client()
        resp = client.post(
            reverse("accounts:setup"),
            self._form_data(password2="a-completely-different-passphrase-2!"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="first-admin").exists())

    def test_weak_password_rejected(self):
        client = Client()
        resp = client.post(reverse("accounts:setup"), self._form_data(password1="password", password2="password"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="first-admin").exists())

    def test_login_page_links_to_setup_only_when_no_superadmin_exists(self):
        resp = Client().get(reverse("accounts:login"))
        self.assertContains(resp, reverse("accounts:setup"))

        make_user(role=User.Role.SUPERADMIN)
        resp = Client().get(reverse("accounts:login"))
        self.assertNotContains(resp, reverse("accounts:setup"))


class UserManagementRBACTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.target = make_user(role=User.Role.CONSULTANT)

    def _urls(self):
        return [
            reverse("user_management:list"),
            reverse("user_management:create"),
            reverse("user_management:detail", args=[self.target.uuid]),
            reverse("user_management:edit", args=[self.target.uuid]),
        ]

    def test_non_superadmin_roles_get_403(self):
        for role in (User.Role.TEAM_LEAD, User.Role.SENIOR, User.Role.CONSULTANT):
            with self.subTest(role=role):
                user = make_user(role=role)
                client = Client()
                login(client, user)
                for url in self._urls():
                    resp = client.get(url)
                    self.assertEqual(resp.status_code, 403, f"{role} should not reach {url}")

    def test_anonymous_user_redirected_to_login(self):
        for url in self._urls():
            resp = Client().get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn(reverse("accounts:login"), resp.url)

    def test_superadmin_can_reach_every_view(self):
        client = Client()
        login(client, self.superadmin)
        for url in self._urls():
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200)

    def test_mutating_endpoints_blocked_for_non_superadmin(self):
        user = make_user(role=User.Role.TEAM_LEAD)
        client = Client()
        login(client, user)
        mutating_urls = [
            reverse("user_management:deactivate", args=[self.target.uuid]),
            reverse("user_management:reactivate", args=[self.target.uuid]),
            reverse("user_management:send_password_reset", args=[self.target.uuid]),
            reverse("user_management:clear_mfa", args=[self.target.uuid]),
        ]
        for url in mutating_urls:
            resp = client.post(url)
            self.assertEqual(resp.status_code, 403)


class UserManagementListSearchPaginationTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN, username="zz-searcher")
        self.client = Client()
        login(self.client, self.superadmin)

    def test_search_filters_by_username_email_or_name(self):
        make_user(role=User.Role.CONSULTANT, username="findme-user", email="other@example.com")
        make_user(role=User.Role.CONSULTANT, username="other-user", email="findme@example.com")
        make_user(role=User.Role.CONSULTANT, username="unrelated", first_name="Findme")
        make_user(role=User.Role.CONSULTANT, username="no-match-at-all")

        resp = self.client.get(reverse("user_management:list"), {"q": "findme"})
        usernames = {u.username for u in resp.context["page_obj"].object_list}
        self.assertEqual(usernames, {"findme-user", "other-user", "unrelated"})

    def test_pagination_caps_at_ten_per_page(self):
        for i in range(15):
            make_user(role=User.Role.CONSULTANT, username=f"bulk-user-{i}")

        resp = self.client.get(reverse("user_management:list"))
        page_obj = resp.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), 10)
        self.assertEqual(page_obj.paginator.num_pages, 2)

        resp_page2 = self.client.get(reverse("user_management:list"), {"page": 2})
        self.assertEqual(len(resp_page2.context["page_obj"].object_list), 6)


class UserManagementCRUDTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.superadmin)

    def test_create_local_user(self):
        mail.outbox = []
        resp = self.client.post(reverse("user_management:create"), {
            "username": "new-consultant",
            "email": "new-consultant@example.com",
            "first_name": "New",
            "last_name": "Consultant",
            "role": Role.objects.get(slug="consultant").pk,
        })
        user = User.objects.get(username="new-consultant")
        self.assertRedirects(resp, reverse("user_management:detail", args=[user.uuid]))
        self.assertEqual(user.auth_type, User.AuthType.LOCAL)
        self.assertTrue(user.is_consultant_role)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertIn(user.username, mail.outbox[0].body)
        self.assertIn("/invite/", mail.outbox[0].body)

    def test_edit_updates_role_and_profile(self):
        target = make_user(role=User.Role.CONSULTANT, first_name="Old")
        resp = self.client.post(reverse("user_management:edit", args=[target.uuid]), {
            "email": target.email,
            "first_name": "Updated",
            "last_name": "Name",
            "role": Role.objects.get(slug="senior").pk,
        })
        self.assertRedirects(resp, reverse("user_management:detail", args=[target.uuid]))
        target.refresh_from_db()
        self.assertTrue(target.is_senior_role)
        self.assertEqual(target.first_name, "Updated")

    def test_deactivate_and_reactivate(self):
        target = make_user(role=User.Role.CONSULTANT)
        self.client.post(reverse("user_management:deactivate", args=[target.uuid]))
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertIsNotNone(target.deactivated_at)

        self.client.post(reverse("user_management:reactivate", args=[target.uuid]))
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertIsNone(target.deactivated_at)

    def test_deactivate_kills_target_sessions_immediately(self):
        target = make_user(role=User.Role.CONSULTANT)
        target_client = Client()
        login(target_client, target)
        self.assertEqual(target_client.get(reverse("accounts:dashboard")).status_code, 200)

        self.client.post(reverse("user_management:deactivate", args=[target.uuid]))

        self.assertEqual(Session.objects.filter(expire_date__gte=timezone.now()).count(), 1)

    def test_send_password_reset_sends_email_for_local_user_only(self):
        local_target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.LOCAL)
        self.client.post(reverse("user_management:send_password_reset", args=[local_target.uuid]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(local_target.email, mail.outbox[0].to)

        oauth_target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH)
        resp = self.client.post(reverse("user_management:send_password_reset", args=[oauth_target.uuid]))
        self.assertEqual(resp.status_code, 404)

    def test_deactivate_warns_about_orphaned_review_qa_assignments(self):
        from apps.crypto.services import generate_project_key
        from apps.engagements.models import Engagement
        from apps.findings import review
        from apps.findings.models import Finding

        engagement = Engagement.objects.create(client_name="Acme")
        generate_project_key(engagement)
        author = make_user(role=User.Role.CONSULTANT)
        target = make_user(role=User.Role.SENIOR)
        finding = Finding.objects.create(
            engagement=engagement, title="Orphan-prone finding", severity=Finding.Severity.HIGH,
            created_by=author,
        )
        review.assign_reviewer(finding, target, assigned_by=self.superadmin)

        resp = self.client.post(
            reverse("user_management:deactivate", args=[target.uuid]), follow=True
        )
        self.assertContains(resp, "still had 1 finding")
        self.assertContains(resp, "Orphan-prone finding")

        finding.refresh_from_db()
        self.assertEqual(finding.assigned_reviewer, target)

    def test_clear_mfa_deletes_confirmed_device(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        target = make_user(role=User.Role.CONSULTANT)
        TOTPDevice.objects.create(user=target, name="default", confirmed=True)

        self.client.post(reverse("user_management:clear_mfa", args=[target.uuid]))
        self.assertFalse(TOTPDevice.objects.filter(user=target).exists())


class UserManagementUsersManageOnlyCannotEscalateTests(TestCase):
    def setUp(self):
        role = Role.objects.create(name=f"Custom {os.urandom(4).hex()}")
        role.slug = Role.unique_slug_from_name(role.name)
        role.save()
        role.permissions.add(Permission.objects.get(codename="users.manage"))
        username = f"holder-{os.urandom(4).hex()}"
        self.holder = User.objects.create(
            username=username, email=f"{username}@example.com", role=role, auth_type=User.AuthType.LOCAL,
        )
        self.client = Client()
        login(self.client, self.holder)

    def test_cannot_create_a_superadmin(self):
        resp = self.client.post(reverse("user_management:create"), {
            "username": "sneaky-superadmin",
            "email": "sneaky@example.com",
            "role": Role.objects.get(slug="superadmin").pk,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="sneaky-superadmin").exists())

    def test_cannot_edit_someone_into_a_superadmin(self):
        target = make_user(role=User.Role.CONSULTANT)
        resp = self.client.post(reverse("user_management:edit", args=[target.uuid]), {
            "email": target.email,
            "first_name": "", "last_name": "",
            "role": Role.objects.get(slug="superadmin").pk,
        })
        self.assertEqual(resp.status_code, 200)
        target.refresh_from_db()
        self.assertFalse(target.is_superadmin_role)

    def test_cannot_reach_a_client_portal_account(self):
        from apps.clients.models import Client as ClientCompany

        company = ClientCompany.objects.create(name="Acme Corp")
        client_role = Role.objects.get(slug="client")
        username = f"client-{os.urandom(4).hex()}"
        target = User.objects.create(
            username=username, email=f"{username}@example.com", role=client_role,
            auth_type=User.AuthType.LOCAL, client=company,
        )
        for url in (
            reverse("user_management:detail", args=[target.uuid]),
            reverse("user_management:edit", args=[target.uuid]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        for url in (
            reverse("user_management:deactivate", args=[target.uuid]),
            reverse("user_management:reactivate", args=[target.uuid]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 404)


class UserManagementSafetyGuardTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.superadmin)

    def test_cannot_deactivate_own_account(self):
        resp = self.client.post(
            reverse("user_management:deactivate", args=[self.superadmin.uuid]), follow=True
        )
        self.superadmin.refresh_from_db()
        self.assertTrue(self.superadmin.is_active)
        self.assertContains(resp, "can&#x27;t deactivate your own account")

    def test_cannot_deactivate_last_active_superadmin(self):
        other_superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client.post(reverse("user_management:deactivate", args=[other_superadmin.uuid]))
        other_superadmin.refresh_from_db()
        self.assertFalse(other_superadmin.is_active)

        resp = self.client.post(
            reverse("user_management:deactivate", args=[self.superadmin.uuid]), follow=True
        )
        self.superadmin.refresh_from_db()
        self.assertTrue(self.superadmin.is_active)

    def test_cannot_change_own_role(self):
        resp = self.client.post(reverse("user_management:edit", args=[self.superadmin.uuid]), {
            "email": self.superadmin.email,
            "first_name": "",
            "last_name": "",
            "role": Role.objects.get(slug="consultant").pk,
        })
        self.assertRedirects(resp, reverse("user_management:detail", args=[self.superadmin.uuid]))
        self.superadmin.refresh_from_db()
        self.assertTrue(self.superadmin.is_superadmin_role)

    def test_last_active_superadmin_guard_blocks_direct_demotion(self):
        self.assertTrue(security.is_last_active_superadmin(self.superadmin))
        other_superadmin = make_user(role=User.Role.SUPERADMIN)
        self.assertFalse(security.is_last_active_superadmin(self.superadmin))
        self.assertFalse(security.is_last_active_superadmin(other_superadmin))

    def test_can_demote_superadmin_when_another_exists(self):
        other_superadmin = make_user(role=User.Role.SUPERADMIN)
        resp = self.client.post(reverse("user_management:edit", args=[other_superadmin.uuid]), {
            "email": other_superadmin.email,
            "first_name": "",
            "last_name": "",
            "role": Role.objects.get(slug="team_lead").pk,
        })
        self.assertRedirects(resp, reverse("user_management:detail", args=[other_superadmin.uuid]))
        other_superadmin.refresh_from_db()
        self.assertTrue(other_superadmin.is_team_lead_role)


class EmergencyAccountRecoveryCommandTests(TestCase):
    def _run(self, **kwargs):
        from django.core.management import call_command

        args = ["--username", kwargs.pop("username"), "--reason", kwargs.pop("reason", "test incident")]
        if kwargs.pop("clear_mfa", False):
            args.append("--clear-mfa")
        if "operator" in kwargs:
            args += ["--operator", kwargs.pop("operator")]
        with patch("getpass.getpass", side_effect=["a-strong-recovery-pass-1", "a-strong-recovery-pass-1"]):
            call_command("emergency_account_recovery", *args)

    def test_resets_password_for_a_local_account(self):
        user = make_user()
        self._run(username=user.username, operator="oncall-engineer")
        user.refresh_from_db()
        self.assertTrue(user.check_password("a-strong-recovery-pass-1"))

    def test_writes_an_audit_log_entry(self):
        from apps.audit.models import AuditLogEntry

        user = make_user()
        self._run(username=user.username, reason="INC-42", operator="oncall-engineer")

        entry = AuditLogEntry.objects.get(action="emergency_account_recovery")
        self.assertEqual(entry.actor_username, "oncall-engineer")
        self.assertIsNone(entry.actor)
        self.assertIn(user.username, entry.object_ref)
        self.assertIn("INC-42", entry.object_ref)
        self.assertNotEqual(entry.entry_hash, "")

    def test_clear_mfa_flag_also_deletes_the_totp_device(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        user = make_user()
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        self._run(username=user.username, clear_mfa=True)
        self.assertFalse(TOTPDevice.objects.filter(user=user).exists())

    def test_omitting_clear_mfa_leaves_an_existing_device_alone(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        user = make_user()
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        self._run(username=user.username)
        self.assertTrue(TOTPDevice.objects.filter(user=user).exists())

    def test_rejects_a_blank_reason(self):
        from django.core.management.base import CommandError

        user = make_user()
        with self.assertRaises(CommandError):
            self._run(username=user.username, reason="   ")

    def test_rejects_an_oauth_account(self):
        from django.core.management.base import CommandError

        user = make_user()
        user.auth_type = User.AuthType.OAUTH
        user.save(update_fields=["auth_type"])
        with self.assertRaises(CommandError):
            self._run(username=user.username)

    def test_rejects_an_unknown_username(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._run(username="does-not-exist")


class RoleModelTests(TestCase):
    def test_superadmin_role_bypasses_every_permission(self):
        superadmin_role = Role.objects.get(slug="superadmin")
        self.assertTrue(superadmin_role.has_permission("engagements.create"))
        self.assertTrue(superadmin_role.has_permission("this-codename-does-not-exist"))

    def test_role_without_permission_returns_false(self):
        senior_role = Role.objects.get(slug="senior")
        self.assertFalse(senior_role.has_permission("engagements.create"))

    def test_role_with_permission_returns_true(self):
        team_lead_role = Role.objects.get(slug="team_lead")
        self.assertTrue(team_lead_role.has_permission("engagements.create"))

    def test_unique_slug_from_name_dedupes_on_collision(self):
        first = Role.unique_slug_from_name("Pentest Lead")
        Role.objects.create(name="Pentest Lead", slug=first)
        second = Role.unique_slug_from_name("Pentest Lead")
        self.assertNotEqual(first, second)


class DefaultRolePermissionRegressionTests(TestCase):
    def test_team_lead_defaults(self):
        team_lead = make_user(role=User.Role.TEAM_LEAD)
        self.assertTrue(team_lead.has_permission("engagements.create"))
        self.assertTrue(team_lead.has_permission("engagements.manage"))
        self.assertTrue(team_lead.has_permission("engagements.view_all"))
        self.assertTrue(team_lead.has_permission("catalogue.manage"))
        self.assertTrue(team_lead.has_permission("findings.review"))
        self.assertTrue(team_lead.has_permission("findings.review_own"))
        self.assertTrue(team_lead.has_permission("findings.qa"))
        self.assertTrue(team_lead.has_permission("findings.qa_own"))
        self.assertTrue(team_lead.has_permission("checklist_templates.manage"))
        self.assertFalse(team_lead.has_permission("report_settings.manage"))

    def test_senior_defaults(self):
        senior = make_user(role=User.Role.SENIOR)
        self.assertFalse(senior.has_permission("engagements.create"))
        self.assertFalse(senior.has_permission("engagements.manage"))
        self.assertFalse(senior.has_permission("catalogue.manage"))
        self.assertTrue(senior.has_permission("findings.review"))
        self.assertFalse(senior.has_permission("findings.review_own"))
        self.assertTrue(senior.has_permission("findings.qa"))
        self.assertFalse(senior.has_permission("findings.qa_own"))

    def test_consultant_defaults(self):
        consultant = make_user(role=User.Role.CONSULTANT)
        self.assertFalse(consultant.has_permission("engagements.create"))
        self.assertFalse(consultant.has_permission("engagements.manage"))
        self.assertFalse(consultant.has_permission("catalogue.manage"))
        self.assertFalse(consultant.has_permission("findings.review"))
        self.assertFalse(consultant.has_permission("findings.qa"))

    def test_superadmin_bypasses_all(self):
        superadmin = make_user(role=User.Role.SUPERADMIN)
        for codename, _label, _category in PERMISSIONS:
            with self.subTest(codename=codename):
                self.assertTrue(superadmin.has_permission(codename))


class RoleManagementRBACTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.custom_role = Role.objects.create(name="Custom Reviewer")

    def _urls(self):
        return [
            reverse("role_management:list"),
            reverse("role_management:create"),
            reverse("role_management:detail", args=[self.custom_role.pk]),
            reverse("role_management:edit", args=[self.custom_role.pk]),
        ]

    def test_non_superadmin_roles_get_403(self):
        for role in (User.Role.TEAM_LEAD, User.Role.SENIOR, User.Role.CONSULTANT):
            with self.subTest(role=role):
                user = make_user(role=role)
                client = Client()
                login(client, user)
                for url in self._urls():
                    resp = client.get(url)
                    self.assertEqual(resp.status_code, 403, f"{role} should not reach {url}")

    def test_anonymous_user_redirected_to_login(self):
        for url in self._urls():
            resp = Client().get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn(reverse("accounts:login"), resp.url)

    def test_superadmin_can_reach_every_view(self):
        client = Client()
        login(client, self.superadmin)
        for url in self._urls():
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200)

    def test_delete_blocked_for_non_superadmin(self):
        user = make_user(role=User.Role.TEAM_LEAD)
        client = Client()
        login(client, user)
        resp = client.post(reverse("role_management:delete", args=[self.custom_role.pk]))
        self.assertEqual(resp.status_code, 403)


class RoleManagementCRUDTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.superadmin)

    def test_create_role_with_permissions(self):
        resp = self.client.post(reverse("role_management:create"), {
            "name": "Reviewer Only",
            "permissions": ["findings.review", "findings.qa"],
        })
        role = Role.objects.get(name="Reviewer Only")
        self.assertRedirects(resp, reverse("role_management:detail", args=[role.pk]))
        self.assertEqual(role.slug, "reviewer-only")
        self.assertFalse(role.is_builtin)
        self.assertFalse(role.is_superadmin)
        self.assertEqual(
            set(role.permissions.values_list("codename", flat=True)),
            {"findings.review", "findings.qa"},
        )

    def test_create_role_duplicate_name_rejected(self):
        Role.objects.create(name="Auditor")
        resp = self.client.post(reverse("role_management:create"), {"name": "Auditor", "permissions": []})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Role.objects.filter(name="Auditor").count(), 1)

    def test_edit_role_updates_name_and_permissions(self):
        role = Role.objects.create(name="Old Name")
        role.permissions.set(Permission.objects.filter(codename="catalogue.manage"))
        resp = self.client.post(reverse("role_management:edit", args=[role.pk]), {
            "name": "New Name",
            "permissions": ["engagements.create"],
        })
        self.assertRedirects(resp, reverse("role_management:detail", args=[role.pk]))
        role.refresh_from_db()
        self.assertEqual(role.name, "New Name")
        self.assertEqual(set(role.permissions.values_list("codename", flat=True)), {"engagements.create"})

    def test_cannot_edit_superadmin_role(self):
        superadmin_role = Role.objects.get(slug="superadmin")
        resp = self.client.get(reverse("role_management:edit", args=[superadmin_role.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_cannot_delete_builtin_role(self):
        team_lead_role = Role.objects.get(slug="team_lead")
        resp = self.client.post(reverse("role_management:delete", args=[team_lead_role.pk]), follow=True)
        team_lead_role.refresh_from_db()
        self.assertContains(resp, "built-in role")

    def test_cannot_delete_role_still_in_use(self):
        role = Role.objects.create(name="In Use Role")
        user = make_user(role=User.Role.CONSULTANT)
        user.role = role
        user.save(update_fields=["role"])

        resp = self.client.post(reverse("role_management:delete", args=[role.pk]), follow=True)
        self.assertTrue(Role.objects.filter(pk=role.pk).exists())
        self.assertContains(resp, "still have it")

    def test_delete_unused_custom_role(self):
        role = Role.objects.create(name="Unused Role")
        resp = self.client.post(reverse("role_management:delete", args=[role.pk]))
        self.assertRedirects(resp, reverse("role_management:list"))
        self.assertFalse(Role.objects.filter(pk=role.pk).exists())


class RequireSuperadminHelperTests(TestCase):
    def test_raises_for_non_superadmin(self):
        from django.core.exceptions import PermissionDenied

        from .permissions import require_superadmin

        team_lead = make_user(role=User.Role.TEAM_LEAD)
        with self.assertRaises(PermissionDenied) as ctx:
            require_superadmin(team_lead, "do the thing")
        self.assertIn("do the thing", str(ctx.exception))

    def test_raises_for_anonymous(self):
        from django.contrib.auth.models import AnonymousUser
        from django.core.exceptions import PermissionDenied

        from .permissions import require_superadmin

        with self.assertRaises(PermissionDenied):
            require_superadmin(AnonymousUser(), "do the thing")

    def test_passes_for_superadmin(self):
        from .permissions import require_superadmin

        superadmin = make_user(role=User.Role.SUPERADMIN)
        require_superadmin(superadmin, "do the thing")


class AppVersionFooterTests(TestCase):
    def test_authenticated_user_sees_version_in_footer(self):
        from django.conf import settings

        client = Client()
        login(client, make_user(User.Role.SUPERADMIN))
        resp = client.get(reverse("accounts:dashboard"))
        self.assertContains(resp, f"RedScribe v{settings.APP_VERSION}")

    def test_anonymous_visitor_does_not_see_version(self):
        resp = Client().get(reverse("accounts:login"))
        self.assertNotContains(resp, "RedScribe v")


class OAuthLoginSignalTests(TestCase):
    def _login_via(self, user, backend_path):
        from django.contrib.auth import login
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.session = self.client.session
        user.backend = backend_path
        login(request, user, backend=backend_path)

    def test_social_backend_login_records_an_oauth_attempt(self):
        user = make_user(auth_type=User.AuthType.OAUTH)
        self._login_via(user, "allauth.account.auth_backends.AuthenticationBackend")

        attempt = LoginAttempt.objects.get(user=user)
        self.assertEqual(attempt.auth_method, LoginAttempt.AuthMethod.OAUTH)
        self.assertTrue(attempt.successful)

    def test_local_backend_login_is_not_double_recorded(self):
        user = make_user()
        self._login_via(user, "apps.accounts.backends.LockoutAwareModelBackend")

        self.assertFalse(LoginAttempt.objects.filter(user=user).exists())

    def test_oauth_login_revokes_other_sessions(self):
        user = make_user(auth_type=User.AuthType.OAUTH)
        other_client = Client()
        login(other_client, user)
        other_key = other_client.session.session_key
        self.assertTrue(Session.objects.filter(pk=other_key).exists())

        self._login_via(user, "allauth.account.auth_backends.AuthenticationBackend")

        self.assertFalse(Session.objects.filter(pk=other_key).exists())

    def test_oauth_login_revokes_other_sessions_on_a_shared_browser(self):
        # Reproduces Django's login() session.flush() branch: it takes flush() (which
        # clears session_key back to None) instead of cycle_key() whenever the browser's
        # existing session already belongs to a DIFFERENT authenticated user — session_key
        # is genuinely None at the exact point the user_logged_in signal fires in that
        # case. A prior version of the signal handler's guard silently skipped
        # invalidation whenever session_key was falsy, defeating enforcement for this
        # exact shared/kiosk-browser scenario.
        user = make_user(auth_type=User.AuthType.OAUTH)
        other_client = Client()
        login(other_client, user)
        other_key = other_client.session.session_key
        self.assertTrue(Session.objects.filter(pk=other_key).exists())

        someone_else = make_user()
        self.client.force_login(someone_else)  # self.client.session now holds a DIFFERENT user's SESSION_KEY

        self._login_via(user, "allauth.account.auth_backends.AuthenticationBackend")

        self.assertFalse(Session.objects.filter(pk=other_key).exists())


class SingleSessionEnforcementTests(TestCase):
    """A user should only ever have one active session — a fresh successful login must
    revoke whatever session(s) they were already logged in with elsewhere."""

    def setUp(self):
        self.user = make_user()

    def _other_active_session_key(self):
        # Plain force_login (no OTP device involved) — keeps this decoupled from whatever
        # TOTPDevice state an individual test sets up for the *new* login it's exercising.
        from .models import UserSession

        other_client = Client()
        other_client.force_login(self.user)
        other_key = other_client.session.session_key
        self.assertTrue(Session.objects.filter(pk=other_key).exists())
        # force_login() bypasses the real login views that normally record this — see
        # the module-level login() helper's comment above for why this is needed.
        UserSession.objects.update_or_create(session_key=other_key, defaults={"user": self.user})
        return other_key

    def _valid_totp(self, device):
        from django_otp.oath import totp as totp_token

        return str(totp_token(device.bin_key, device.step, device.t0, device.digits, device.drift)).zfill(
            device.digits
        )

    def test_plain_login_revokes_other_sessions(self):
        other_key = self._other_active_session_key()

        resp = Client().post(reverse("accounts:login"), {
            "username": self.user.username, "password": TEST_PASSWORD,
        })
        self.assertEqual(resp.status_code, 302)

        self.assertFalse(Session.objects.filter(pk=other_key).exists())

    def test_password_step_alone_does_not_revoke_when_mfa_still_pending(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from apps.feature_flags.models import FeatureFlags

        FeatureFlags.objects.update_or_create(pk=1, defaults={"mfa_required": True})
        TOTPDevice.objects.create(user=self.user, name="default", confirmed=True)

        other_key = self._other_active_session_key()

        client = Client()
        resp = client.post(reverse("accounts:login"), {
            "username": self.user.username, "password": TEST_PASSWORD,
        })
        self.assertRedirects(resp, reverse("accounts:dashboard"), target_status_code=302)

        # Knowing the password isn't enough on its own to kick out the real session —
        # otherwise anyone with a leaked password (but no MFA code) could disrupt it
        # without ever completing login themselves.
        self.assertTrue(Session.objects.filter(pk=other_key).exists())

    def test_mfa_verify_step_revokes_other_sessions(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from apps.feature_flags.models import FeatureFlags

        FeatureFlags.objects.update_or_create(pk=1, defaults={"mfa_required": True})
        device = TOTPDevice.objects.create(user=self.user, name="default", confirmed=True)

        other_key = self._other_active_session_key()

        client = Client()
        client.post(reverse("accounts:login"), {"username": self.user.username, "password": TEST_PASSWORD})
        resp = client.post(reverse("accounts:mfa_verify"), {"token": self._valid_totp(device)})
        self.assertRedirects(resp, reverse("accounts:dashboard"))

        self.assertFalse(Session.objects.filter(pk=other_key).exists())

    def test_forced_first_time_enrollment_revokes_other_sessions(self):
        from apps.feature_flags.models import FeatureFlags

        FeatureFlags.objects.update_or_create(pk=1, defaults={"mfa_required": True})

        other_key = self._other_active_session_key()

        client = Client()
        client.post(reverse("accounts:login"), {"username": self.user.username, "password": TEST_PASSWORD})
        enroll_resp = client.get(reverse("accounts:mfa_enroll"))
        self.assertEqual(enroll_resp.status_code, 200)
        device = self.user.totpdevice_set.get(confirmed=False)

        resp = client.post(reverse("accounts:mfa_enroll"), {"token": self._valid_totp(device)})
        self.assertRedirects(resp, reverse("accounts:dashboard"))

        self.assertFalse(Session.objects.filter(pk=other_key).exists())

    def test_voluntary_mfa_enrollment_mid_session_does_not_revoke_other_sessions(self):
        # MFA isn't required for this user (no feature flag, no role requirement), so a
        # plain non-OTP session can already use the whole app — this simulates them
        # opting into MFA later via the "Enable 2FA" sidebar link, not completing a login.
        other_key = self._other_active_session_key()

        client = Client()
        client.force_login(self.user)
        current_key = client.session.session_key

        # Two legitimate sessions coexist until one of them actually re-logs in.
        self.assertTrue(Session.objects.filter(pk=other_key).exists())

        enroll_resp = client.get(reverse("accounts:mfa_enroll"))
        self.assertEqual(enroll_resp.status_code, 200)
        device = self.user.totpdevice_set.get(confirmed=False)

        resp = client.post(reverse("accounts:mfa_enroll"), {"token": self._valid_totp(device)})
        self.assertRedirects(resp, reverse("accounts:dashboard"))

        self.assertTrue(Session.objects.filter(pk=other_key).exists())
        self.assertTrue(Session.objects.filter(pk=current_key).exists())


class IdleTimeoutMiddlewareTests(TestCase):
    def setUp(self):
        self.user = make_user(User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.user)
        self.dashboard_url = reverse("accounts:dashboard")

    def _set_last_activity(self, seconds_ago):
        from apps.accounts.middleware import _IDLE_SESSION_KEY

        session = self.client.session
        session[_IDLE_SESSION_KEY] = time.time() - seconds_ago
        session.save()

    def test_recent_activity_stays_logged_in(self):
        self._set_last_activity(5)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)

    @override_settings(SESSION_IDLE_TIMEOUT_SECONDS=60)
    def test_idle_beyond_timeout_logs_out_and_redirects(self):
        self._set_last_activity(120)
        resp = self.client.get(self.dashboard_url)
        self.assertRedirects(resp, reverse("accounts:login"))

        resp2 = self.client.get(self.dashboard_url)
        self.assertEqual(resp2.status_code, 302)

    def test_first_request_after_login_has_no_prior_activity_to_compare(self):
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)

    @override_settings(SESSION_IDLE_TIMEOUT_SECONDS=60)
    def test_stale_session_visiting_a_real_page_ends_up_at_login(self):
        self._set_last_activity(120)
        resp = self.client.get(self.dashboard_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "accounts/login.html")

    def test_anonymous_request_is_unaffected(self):
        resp = Client().get(self.dashboard_url)
        self.assertEqual(resp.status_code, 302)

    @override_settings(SESSION_IDLE_TIMEOUT_SECONDS=60)
    def test_last_activity_in_the_future_forces_logout(self):
        self._set_last_activity(-3600)
        resp = self.client.get(self.dashboard_url)
        self.assertRedirects(resp, reverse("accounts:login"))


@override_settings(LOCKOUT_THRESHOLD=3, LOCKOUT_DURATION_SECONDS=86400)
class LockoutAlertTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(User.Role.SUPERADMIN, email="admin@example.com")

    def test_alert_fires_exactly_at_threshold(self):
        for _ in range(2):
            security.record_attempt(username="nosuchuser", user=None, successful=False, ip_address="1.2.3.4")
            security.maybe_alert_lockout(username="nosuchuser", is_superadmin=False, ip_address="1.2.3.4")
        self.assertEqual(len(mail.outbox), 0)

        security.record_attempt(username="nosuchuser", user=None, successful=False, ip_address="1.2.3.4")
        security.maybe_alert_lockout(username="nosuchuser", is_superadmin=False, ip_address="1.2.3.4")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("nosuchuser", mail.outbox[0].subject)
        self.assertIn(self.superadmin.email, mail.outbox[0].to)

    def test_alert_does_not_refire_past_the_threshold(self):
        for _ in range(3):
            security.record_attempt(username="nosuchuser", user=None, successful=False, ip_address="1.2.3.4")
            security.maybe_alert_lockout(username="nosuchuser", is_superadmin=False, ip_address="1.2.3.4")
        self.assertEqual(len(mail.outbox), 1)

        security.record_attempt(username="nosuchuser", user=None, successful=False, ip_address="1.2.3.4")
        security.maybe_alert_lockout(username="nosuchuser", is_superadmin=False, ip_address="1.2.3.4")
        self.assertEqual(len(mail.outbox), 1)

    def test_no_active_superadmin_recipients_does_not_crash(self):
        self.superadmin.is_active = False
        self.superadmin.save()

        for _ in range(3):
            security.record_attempt(username="nosuchuser", user=None, successful=False, ip_address="1.2.3.4")
            security.maybe_alert_lockout(username="nosuchuser", is_superadmin=False, ip_address="1.2.3.4")

        self.assertEqual(len(mail.outbox), 0)

    def test_end_to_end_via_authenticate_backend(self):
        from django.contrib.auth import authenticate

        target = make_user(User.Role.CONSULTANT, username="target-user")
        for _ in range(3):
            authenticate(username="target-user", password="definitely-wrong")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("target-user", mail.outbox[0].subject)


@override_settings(LOCKOUT_THRESHOLD=3, LOCKOUT_DURATION_SECONDS=86400)
class LoginLockoutStatusCodeTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:login")
        make_user(User.Role.CONSULTANT, username="lockout-target")

    def test_ordinary_invalid_login_is_200(self):
        resp = Client().post(self.url, {"username": "lockout-target", "password": "wrong-once"})
        self.assertEqual(resp.status_code, 200)

    def test_crossing_the_threshold_returns_429_with_retry_after(self):
        client = Client()
        for _ in range(3):
            resp = client.post(self.url, {"username": "lockout-target", "password": "wrong"})
            self.assertEqual(resp.status_code, 200)

        resp = client.post(self.url, {"username": "lockout-target", "password": "wrong"})
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp["Retry-After"], "86400")
        self.assertContains(resp, "temporarily locked", status_code=429)


@override_settings(MFA_THROTTLE_MAX_ATTEMPTS=5, MFA_THROTTLE_WINDOW_SECONDS=30)
class MFAVerifyThrottleTests(TestCase):
    def setUp(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        self.user = make_user()
        TOTPDevice.objects.create(user=self.user, name="default", confirmed=True)
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse("accounts:mfa_verify")

    def test_ordinary_wrong_code_is_200(self):
        resp = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "didn&#x27;t match")

    def test_sixth_attempt_within_window_is_throttled(self):
        for _ in range(5):
            resp = self.client.post(self.url, {"token": "000000"})
            self.assertEqual(resp.status_code, 200)

        resp = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, "Too many attempts", status_code=429)

    def test_throttle_blocks_even_a_correct_code(self):
        from django_otp.oath import totp as totp_token

        device = self.user.totpdevice_set.get()
        valid_token = str(totp_token(device.bin_key, device.step, device.t0, device.digits, device.drift)).zfill(
            device.digits
        )

        for _ in range(5):
            self.client.post(self.url, {"token": "000000"})

        resp = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(resp.status_code, 429)
        self.assertNotIn(django_otp.DEVICE_ID_SESSION_KEY, self.client.session)

    def test_throttle_is_per_account(self):
        other = make_user()
        from django_otp.plugins.otp_totp.models import TOTPDevice

        TOTPDevice.objects.create(user=other, name="default", confirmed=True)
        other_client = Client()
        other_client.force_login(other)

        for _ in range(5):
            self.client.post(self.url, {"token": "000000"})
        self.client.post(self.url, {"token": "000000"})

        resp = other_client.post(reverse("accounts:mfa_verify"), {"token": "000000"})
        self.assertEqual(resp.status_code, 200)


class UserManagementFormRoleChoicesTests(TestCase):
    def test_create_form_excludes_client_role(self):
        from .forms import LocalUserCreateForm

        form = LocalUserCreateForm(requesting_user=make_user(role=User.Role.SUPERADMIN))
        slugs = set(form.fields["role"].queryset.values_list("slug", flat=True))
        self.assertNotIn("client", slugs)
        self.assertIn("superadmin", slugs)

    def test_edit_form_excludes_client_role(self):
        from .forms import LocalUserEditForm

        form = LocalUserEditForm(requesting_user=make_user(role=User.Role.SUPERADMIN))
        slugs = set(form.fields["role"].queryset.values_list("slug", flat=True))
        self.assertNotIn("client", slugs)
        self.assertIn("superadmin", slugs)

    def test_non_superadmin_requester_cannot_choose_superadmin_role(self):
        from .forms import LocalUserCreateForm, LocalUserEditForm

        for role in (User.Role.TEAM_LEAD, User.Role.SENIOR, User.Role.CONSULTANT):
            with self.subTest(role=role):
                requester = make_user(role=role)
                create_slugs = set(
                    LocalUserCreateForm(requesting_user=requester).fields["role"].queryset.values_list("slug", flat=True)
                )
                edit_slugs = set(
                    LocalUserEditForm(requesting_user=requester).fields["role"].queryset.values_list("slug", flat=True)
                )
                self.assertNotIn("superadmin", create_slugs)
                self.assertNotIn("superadmin", edit_slugs)

    def test_no_requesting_user_defaults_to_excluding_superadmin(self):
        from .forms import LocalUserCreateForm

        form = LocalUserCreateForm()
        slugs = set(form.fields["role"].queryset.values_list("slug", flat=True))
        self.assertNotIn("superadmin", slugs)


def _make_role_with_permissions(*codenames):
    name = f"Custom {os.urandom(4).hex()}"
    role = Role.objects.create(name=name, slug=Role.unique_slug_from_name(name))
    role.permissions.set(Permission.objects.filter(codename__in=codenames))
    return role


class GranularAdminPermissionDelegationTests(TestCase):
    def _user_with(self, *codenames):
        role = _make_role_with_permissions(*codenames)
        return make_user(role=role.slug)

    def test_users_manage_reaches_user_management_only(self):
        user = self._user_with("users.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("user_management:list")).status_code, 200)
        self.assertEqual(client.get(reverse("role_management:list")).status_code, 403)

    def test_roles_manage_reaches_role_management_only(self):
        user = self._user_with("roles.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("role_management:list")).status_code, 200)
        self.assertEqual(client.get(reverse("user_management:list")).status_code, 403)

    def test_feature_flags_manage_reaches_feature_flags_only(self):
        user = self._user_with("feature_flags.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("feature_flags:edit")).status_code, 200)
        self.assertEqual(client.get(reverse("licensing:edit")).status_code, 403)

    def test_licensing_manage_reaches_licensing_only(self):
        user = self._user_with("licensing.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("licensing:edit")).status_code, 200)
        self.assertEqual(client.get(reverse("feature_flags:edit")).status_code, 403)

    def test_audit_log_manage_reaches_audit_log_only(self):
        user = self._user_with("audit_log.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("audit:list")).status_code, 200)
        self.assertEqual(client.get(reverse("licensing:edit")).status_code, 403)

    def test_field_visibility_manage_reaches_field_visibility_only(self):
        user = self._user_with("field_visibility.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("field_visibility:edit")).status_code, 200)
        self.assertEqual(client.get(reverse("audit:list")).status_code, 403)

    def test_branding_manage_reaches_branding_only(self):
        user = self._user_with("branding.manage")
        client = Client()
        login(client, user)
        self.assertEqual(client.get(reverse("branding:edit")).status_code, 200)
        self.assertEqual(client.get(reverse("field_visibility:edit")).status_code, 403)

    def test_no_permission_reaches_none_of_them(self):
        user = self._user_with()
        client = Client()
        login(client, user)
        for url_name in (
            "user_management:list", "role_management:list", "feature_flags:edit",
            "licensing:edit", "audit:list", "field_visibility:edit", "branding:edit",
        ):
            with self.subTest(url_name=url_name):
                self.assertEqual(client.get(reverse(url_name)).status_code, 403)


def _sociallogin(email, provider="google", uid=None):
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount, SocialLogin

    login_user = User(email=email)
    account = SocialAccount(provider=provider, uid=uid or f"uid-{os.urandom(4).hex()}")
    email_address = EmailAddress(email=email, verified=True, primary=True)
    return SocialLogin(user=login_user, account=account, email_addresses=[email_address])


class SingleProviderSocialAdapterInviteTests(TestCase):
    """Unit tests for the adapter's pre_social_login invite-claiming logic — built directly
    against allauth's SocialLogin/SocialAccount, since exercising the real OAuth dance would
    require mocking the provider's token exchange."""

    def _request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return request

    @override_settings(OAUTH_PROVIDER="google")
    def test_claims_pending_invite_on_matching_email(self):
        from allauth.socialaccount.models import SocialAccount

        from .adapters import SingleProviderSocialAdapter

        pending = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH, email="invited@example.com")
        pending.oauth_invite_pending = True
        pending.save(update_fields=["oauth_invite_pending"])

        # allauth's connect() unconditionally resolves the provider by name to build an
        # "account connected" notification-email context, which needs a real provider app
        # configured — irrelevant to what's under test here (this environment has no OAuth
        # provider actually configured), so it's stubbed out.
        with patch.object(SocialAccount, "get_provider", return_value=None):
            SingleProviderSocialAdapter().pre_social_login(self._request(), _sociallogin("invited@example.com"))

        pending.refresh_from_db()
        self.assertFalse(pending.oauth_invite_pending)
        self.assertTrue(SocialAccount.objects.filter(user=pending, provider="google").exists())

        from allauth.account.models import EmailAddress

        email_address = EmailAddress.objects.get(user=pending, email__iexact="invited@example.com")
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

    @override_settings(OAUTH_PROVIDER="google")
    def test_claims_pending_invite_case_insensitively(self):
        from allauth.socialaccount.models import SocialAccount

        pending = make_user(
            role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH, email="Invited@Example.com",
        )
        pending.oauth_invite_pending = True
        pending.save(update_fields=["oauth_invite_pending"])

        from .adapters import SingleProviderSocialAdapter

        with patch.object(SocialAccount, "get_provider", return_value=None):
            SingleProviderSocialAdapter().pre_social_login(self._request(), _sociallogin("invited@example.com"))

        pending.refresh_from_db()
        self.assertFalse(pending.oauth_invite_pending)

    @override_settings(OAUTH_PROVIDER="google")
    def test_no_user_created_when_no_pending_invite_matches(self):
        from .adapters import SingleProviderSocialAdapter

        before = User.objects.count()
        SingleProviderSocialAdapter().pre_social_login(self._request(), _sociallogin("nobody@example.com"))
        self.assertEqual(User.objects.count(), before)

    @override_settings(OAUTH_PROVIDER="google")
    def test_rejects_login_when_matched_target_is_superadmin(self):
        from allauth.core.exceptions import ImmediateHttpResponse
        from allauth.socialaccount.models import SocialAccount

        from .adapters import SingleProviderSocialAdapter

        pending = make_user(role=User.Role.SUPERADMIN, auth_type=User.AuthType.OAUTH, email="admin@example.com")
        pending.oauth_invite_pending = True
        pending.save(update_fields=["oauth_invite_pending"])

        with self.assertRaises(ImmediateHttpResponse):
            SingleProviderSocialAdapter().pre_social_login(self._request(), _sociallogin("admin@example.com"))

        pending.refresh_from_db()
        self.assertTrue(pending.oauth_invite_pending)
        self.assertFalse(SocialAccount.objects.filter(user=pending).exists())

        from allauth.account.models import EmailAddress

        self.assertFalse(EmailAddress.objects.filter(user=pending).exists())

    def test_existing_linked_account_is_left_alone(self):
        from .adapters import SingleProviderSocialAdapter

        user = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH, email="already@example.com")
        sociallogin = _sociallogin("already@example.com")
        sociallogin.user = user  # already a saved row -> is_existing is True

        # Should return quietly (ordinary repeat login) rather than touching oauth_invite_pending.
        SingleProviderSocialAdapter().pre_social_login(self._request(), sociallogin)
        user.refresh_from_db()
        self.assertFalse(user.oauth_invite_pending)

    def test_heals_an_account_left_with_an_unverified_email_by_a_past_login(self):
        # Simulates an account that claimed its invite before _mark_email_verified
        # existed (or any other way it ended up with no verified EmailAddress) — the
        # very next login should self-heal it, the same way UserSession rows do.
        from allauth.account.models import EmailAddress

        from .adapters import SingleProviderSocialAdapter

        user = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH, email="already@example.com")
        EmailAddress.objects.create(user=user, email="already@example.com", verified=False, primary=False)
        sociallogin = _sociallogin("already@example.com")
        sociallogin.user = user

        SingleProviderSocialAdapter().pre_social_login(self._request(), sociallogin)

        email_address = EmailAddress.objects.get(user=user, email__iexact="already@example.com")
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

    def test_does_not_crash_when_user_already_has_a_different_primary_email(self):
        # Regression test: reproduces a staging 500 (psycopg.errors.UniqueViolation on
        # "unique_primary_email") — happened because a prior version of
        # _mark_email_verified created the new primary row *before* clearing the old
        # one, which Postgres's unique constraint rejects immediately since a user can
        # only have one primary=True EmailAddress at a time.
        from allauth.account.models import EmailAddress

        from .adapters import SingleProviderSocialAdapter

        user = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH, email="new@example.com")
        EmailAddress.objects.create(user=user, email="old@example.com", verified=True, primary=True)
        sociallogin = _sociallogin("new@example.com")
        sociallogin.user = user

        SingleProviderSocialAdapter().pre_social_login(self._request(), sociallogin)

        new_address = EmailAddress.objects.get(user=user, email__iexact="new@example.com")
        self.assertTrue(new_address.verified)
        self.assertTrue(new_address.primary)
        old_address = EmailAddress.objects.get(user=user, email__iexact="old@example.com")
        self.assertFalse(old_address.primary)


class LocalUserCreateFormOAuthInviteTests(TestCase):
    def setUp(self):
        self.requesting_superadmin = make_user(role=User.Role.SUPERADMIN)

    def _data(self, **overrides):
        data = {
            "username": f"invitee-{os.urandom(4).hex()}",
            "email": "invitee@example.com",
            "first_name": "In",
            "last_name": "Vitee",
            "role": Role.objects.get(slug="consultant").pk,
        }
        data.update(overrides)
        return data

    def _form(self, data):
        from .forms import LocalUserCreateForm

        return LocalUserCreateForm(data, requesting_user=self.requesting_superadmin)

    def test_defaults_to_local_when_oauth_unset(self):
        form = self._form(self._data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.creates_oauth_invite)
        user = form.save()
        self.assertEqual(user.auth_type, User.AuthType.LOCAL)
        self.assertFalse(user.oauth_invite_pending)
        self.assertFalse(user.has_usable_password())

    @override_settings(OAUTH_PROVIDER="google")
    def test_defaults_to_oauth_pending_invite_when_oauth_configured(self):
        form = self._form(self._data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.creates_oauth_invite)
        user = form.save()
        self.assertEqual(user.auth_type, User.AuthType.OAUTH)
        self.assertTrue(user.oauth_invite_pending)
        self.assertFalse(user.has_usable_password())

    @override_settings(OAUTH_PROVIDER="google")
    def test_rejects_superadmin_role_as_oauth_invite(self):
        form = self._form(self._data(role=Role.objects.get(slug="superadmin").pk))
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)

    @override_settings(OAUTH_PROVIDER="google", OAUTH_ALLOWED_DOMAIN="corp.example.com")
    def test_rejects_off_domain_email_as_oauth_invite(self):
        form = self._form(self._data(email="someone@othercorp.com"))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    @override_settings(OAUTH_PROVIDER="google", OAUTH_ALLOWED_DOMAIN="corp.example.com")
    def test_accepts_on_domain_email_as_oauth_invite(self):
        form = self._form(self._data(email="someone@corp.example.com"))
        self.assertTrue(form.is_valid(), form.errors)


class LocalUserEditFormOAuthGuardTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)

    def test_rejects_superadmin_role_change_for_oauth_instance(self):
        from .forms import LocalUserEditForm

        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH)
        form = LocalUserEditForm(
            {
                "email": target.email, "first_name": "", "last_name": "",
                "role": Role.objects.get(slug="superadmin").pk,
                "qualifications": "", "background": "",
            },
            instance=target,
            requesting_user=self.superadmin,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)

    def test_allows_superadmin_role_change_for_local_instance(self):
        from .forms import LocalUserEditForm

        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.LOCAL)
        form = LocalUserEditForm(
            {
                "email": target.email, "first_name": "", "last_name": "",
                "role": Role.objects.get(slug="superadmin").pk,
                "qualifications": "", "background": "",
            },
            instance=target,
            requesting_user=self.superadmin,
        )
        self.assertTrue(form.is_valid(), form.errors)


class UserCreateOAuthInviteViewTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.superadmin)

    @override_settings(OAUTH_PROVIDER="google")
    def test_create_produces_pending_oauth_invite_with_no_email(self):
        mail.outbox = []
        resp = self.client.post(reverse("user_management:create"), {
            "username": "new-invitee",
            "email": "new-invitee@example.com",
            "first_name": "New", "last_name": "Invitee",
            "role": Role.objects.get(slug="consultant").pk,
        })
        user = User.objects.get(username="new-invitee")
        self.assertRedirects(resp, reverse("user_management:detail", args=[user.uuid]))
        self.assertEqual(user.auth_type, User.AuthType.OAUTH)
        self.assertTrue(user.oauth_invite_pending)
        self.assertEqual(len(mail.outbox), 0)


class UserConvertToLocalViewTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.superadmin)

    def test_converts_oauth_user_and_sends_setup_email(self):
        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH)
        target.oauth_invite_pending = True
        target.save(update_fields=["oauth_invite_pending"])
        mail.outbox = []

        resp = self.client.post(reverse("user_management:convert_to_local", args=[target.uuid]))
        self.assertRedirects(resp, reverse("user_management:detail", args=[target.uuid]))

        target.refresh_from_db()
        self.assertEqual(target.auth_type, User.AuthType.LOCAL)
        self.assertFalse(target.oauth_invite_pending)
        self.assertFalse(target.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [target.email])

    def test_404_for_already_local_user(self):
        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.LOCAL)
        resp = self.client.post(reverse("user_management:convert_to_local", args=[target.uuid]))
        self.assertEqual(resp.status_code, 404)


class UserConvertToOAuthViewTests(TestCase):
    def setUp(self):
        self.superadmin = make_user(role=User.Role.SUPERADMIN)
        self.client = Client()
        login(self.client, self.superadmin)

    @override_settings(OAUTH_PROVIDER="google")
    def test_converts_local_user_to_pending_oauth_invite(self):
        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.LOCAL)

        resp = self.client.post(reverse("user_management:convert_to_oauth", args=[target.uuid]), follow=True)
        self.assertRedirects(resp, reverse("user_management:detail", args=[target.uuid]))
        self.assertContains(resp, "pending OAuth invite")

        target.refresh_from_db()
        self.assertEqual(target.auth_type, User.AuthType.OAUTH)
        self.assertTrue(target.oauth_invite_pending)
        self.assertFalse(target.has_usable_password())

    def test_blocked_when_oauth_unset(self):
        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.LOCAL)

        resp = self.client.post(reverse("user_management:convert_to_oauth", args=[target.uuid]), follow=True)
        self.assertContains(resp, "OAuth isn&#x27;t configured")

        target.refresh_from_db()
        self.assertEqual(target.auth_type, User.AuthType.LOCAL)

    @override_settings(OAUTH_PROVIDER="google")
    def test_blocked_for_superadmin_target(self):
        target = make_user(role=User.Role.SUPERADMIN, auth_type=User.AuthType.LOCAL)

        resp = self.client.post(reverse("user_management:convert_to_oauth", args=[target.uuid]), follow=True)
        self.assertContains(resp, "local-auth only")

        target.refresh_from_db()
        self.assertEqual(target.auth_type, User.AuthType.LOCAL)

    @override_settings(OAUTH_PROVIDER="google", OAUTH_ALLOWED_DOMAIN="corp.example.com")
    def test_blocked_for_off_domain_email(self):
        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.LOCAL, email="someone@othercorp.com")

        resp = self.client.post(reverse("user_management:convert_to_oauth", args=[target.uuid]), follow=True)
        self.assertContains(resp, "could never sign in")

        target.refresh_from_db()
        self.assertEqual(target.auth_type, User.AuthType.LOCAL)

    @override_settings(OAUTH_PROVIDER="google")
    def test_404_for_already_oauth_user(self):
        target = make_user(role=User.Role.CONSULTANT, auth_type=User.AuthType.OAUTH)
        resp = self.client.post(reverse("user_management:convert_to_oauth", args=[target.uuid]))
        self.assertEqual(resp.status_code, 404)


class SignupClosedTemplateTests(TestCase):
    """Rendered when an OAuth login has no matching pending invite (is_open_for_signup
    is always False) — allauth's own default is unbranded boilerplate, so this is
    overridden at templates/account/signup_closed.html."""

    def test_renders_with_redscribe_branding_and_guidance(self):
        from django.template.loader import render_to_string

        html = render_to_string("account/signup_closed.html", {})
        self.assertIn("hasn't been invited yet", html)
        self.assertIn("User Management", html)
        self.assertIn(reverse("accounts:login"), html)


class BlockedAllauthUrlsTests(TestCase):
    """RedScribe has its own login/signup/logout/password-reset/email-management —
    allauth's own equivalents (pulled in wholesale by include("allauth.urls")) are
    dead surface that bypass RedScribe's lockout/MFA/invite-only logic, so they're
    shadowed to 404 in config/urls.py rather than left reachable."""

    def test_unused_allauth_urls_404(self):
        from django.urls import reverse

        blocked_names = [
            "account_login", "account_confirm_login_code", "account_logout", "account_signup",
            "account_change_password", "account_set_password", "account_reset_password",
            "account_reset_password_done", "account_reset_password_from_key_done",
            "account_email", "account_reauthenticate", "socialaccount_connections",
            "socialaccount_signup",
        ]
        for name in blocked_names:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)

        url = reverse("account_reset_password_from_key", kwargs={"uidb36": "abc", "key": "xyz"})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_still_used_allauth_urls_remain_reachable(self):
        from django.urls import reverse

        self.assertEqual(self.client.get(reverse("account_inactive")).status_code, 200)
        self.assertEqual(self.client.get(reverse("account_email_verification_sent")).status_code, 200)
        self.assertEqual(self.client.get(reverse("socialaccount_login_cancelled")).status_code, 200)
        self.assertEqual(self.client.get(reverse("socialaccount_login_error")).status_code, 401)
        self.assertEqual(self.client.get(reverse("account_confirm_email", args=["dummy"])).status_code, 200)


class GoogleAuthParamsTests(TestCase):
    """SOCIALACCOUNT_PROVIDERS["google"]["AUTH_PARAMS"] forces Google's account
    chooser every time, rather than silently reusing whichever Google account
    already has an active browser session. This can't be exercised through the
    login page in this environment (INSTALLED_APPS is fixed at process start, and
    this environment has no real Google app installed), so it's verified directly
    against the provider class allauth would otherwise construct from that setting."""

    @override_settings(SOCIALACCOUNT_PROVIDERS={"google": {"AUTH_PARAMS": {"prompt": "select_account"}}})
    def test_prompt_select_account_is_passed_to_googles_authorize_url(self):
        from allauth.socialaccount.models import SocialApp
        from allauth.socialaccount.providers.google.provider import GoogleProvider

        app = SocialApp(provider="google", client_id="x", secret="y")
        provider = GoogleProvider(request=None, app=app)
        self.assertEqual(provider.get_auth_params(), {"prompt": "select_account"})

    @override_settings(SOCIALACCOUNT_PROVIDERS={"microsoft": {"AUTH_PARAMS": {"prompt": "select_account"}}})
    def test_prompt_select_account_is_passed_to_microsofts_authorize_url(self):
        from allauth.socialaccount.models import SocialApp
        from allauth.socialaccount.providers.microsoft.provider import MicrosoftGraphProvider

        app = SocialApp(provider="microsoft", client_id="x", secret="y")
        provider = MicrosoftGraphProvider(request=None, app=app)
        self.assertEqual(provider.get_auth_params(), {"prompt": "select_account"})


class AllauthPageBrandingTests(TestCase):
    """A handful of allauth-rendered pages/emails (mandatory email verification, an
    inactive-account login attempt) are reachable outside the normal invite-claim
    happy path — e.g. a manually added unverified EmailAddress, or a deactivated
    account attempting an OAuth login — so they're styled to match RedScribe's own
    pages rather than left as allauth's unbranded defaults."""

    def _confirmation_email(self):
        from allauth.account.models import EmailAddress, EmailConfirmationHMAC
        from allauth.core import context as allauth_context
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        user = make_user(role=User.Role.CONSULTANT)
        email_address = EmailAddress.objects.create(user=user, email=user.email, verified=False, primary=True)
        request = RequestFactory().get("/", SERVER_NAME="localhost")
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = user
        with allauth_context.request_context(request):
            EmailConfirmationHMAC(email_address).send(request, signup=False)
        return user

    def test_subject_has_no_site_name_bracket_prefix(self):
        mail.outbox = []
        self._confirmation_email()
        self.assertEqual(mail.outbox[0].subject, "Confirm your email address")

    def test_body_uses_redscribe_branding_and_activation_link(self):
        mail.outbox = []
        user = self._confirmation_email()
        message = mail.outbox[0]
        self.assertIn("RedScribe", message.body)
        self.assertIn(user.username, message.body)
        html_body = message.alternatives[0][0]
        self.assertIn("RedScribe", html_body)
        self.assertIn("Confirm email address", html_body)

    def test_verification_sent_page_renders_with_redscribe_branding(self):
        from django.template.loader import render_to_string

        html = render_to_string("account/verification_sent.html", {})
        self.assertIn("Check your email", html)
        self.assertIn(reverse("accounts:login"), html)

    def test_account_inactive_page_renders_with_redscribe_branding(self):
        resp = self.client.get(reverse("account_inactive"))
        self.assertContains(resp, "This account is inactive")
        self.assertContains(resp, reverse("accounts:login"))

    def test_login_cancelled_page_renders_with_redscribe_branding(self):
        resp = self.client.get(reverse("socialaccount_login_cancelled"))
        self.assertContains(resp, "Sign-in cancelled")
        self.assertContains(resp, reverse("accounts:login"))

    def test_authentication_error_page_renders_with_redscribe_branding(self):
        resp = self.client.get(reverse("socialaccount_login_error"))
        self.assertContains(resp, "Sign-in failed", status_code=401)
        self.assertContains(resp, reverse("accounts:login"), status_code=401)

    def test_email_confirm_page_renders_invalid_and_valid_states(self):
        from allauth.account.models import EmailAddress, EmailConfirmationHMAC

        user = make_user(role=User.Role.CONSULTANT)
        email_address = EmailAddress.objects.create(user=user, email=user.email, verified=False, primary=True)
        key = EmailConfirmationHMAC(email_address).key

        resp = self.client.get(reverse("account_confirm_email", args=[key]))
        self.assertContains(resp, "Confirm your email address")
        self.assertContains(resp, user.email)

        resp = self.client.get(reverse("account_confirm_email", args=["not-a-real-key"]))
        self.assertContains(resp, "invalid or has expired")


class LoginPageOAuthAdditiveTests(TestCase):
    """The login page looks the same whether or not OAuth is configured — the local
    form is always front and center — with the provider button(s) simply added below
    it when OAUTH_PROVIDER is set. Superadmin (and anyone else) always has full,
    unhidden access to the local form; OAuth is additive, never a replacement."""

    @override_settings(OAUTH_PROVIDER="google")
    def test_oauth_button_added_alongside_the_always_visible_local_form(self):
        from unittest.mock import MagicMock

        from .adapters import SingleProviderSocialAdapter

        # This environment has no real Google OAuth app configured (INSTALLED_APPS is
        # fixed at process start), so the provider lookup the login template's
        # {% provider_login_url %} tag makes is stubbed out — irrelevant to what's under
        # test here, which is the template's own layout.
        dummy_provider = MagicMock()
        dummy_provider.get_login_url.return_value = "https://example.com/oauth/login"
        with patch.object(SingleProviderSocialAdapter, "get_provider", return_value=dummy_provider):
            resp = self.client.get(reverse("accounts:login"))

        self.assertNotContains(resp, "<details")
        self.assertContains(resp, "Sign in with Google")
        self.assertContains(resp, "Forgot your password?")
        self.assertContains(resp, f'id="{resp.context["form"]["username"].id_for_label}"')

    def test_no_oauth_button_when_oauth_disabled(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertNotContains(resp, "<details")
        self.assertNotContains(resp, "Sign in with Google")
        self.assertNotContains(resp, "Sign in with Microsoft")
        self.assertContains(resp, "Forgot your password?")
