import base64
import os

from cryptography.exceptions import InvalidTag
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.engagements.models import Engagement, EngagementMembership

from . import services
from .models import EncryptedBlob, ProjectKey
from .root_key import KEY_LENGTH_BYTES, RootKeyProvider, RootKeyUnavailable

User = get_user_model()
TEST_PASSWORD = "a-very-long-test-password-123!"


def make_user(role, **kwargs):
    kwargs.setdefault("username", f"user-{role.lower()}-{os.urandom(4).hex()}")
    kwargs.setdefault("email", f"{kwargs['username']}@example.com")
    return User.objects.create(
        role=Role.objects.get(slug=role.lower()), auth_type=User.AuthType.LOCAL, **kwargs
    )


def make_login_user(role, **kwargs):
    user = make_user(role, **kwargs)
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


class RootKeyProviderTests(TestCase):
    # Point REDSCRIBE_ROOT_KEY_FILE at a path that can't exist, so these
    # env-var-only tests aren't shadowed by a real Docker secret mounted at
    # the default /run/secrets/redscribe_root_key (as it is under compose).
    _NO_SUCH_FILE = "/nonexistent/redscribe_root_key_test_sentinel"

    def test_missing_env_var_raises(self):
        provider = RootKeyProvider()
        with override_settings():
            old = os.environ.pop("REDSCRIBE_ROOT_KEY", None)
            old_file_var = os.environ.get("REDSCRIBE_ROOT_KEY_FILE")
            os.environ["REDSCRIBE_ROOT_KEY_FILE"] = self._NO_SUCH_FILE
            try:
                with self.assertRaises(RootKeyUnavailable):
                    provider.key
            finally:
                if old is not None:
                    os.environ["REDSCRIBE_ROOT_KEY"] = old
                if old_file_var is not None:
                    os.environ["REDSCRIBE_ROOT_KEY_FILE"] = old_file_var
                else:
                    os.environ.pop("REDSCRIBE_ROOT_KEY_FILE", None)

    def test_wrong_length_key_rejected(self):
        provider = RootKeyProvider()
        old = os.environ.get("REDSCRIBE_ROOT_KEY")
        old_file_var = os.environ.get("REDSCRIBE_ROOT_KEY_FILE")
        os.environ["REDSCRIBE_ROOT_KEY"] = base64.b64encode(b"too-short").decode()
        os.environ["REDSCRIBE_ROOT_KEY_FILE"] = self._NO_SUCH_FILE
        try:
            with self.assertRaises(RootKeyUnavailable):
                provider.key
        finally:
            if old is not None:
                os.environ["REDSCRIBE_ROOT_KEY"] = old
            if old_file_var is not None:
                os.environ["REDSCRIBE_ROOT_KEY_FILE"] = old_file_var
            else:
                os.environ.pop("REDSCRIBE_ROOT_KEY_FILE", None)

    def test_wrap_unwrap_roundtrip(self):
        os.environ["REDSCRIBE_ROOT_KEY"] = base64.b64encode(os.urandom(KEY_LENGTH_BYTES)).decode()
        os.environ["REDSCRIBE_ROOT_KEY_FILE"] = self._NO_SUCH_FILE
        provider = RootKeyProvider()
        plaintext = os.urandom(32)
        wrapped = provider.wrap(plaintext, associated_data=b"engagement:1")
        self.assertEqual(provider.unwrap(wrapped, associated_data=b"engagement:1"), plaintext)

    def test_reads_from_secret_file_when_present(self):
        import tempfile

        key_b64 = base64.b64encode(os.urandom(KEY_LENGTH_BYTES)).decode()
        old_env = os.environ.pop("REDSCRIBE_ROOT_KEY", None)
        old_file_var = os.environ.get("REDSCRIBE_ROOT_KEY_FILE")
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
                f.write(key_b64 + "\n")
                path = f.name
            os.environ["REDSCRIBE_ROOT_KEY_FILE"] = path
            provider = RootKeyProvider()
            self.assertEqual(provider.key, base64.b64decode(key_b64))
        finally:
            os.remove(path)
            if old_env is not None:
                os.environ["REDSCRIBE_ROOT_KEY"] = old_env
            if old_file_var is not None:
                os.environ["REDSCRIBE_ROOT_KEY_FILE"] = old_file_var
            else:
                os.environ.pop("REDSCRIBE_ROOT_KEY_FILE", None)

    def test_secret_file_takes_precedence_over_env_var(self):
        import tempfile

        file_key = base64.b64encode(os.urandom(KEY_LENGTH_BYTES)).decode()
        env_key = base64.b64encode(os.urandom(KEY_LENGTH_BYTES)).decode()
        old_env = os.environ.get("REDSCRIBE_ROOT_KEY")
        old_file_var = os.environ.get("REDSCRIBE_ROOT_KEY_FILE")
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
                f.write(file_key)
                path = f.name
            os.environ["REDSCRIBE_ROOT_KEY_FILE"] = path
            os.environ["REDSCRIBE_ROOT_KEY"] = env_key
            provider = RootKeyProvider()
            self.assertEqual(provider.key, base64.b64decode(file_key))
        finally:
            os.remove(path)
            if old_env is not None:
                os.environ["REDSCRIBE_ROOT_KEY"] = old_env
            else:
                os.environ.pop("REDSCRIBE_ROOT_KEY", None)
            if old_file_var is not None:
                os.environ["REDSCRIBE_ROOT_KEY_FILE"] = old_file_var
            else:
                os.environ.pop("REDSCRIBE_ROOT_KEY_FILE", None)

    def test_unwrap_with_wrong_associated_data_fails(self):
        os.environ["REDSCRIBE_ROOT_KEY"] = base64.b64encode(os.urandom(KEY_LENGTH_BYTES)).decode()
        os.environ["REDSCRIBE_ROOT_KEY_FILE"] = self._NO_SUCH_FILE
        provider = RootKeyProvider()
        wrapped = provider.wrap(os.urandom(32), associated_data=b"engagement:1")
        with self.assertRaises(InvalidTag):
            provider.unwrap(wrapped, associated_data=b"engagement:2")


