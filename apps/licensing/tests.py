import datetime
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role

from .models import LicenseKey
from .payload import canonical_payload_bytes, decode_license_key, encode_license_key
from .status import license_status
from .verify import verify_license_key

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


def _keypair():
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH, format=serialization.PublicFormat.OpenSSH,
    ).decode()
    return private_key, public_pem


def _iso(days_from_today: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days_from_today)).isoformat()


def _sign(private_key, org="ACME Corp", issued="2026-01-01", expires=None, license_type="commercial"):
    expires = expires or _iso(365)
    payload_bytes = canonical_payload_bytes(org=org, issued=issued, expires=expires, license_type=license_type)
    return encode_license_key(payload_bytes, private_key.sign(payload_bytes))


class PayloadTests(TestCase):
    def test_roundtrip(self):
        payload_bytes = canonical_payload_bytes(org="ACME Corp", issued="2026-01-01", expires="2027-01-01")
        key_text = encode_license_key(payload_bytes, b"fake-signature-bytes")
        decoded_payload, decoded_sig = decode_license_key(key_text)
        self.assertEqual(decoded_payload, payload_bytes)
        self.assertEqual(decoded_sig, b"fake-signature-bytes")

    def test_malformed_key_raises(self):
        with self.assertRaises(ValueError):
            decode_license_key("not-a-valid-key-at-all")


class VerifyLicenseKeyTests(TestCase):
    def test_valid_signature_verifies_and_returns_payload(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp", expires="2027-01-01")

        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            result = verify_license_key(key_text)

        self.assertEqual(
            result, {"org": "ACME Corp", "issued": "2026-01-01", "expires": "2027-01-01", "type": "commercial"},
        )

    def test_signature_from_a_different_key_is_rejected(self):
        signer_key, _ = _keypair()
        _, wrong_public_pem = _keypair()
        key_text = _sign(signer_key)

        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=wrong_public_pem):
            self.assertIsNone(verify_license_key(key_text))

    def test_tampered_key_text_is_rejected(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key)

        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            self.assertIsNone(verify_license_key(key_text + "tampered"))

    def test_empty_key_text_returns_none(self):
        self.assertIsNone(verify_license_key(""))
        self.assertIsNone(verify_license_key("   "))

    def test_no_public_key_configured_returns_none(self):
        private_key, _ = _keypair()
        key_text = _sign(private_key)

        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=""):
            self.assertIsNone(verify_license_key(key_text))

    def test_garbage_input_never_raises(self):
        self.assertIsNone(verify_license_key("garbage"))
        self.assertIsNone(verify_license_key("also.garbage"))

    def test_expired_signature_still_verifies_as_authentic(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp", expires=_iso(-10))

        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            result = verify_license_key(key_text)

        self.assertEqual(result["org"], "ACME Corp")


class LicenseStatusTests(TestCase):
    def test_no_payload_is_state_none(self):
        self.assertEqual(license_status(None), {"state": "none"})

    def test_far_future_expiry_is_active(self):
        result = license_status({"org": "ACME Corp", "issued": "2026-01-01", "expires": _iso(200), "type": "commercial"})
        self.assertEqual(result["state"], "active")

    def test_within_30_days_is_expiring_soon(self):
        result = license_status({"org": "ACME Corp", "issued": "2026-01-01", "expires": _iso(15), "type": "commercial"})
        self.assertEqual(result["state"], "expiring_soon")
        self.assertEqual(result["days_left"], 15)

    def test_exactly_30_days_is_expiring_soon_boundary(self):
        result = license_status({"org": "ACME Corp", "issued": "2026-01-01", "expires": _iso(30), "type": "commercial"})
        self.assertEqual(result["state"], "expiring_soon")

    def test_31_days_is_still_active(self):
        result = license_status({"org": "ACME Corp", "issued": "2026-01-01", "expires": _iso(31), "type": "commercial"})
        self.assertEqual(result["state"], "active")

    def test_past_expiry_is_expired(self):
        result = license_status({"org": "ACME Corp", "issued": "2026-01-01", "expires": _iso(-1), "type": "commercial"})
        self.assertEqual(result["state"], "expired")
        self.assertEqual(result["days_left"], -1)


class LicenseEditViewTests(TestCase):
    def setUp(self):
        self.url = reverse("licensing:edit")
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def test_non_superadmin_gets_403(self):
        client = Client()
        login(client, make_user(User.Role.TEAM_LEAD))
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_saving_a_valid_key_succeeds(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp")

        client = Client()
        login(client, self.superadmin)
        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            resp = client.post(self.url, {"key_text": key_text}, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(LicenseKey.get_solo().key_text, key_text)

    def test_saving_an_invalid_key_is_rejected_with_an_error(self):
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {"key_text": "not-a-real-license-key"})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].errors.get("key_text"))
        self.assertEqual(LicenseKey.get_solo().key_text, "")

    def test_blank_key_text_is_allowed_community_use(self):
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {"key_text": ""}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(LicenseKey.get_solo().key_text, "")


class FooterAndBannerTests(TestCase):
    def setUp(self):
        self.staff_user = make_user(User.Role.TEAM_LEAD)
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def test_footer_shows_plain_version_with_no_license(self):
        client = Client()
        login(client, self.staff_user)
        resp = client.get(reverse("accounts:dashboard"))
        self.assertContains(resp, "RedScribe v")
        self.assertNotContains(resp, "Licensed to")

    def test_footer_shows_licensed_org_for_an_active_key(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp", expires=_iso(200))
        LicenseKey.objects.create(pk=1, key_text=key_text)

        client = Client()
        login(client, self.staff_user)
        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            resp = client.get(reverse("accounts:dashboard"))

        self.assertContains(resp, "Licensed to ACME Corp")

    def test_footer_shows_expired_state_distinctly(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp", expires=_iso(-5))
        LicenseKey.objects.create(pk=1, key_text=key_text)

        client = Client()
        login(client, self.staff_user)
        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            resp = client.get(reverse("accounts:dashboard"))

        self.assertContains(resp, "License expired")

    def test_expiring_soon_banner_shown_to_superadmin_only(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp", expires=_iso(10))
        LicenseKey.objects.create(pk=1, key_text=key_text)

        superadmin_client = Client()
        login(superadmin_client, self.superadmin)
        staff_client = Client()
        login(staff_client, self.staff_user)

        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            superadmin_resp = superadmin_client.get(reverse("accounts:dashboard"))
            staff_resp = staff_client.get(reverse("accounts:dashboard"))

        self.assertContains(superadmin_resp, "expires in 10 day")
        self.assertNotContains(staff_resp, "expires in 10 day")

    def test_no_banner_when_license_is_comfortably_active(self):
        private_key, public_pem = _keypair()
        key_text = _sign(private_key, org="ACME Corp", expires=_iso(200))
        LicenseKey.objects.create(pk=1, key_text=key_text)

        client = Client()
        login(client, self.superadmin)
        with override_settings(LICENSE_SIGNING_PUBLIC_KEY=public_pem):
            resp = client.get(reverse("accounts:dashboard"))

        self.assertNotContains(resp, "expires in")
        self.assertNotContains(resp, "expired on")