class RotateRootKeyCommandTests(TestCase):
    def setUp(self):
        from .root_key import root_key_provider

        self.root_key_provider = root_key_provider
        self.old_key = os.urandom(KEY_LENGTH_BYTES)
        self.new_key = os.urandom(KEY_LENGTH_BYTES)
        self._old_env = os.environ.get("REDSCRIBE_ROOT_KEY")
        self._old_file_var = os.environ.get("REDSCRIBE_ROOT_KEY_FILE")
        os.environ["REDSCRIBE_ROOT_KEY"] = base64.b64encode(self.old_key).decode()
        os.environ["REDSCRIBE_ROOT_KEY_FILE"] = "/nonexistent/rotate_test_sentinel"
        self.root_key_provider._key = None

        self.engagement = Engagement.objects.create(client_name="Rotate Co")
        services.generate_project_key(self.engagement)

    def tearDown(self):
        self.root_key_provider._key = None
        if self._old_env is not None:
            os.environ["REDSCRIBE_ROOT_KEY"] = self._old_env
        else:
            os.environ.pop("REDSCRIBE_ROOT_KEY", None)
        if self._old_file_var is not None:
            os.environ["REDSCRIBE_ROOT_KEY_FILE"] = self._old_file_var
        else:
            os.environ.pop("REDSCRIBE_ROOT_KEY_FILE", None)

    def test_rotate_rewraps_under_new_key_and_bumps_version(self):
        from django.core.management import call_command

        original_raw_key = services.get_data_key(self.engagement)
        project_key = self.engagement.project_key

        call_command("rotate_root_key", new_key=base64.b64encode(self.new_key).decode())

        project_key.refresh_from_db()
        self.assertEqual(project_key.key_version, 2)

        # Simulate deploying the new key and restarting.
        self.root_key_provider._key = None
        os.environ["REDSCRIBE_ROOT_KEY"] = base64.b64encode(self.new_key).decode()
        self.assertEqual(services.get_data_key(self.engagement), original_raw_key)

    def test_dry_run_makes_no_changes(self):
        from django.core.management import call_command

        project_key = self.engagement.project_key
        original_wrapped = bytes(project_key.wrapped_key)

        call_command(
            "rotate_root_key",
            new_key=base64.b64encode(self.new_key).decode(),
            dry_run=True,
        )

        project_key.refresh_from_db()
        self.assertEqual(bytes(project_key.wrapped_key), original_wrapped)
        self.assertEqual(project_key.key_version, 1)

    def test_invalid_new_key_length_raises(self):
        from django.core.management import CommandError, call_command

        with self.assertRaises(CommandError):
            call_command("rotate_root_key", new_key=base64.b64encode(b"too-short").decode())

    def test_wrong_current_key_aborts_without_writes(self):
        from django.core.management import CommandError, call_command

        project_key = self.engagement.project_key
        original_wrapped = bytes(project_key.wrapped_key)

        self.root_key_provider._key = None
        os.environ["REDSCRIBE_ROOT_KEY"] = base64.b64encode(os.urandom(KEY_LENGTH_BYTES)).decode()

        with self.assertRaises(CommandError):
            call_command("rotate_root_key", new_key=base64.b64encode(self.new_key).decode())

        project_key.refresh_from_db()
        self.assertEqual(bytes(project_key.wrapped_key), original_wrapped)
        self.assertEqual(project_key.key_version, 1)


class ReencryptWithAadCommandTests(TestCase):
    """apps.crypto.management.commands.reencrypt_with_aad — the AAD-binding migration."""

    def setUp(self):
        from apps.checklist.models import ChecklistItem, ChecklistItemComment, ChecklistRun
        from apps.findings.models import (
            CommentEntry,
            CommentThread,
            ContentSectionDefinition,
            Finding,
            FindingSection,
            RetestRecord,
        )

        self.engagement = Engagement.objects.create(client_name="AAD Migration Co")
        services.generate_project_key(self.engagement)
        self.key = services.get_data_key(self.engagement)

        self.finding = Finding.objects.create(
            engagement=self.engagement, title="Legacy finding", severity="HIGH",
        )
        # Finding Structure isn't pre-seeded (apps/findings/migrations/
        # 0018_seed_content_sections.py) — create the one section definition
        # this test needs directly, rather than depending on
        # apps.findings.tests' module-level setUpModule() seeding it first.
        definition, _ = ContentSectionDefinition.objects.get_or_create(
            slug="technical-details", defaults={"label": "Technical details", "order": 10},
        )
        self.section = FindingSection.objects.create(
            finding=self.finding, definition=definition,
            # No associated_data — simulates ciphertext written before AAD binding existed.
            content_ciphertext=services.encrypt_bytes(b"legacy section body", self.key),
        )
        self.retest = RetestRecord.objects.create(
            finding=self.finding, status=Finding.RetestStatus.FIXED,
            notes_ciphertext=services.encrypt_bytes(b"legacy retest notes", self.key),
        )
        self.thread = CommentThread.objects.create(
            finding=self.finding, field_name="technical-details", start_pos=0, end_pos=5,
            anchored_text_ciphertext=services.encrypt_bytes(b"legacy anchor", self.key),
        )
        self.entry = CommentEntry.objects.create(
            thread=self.thread,
            body_ciphertext=services.encrypt_bytes(b"legacy comment body", self.key),
        )
        run = ChecklistRun.objects.create(engagement=self.engagement, label="Run 1")
        self.item = ChecklistItem.objects.create(
            run=run, category="Auth", title="Check session handling",
            test_results_ciphertext=services.encrypt_bytes(b"legacy test results", self.key),
        )
        self.comment = ChecklistItemComment.objects.create(
            checklist_item=self.item,
            body_ciphertext=services.encrypt_bytes(b"legacy checklist comment", self.key),
        )
        self.blob = EncryptedBlob.objects.create(
            engagement=self.engagement, content_type="text/plain",
            ciphertext=services.encrypt_bytes(b"legacy blob bytes", self.key),
        )

    def _strict_decrypt(self, ciphertext, aad: bytes) -> bytes:
        # Bypasses decrypt_bytes' AAD-mismatch fallback entirely, so a pass
        # here proves the ciphertext is genuinely bound to `aad` now — not
        # just readable because the fallback papered over a mismatch.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from .root_key import NONCE_LENGTH_BYTES

        raw = bytes(ciphertext)
        nonce, ct = raw[:NONCE_LENGTH_BYTES], raw[NONCE_LENGTH_BYTES:]
        return AESGCM(self.key).decrypt(nonce, ct, aad)

    def test_dry_run_reports_counts_and_changes_nothing(self):
        from django.core.management import call_command

        original = bytes(self.section.content_ciphertext)
        call_command("reencrypt_with_aad", dry_run=True)
        self.section.refresh_from_db()
        self.assertEqual(bytes(self.section.content_ciphertext), original)
        with self.assertRaises(Exception):
            self._strict_decrypt(
                self.section.content_ciphertext,
                services.record_aad("finding", self.finding.pk, "technical-details"),
            )

    def test_rewraps_every_record_type_under_correct_aad(self):
        from django.core.management import call_command

        call_command("reencrypt_with_aad")

        self.section.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.section.content_ciphertext,
                services.record_aad("finding", self.finding.pk, "technical-details"),
            ),
            b"legacy section body",
        )

        self.retest.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.retest.notes_ciphertext,
                services.record_aad("retestrecord", self.retest.pk, "notes"),
            ),
            b"legacy retest notes",
        )

        self.thread.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.thread.anchored_text_ciphertext,
                services.record_aad("commentthread", self.thread.pk, "anchored_text"),
            ),
            b"legacy anchor",
        )

        self.entry.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.entry.body_ciphertext,
                services.record_aad("commententry", self.entry.pk, "body"),
            ),
            b"legacy comment body",
        )

        self.item.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.item.test_results_ciphertext,
                services.record_aad("checklistitem", self.item.pk, "test_results"),
            ),
            b"legacy test results",
        )

        self.comment.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.comment.body_ciphertext,
                services.record_aad("checklistitemcomment", self.comment.pk, "body"),
            ),
            b"legacy checklist comment",
        )

        self.blob.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.blob.ciphertext,
                services.record_aad("encryptedblob", self.blob.id, "ciphertext"),
            ),
            b"legacy blob bytes",
        )

    def test_idempotent_second_run_is_a_no_op_functionally(self):
        from django.core.management import call_command

        call_command("reencrypt_with_aad")
        call_command("reencrypt_with_aad")  # must not raise or corrupt anything

        self.section.refresh_from_db()
        self.assertEqual(
            self._strict_decrypt(
                self.section.content_ciphertext,
                services.record_aad("finding", self.finding.pk, "technical-details"),
            ),
            b"legacy section body",
        )

    def test_skips_engagement_with_no_project_key_and_leaves_its_records_alone(self):
        from django.core.management import call_command

        from apps.findings.models import ContentSectionDefinition, Finding, FindingSection

        keyless_engagement = Engagement.objects.create(client_name="No ProjectKey Co")
        # No generate_project_key() call — this engagement has no ProjectKey,
        # so it can't be re-encrypted; the command must skip it, not crash.
        keyless_finding = Finding.objects.create(
            engagement=keyless_engagement, title="Orphaned", severity="LOW",
        )
        definition, _ = ContentSectionDefinition.objects.get_or_create(
            slug="technical-details", defaults={"label": "Technical details", "order": 10},
        )
        orphan_section = FindingSection.objects.create(
            finding=keyless_finding, definition=definition,
            content_ciphertext=b"not-even-valid-ciphertext",
        )

        call_command("reencrypt_with_aad")  # must not raise

        orphan_section.refresh_from_db()
        self.assertEqual(bytes(orphan_section.content_ciphertext), b"not-even-valid-ciphertext")


class ProjectKeyServiceTests(TestCase):
    def setUp(self):
        self.engagement_a = Engagement.objects.create(client_name="Engagement A")
        self.engagement_b = Engagement.objects.create(client_name="Engagement B")

    def test_generate_and_get_data_key_roundtrip(self):
        services.generate_project_key(self.engagement_a)
        key = services.get_data_key(self.engagement_a)
        self.assertEqual(len(key), services.DATA_KEY_LENGTH_BYTES)

    def test_generate_twice_raises(self):
        services.generate_project_key(self.engagement_a)
        with self.assertRaises(ValueError):
            services.generate_project_key(self.engagement_a)

    def test_each_engagement_gets_a_distinct_key(self):
        services.generate_project_key(self.engagement_a)
        services.generate_project_key(self.engagement_b)
        key_a = services.get_data_key(self.engagement_a)
        key_b = services.get_data_key(self.engagement_b)
        self.assertNotEqual(key_a, key_b)

    def test_swapped_wrapped_key_blob_fails_to_unwrap(self):
        pk_a = services.generate_project_key(self.engagement_a)
        pk_b = services.generate_project_key(self.engagement_b)

        pk_a.wrapped_key, pk_b.wrapped_key = pk_b.wrapped_key, pk_a.wrapped_key
        pk_a.save()
        pk_b.save()

        with self.assertRaises(PermissionDenied):
            services.get_data_key(self.engagement_a)
        with self.assertRaises(PermissionDenied):
            services.get_data_key(self.engagement_b)

    def test_get_data_key_without_project_key_raises(self):
        with self.assertRaises(PermissionDenied):
            services.get_data_key(self.engagement_a)

    def test_field_encryption_roundtrip(self):
        services.generate_project_key(self.engagement_a)
        key = services.get_data_key(self.engagement_a)
        plaintext = b"technical details: SQLi in /login"
        blob = services.encrypt_bytes(plaintext, key)
        self.assertEqual(services.decrypt_bytes(blob, key), plaintext)

    def test_field_encryption_wrong_key_fails(self):
        services.generate_project_key(self.engagement_a)
        services.generate_project_key(self.engagement_b)
        key_a = services.get_data_key(self.engagement_a)
        key_b = services.get_data_key(self.engagement_b)
        blob = services.encrypt_bytes(b"secret", key_a)
        with self.assertRaises(InvalidTag):
            services.decrypt_bytes(blob, key_b)


class RecordAadBindingTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        services.generate_project_key(self.engagement)
        self.key = services.get_data_key(self.engagement)

    def test_decrypts_with_matching_aad(self):
        ciphertext = services.encrypt_bytes(
            b"secret", self.key, associated_data=services.record_aad("finding", "abc", "technical_details"),
        )
        plaintext = services.decrypt_bytes(
            ciphertext, self.key, associated_data=services.record_aad("finding", "abc", "technical_details"),
        )
        self.assertEqual(plaintext, b"secret")

    def test_ciphertext_swapped_to_a_different_record_fails_to_decrypt(self):
        ciphertext = services.encrypt_bytes(
            b"secret", self.key, associated_data=services.record_aad("finding", "finding-a", "technical_details"),
        )
        with self.assertRaises(InvalidTag):
            services.decrypt_bytes(
                ciphertext, self.key,
                associated_data=services.record_aad("finding", "finding-b", "technical_details"),
            )

    def test_ciphertext_swapped_to_a_different_field_on_the_same_record_fails_to_decrypt(self):
        ciphertext = services.encrypt_bytes(
            b"secret", self.key, associated_data=services.record_aad("finding", "abc", "technical_details"),
        )
        with self.assertRaises(InvalidTag):
            services.decrypt_bytes(
                ciphertext, self.key, associated_data=services.record_aad("finding", "abc", "note"),
            )

    def test_ciphertext_with_no_aad_fails_to_decrypt_when_aad_is_required(self):
        # The AAD-mismatch fallback that used to make this succeed (for
        # pre-AAD-binding legacy ciphertext) is gone from decrypt_bytes —
        # see `reencrypt_with_aad` for migrating any ciphertext that still
        # needs it. No new ciphertext should ever be written without AAD
        # via encrypt_bytes when a caller passes one on decrypt.
        ciphertext = services.encrypt_bytes(b"legacy secret", self.key)
        with self.assertRaises(InvalidTag):
            services.decrypt_bytes(
                ciphertext, self.key,
                associated_data=services.record_aad("finding", "abc", "technical_details"),
            )

    def test_fallback_never_masks_genuine_tampering(self):
        ciphertext = bytearray(services.encrypt_bytes(
            b"secret", self.key, associated_data=services.record_aad("finding", "abc", "technical_details"),
        ))
        ciphertext[-1] ^= 0xFF
        with self.assertRaises(InvalidTag):
            services.decrypt_bytes(
                bytes(ciphertext), self.key,
                associated_data=services.record_aad("finding", "abc", "technical_details"),
            )


class AccessCheckAndKeyAttachmentTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Active Engagement")
        services.generate_project_key(self.engagement)
        self.expected_key = services.get_data_key(self.engagement)

        self.archived_engagement = Engagement.objects.create(
            client_name="Archived Engagement", archived=True
        )
        services.generate_project_key(self.archived_engagement)

        self.superadmin = make_user(User.Role.SUPERADMIN)
        self.team_lead = make_user(User.Role.TEAM_LEAD)
        self.senior_member = make_user(User.Role.SENIOR)
        self.senior_nonmember = make_user(User.Role.SENIOR)
        self.consultant_member = make_user(User.Role.CONSULTANT)

        EngagementMembership.objects.create(user=self.senior_member, engagement=self.engagement)
        EngagementMembership.objects.create(user=self.consultant_member, engagement=self.engagement)
        EngagementMembership.objects.create(
            user=self.senior_member, engagement=self.archived_engagement
        )

    def _attach(self, user, engagement):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = user
        from .access import _attach_engagement_and_key

        _attach_engagement_and_key(request, engagement.pk)
        return request

    def test_superadmin_always_granted_active(self):
        request = self._attach(self.superadmin, self.engagement)
        self.assertEqual(request.project_key, self.expected_key)

    def test_superadmin_always_granted_even_when_archived(self):
        request = self._attach(self.superadmin, self.archived_engagement)
        self.assertIsNotNone(request.project_key)

    def test_team_lead_blanket_access_on_active(self):
        request = self._attach(self.team_lead, self.engagement)
        self.assertEqual(request.project_key, self.expected_key)

    def test_team_lead_denied_on_archived(self):
        with self.assertRaises(PermissionDenied):
            self._attach(self.team_lead, self.archived_engagement)

    def test_member_granted(self):
        request = self._attach(self.senior_member, self.engagement)
        self.assertEqual(request.project_key, self.expected_key)

    def test_nonmember_denied(self):
        with self.assertRaises(PermissionDenied):
            self._attach(self.senior_nonmember, self.engagement)

    def test_member_denied_once_archived(self):
        with self.assertRaises(PermissionDenied):
            self._attach(self.senior_member, self.archived_engagement)

    def test_consultant_member_granted(self):
        request = self._attach(self.consultant_member, self.engagement)
        self.assertEqual(request.project_key, self.expected_key)

    def test_key_never_fetched_when_access_denied(self):
        from unittest.mock import patch

        with patch("apps.crypto.access.get_data_key", side_effect=AssertionError("should not be called")):
            with self.assertRaises(PermissionDenied):
                self._attach(self.senior_nonmember, self.engagement)


_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class EncryptedBlobTests(TestCase):
    def setUp(self):
        self.engagement = Engagement.objects.create(client_name="Acme")
        services.generate_project_key(self.engagement)
        self.member = make_login_user(User.Role.CONSULTANT)
        EngagementMembership.objects.create(user=self.member, engagement=self.engagement)
        self.outsider = make_login_user(User.Role.CONSULTANT)

    def _upload(self, client, filename="pixel.png", content_type="image/png", data=_TINY_PNG):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(filename, data, content_type=content_type)
        return client.post(reverse("crypto:blob_upload", args=[self.engagement.pk]), {"file": upload})

    def test_member_can_upload_and_serve_roundtrip(self):
        client = Client()
        login(client, self.member)

        resp = self._upload(client)
        self.assertEqual(resp.status_code, 200)
        url = resp.json()["url"]

        blob = EncryptedBlob.objects.get(engagement=self.engagement)
        self.assertEqual(blob.content_type, "image/png")
        self.assertEqual(blob.uploaded_by, self.member)

        self.assertNotEqual(bytes(blob.ciphertext), _TINY_PNG)

        serve_resp = client.get(url)
        self.assertEqual(serve_resp.status_code, 200)
        self.assertEqual(serve_resp["Content-Type"], "image/png")
        self.assertEqual(serve_resp.content, _TINY_PNG)

    def test_non_member_cannot_upload(self):
        client = Client()
        login(client, self.outsider)
        resp = self._upload(client)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(EncryptedBlob.objects.exists())

    def test_non_member_cannot_serve(self):
        client = Client()
        login(client, self.member)
        resp = self._upload(client)
        url = resp.json()["url"]

        outsider_client = Client()
        login(outsider_client, self.outsider)
        resp = outsider_client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_disallowed_content_type_rejected(self):
        client = Client()
        login(client, self.member)
        resp = self._upload(client, filename="evil.svg", content_type="image/svg+xml", data=b"<svg></svg>")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(EncryptedBlob.objects.exists())

    def test_content_type_header_lying_about_non_image_bytes_is_rejected(self):
        client = Client()
        login(client, self.member)
        resp = self._upload(client, filename="evil.png", content_type="image/png", data=b"<script>alert(1)</script>")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(EncryptedBlob.objects.exists())

    def test_content_type_is_server_detected_not_client_supplied(self):
        import io

        from PIL import Image

        client = Client()
        login(client, self.member)
        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="JPEG")
        resp = self._upload(client, filename="pixel.jpg", content_type="image/png", data=buf.getvalue())
        self.assertEqual(resp.status_code, 200)
        blob = EncryptedBlob.objects.get()
        self.assertEqual(blob.content_type, "image/jpeg")

    def test_serve_sets_nosniff_header(self):
        client = Client()
        login(client, self.member)
        resp = self._upload(client)
        url = resp.json()["url"]
        serve_resp = client.get(url)
        self.assertEqual(serve_resp["X-Content-Type-Options"], "nosniff")


class AnonymousAccessGetsA401Tests(TestCase):
    def test_anonymous_request_gets_401_not_403(self):
        engagement = Engagement.objects.create(client_name="Some Engagement")
        resp = Client().get(reverse("findings:list", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_non_member_still_gets_403(self):
        engagement = Engagement.objects.create(client_name="Some Engagement")
        outsider = make_login_user(User.Role.CONSULTANT)
        client = Client()
        login(client, outsider)
        resp = client.get(reverse("findings:list", args=[engagement.pk]))
        self.assertEqual(resp.status_code, 403)
