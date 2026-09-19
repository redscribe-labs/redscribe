import os

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LoginAttempt, Role

from .models import AuditLogEntry

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


class AuditLogViewTests(TestCase):
    def setUp(self):
        self.url = reverse("audit:list")
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def test_superadmin_can_view(self):
        client = Client()
        login(client, self.superadmin)
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 200)

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

    def test_anonymous_redirected_to_login(self):
        resp = Client().get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_a_real_state_changing_request_is_logged_and_visible(self):
        client = Client()
        login(client, self.superadmin)
        client.post(reverse("feature_flags:edit"), {})

        resp = client.get(self.url)
        results = resp.context["page_obj"].object_list
        self.assertTrue(any(e.action == "feature_flags:edit" for e in results))

    def test_search_filters_by_actor_username(self):
        target = make_user(User.Role.CONSULTANT, username="findable-actor")
        client = Client()
        login(client, target)
        AuditLogEntry.objects.create(
            actor=target, actor_username="findable-actor", action="findings:create",
            method="POST", path="/x/", status_code=302,
        )

        admin_client = Client()
        login(admin_client, self.superadmin)
        resp = admin_client.get(self.url, {"q": "findable-actor"})
        results = resp.context["page_obj"].object_list
        self.assertTrue(all(e.actor_username == "findable-actor" for e in results))
        self.assertGreaterEqual(len(results), 1)

    def test_method_filter(self):
        AuditLogEntry.objects.create(
            actor_username="someone", action="findings:archive", method="DELETE", path="/y/", status_code=204,
        )
        client = Client()
        login(client, self.superadmin)
        resp = client.get(self.url, {"method": "DELETE"})
        results = resp.context["page_obj"].object_list
        self.assertTrue(all(e.method == "DELETE" for e in results))
        self.assertGreaterEqual(len(results), 1)

    def test_bare_login_attempt_row_is_not_shown_in_the_audit_log(self):
        from apps.accounts.models import LoginAttempt

        LoginAttempt.objects.create(
            username_attempted="oauth-user", successful=True,
            auth_method=LoginAttempt.AuthMethod.OAUTH, ip_address="10.0.0.5",
        )
        client = Client()
        login(client, self.superadmin)
        resp = client.get(self.url)
        results = resp.context["page_obj"].object_list
        self.assertFalse(any(e.actor_username == "oauth-user" for e in results))

    def test_local_login_attempt_is_not_duplicated_in_the_merged_view(self):
        from apps.accounts.models import LoginAttempt

        LoginAttempt.objects.create(
            username_attempted="local-user", successful=True,
            auth_method=LoginAttempt.AuthMethod.LOCAL, ip_address="10.0.0.6",
        )
        client = Client()
        login(client, self.superadmin)
        resp = client.get(self.url)
        results = resp.context["page_obj"].object_list
        self.assertFalse(any(e.actor_username == "local-user" for e in results))

    def test_get_requests_are_now_logged(self):
        client = Client()
        login(client, self.superadmin)
        client.get(self.url)

        resp = client.get(self.url)
        results = resp.context["page_obj"].object_list
        self.assertTrue(any(e.method == "GET" and e.action == "audit:list" for e in results))

    def test_reports_preview_stays_excluded_even_though_gets_are_logged_now(self):
        from .middleware import _EXCLUDED_VIEW_NAMES

        self.assertIn("reports:preview", _EXCLUDED_VIEW_NAMES)

    def test_health_check_endpoint_is_not_logged(self):
        from .models import AuditLogEntry

        before = AuditLogEntry.objects.count()
        Client().get("/health/")
        self.assertEqual(AuditLogEntry.objects.count(), before)


class RedactionTests(TestCase):
    def test_sensitive_query_params_are_redacted(self):
        from apps.audit.redaction import sanitize_query_string

        result = sanitize_query_string("q=hello&api_token=abc123&password=hunter2&page=2")
        self.assertIn("q=hello", result)
        self.assertIn("page=2", result)
        self.assertNotIn("abc123", result)
        self.assertNotIn("hunter2", result)
        self.assertIn("api_token=%5Bredacted%5D", result)

    def test_non_sensitive_query_string_passes_through(self):
        from apps.audit.redaction import sanitize_query_string

        self.assertEqual(sanitize_query_string("q=xss&method=GET"), "q=xss&method=GET")

    def test_empty_query_string(self):
        from apps.audit.redaction import sanitize_query_string

        self.assertEqual(sanitize_query_string(""), "")

    def test_referer_strips_token_shaped_path_segments(self):
        from apps.audit.redaction import sanitize_referer

        referer = "https://example.com/password/reset/MQ/aB3dEf6hIjKlMnOpQrSt/"
        result = sanitize_referer(referer)
        self.assertNotIn("aB3dEf6hIjKlMnOpQrSt", result)
        self.assertIn("password", result)
        self.assertIn("reset", result)

    def test_referer_strips_sensitive_query_params_too(self):
        from apps.audit.redaction import sanitize_referer

        result = sanitize_referer("https://example.com/search/?q=test&token=secretsecretsecret")
        self.assertNotIn("secretsecretsecret", result)
        self.assertIn("q=test", result)

    def test_referer_drops_scheme_and_host(self):
        from apps.audit.redaction import sanitize_referer

        result = sanitize_referer("https://example.com/findings/list/")
        self.assertNotIn("example.com", result)
        self.assertNotIn("https", result)

    def test_short_normal_path_segments_are_not_treated_as_tokens(self):
        from apps.audit.redaction import sanitize_referer

        result = sanitize_referer("https://example.com/engagements/list/")
        self.assertIn("engagements", result)
        self.assertIn("list", result)

    def test_sensitive_kwargs_redacted_in_object_ref(self):
        from apps.audit.redaction import sanitize_object_ref

        ref = sanitize_object_ref({"uidb64": "MQ", "token": "abc123-realtoken", "pk": "5"})
        self.assertIn("pk=5", ref)
        self.assertNotIn("abc123-realtoken", ref)
        self.assertNotIn("MQ", ref)


class PasswordResetAuditTests(TestCase):
    def test_password_reset_confirm_path_is_redacted_in_audit_log(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        from .models import AuditLogEntry

        superadmin = make_user(User.Role.SUPERADMIN)
        uid = urlsafe_base64_encode(force_bytes(superadmin.pk))
        token = default_token_generator.make_token(superadmin)

        Client().get(reverse("accounts:password_reset_confirm", args=[uid, token]))

        entry = AuditLogEntry.objects.filter(action="accounts:password_reset_confirm").latest("created_at")
        self.assertNotIn(token, entry.path)
        self.assertNotIn(uid, entry.path)
        self.assertIn("[redacted]", entry.path)


class RetentionTests(TestCase):
    def _backdated_entry(self, days_old):
        entry = AuditLogEntry.objects.create(
            actor_username="x", action="findings:create", method="POST", path="/x/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_old)
        )
        return entry

    def _backdated_login_attempt(self, days_old):
        attempt = LoginAttempt.objects.create(username_attempted="x", successful=True)
        LoginAttempt.objects.filter(pk=attempt.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_old)
        )
        return attempt

    def test_purge_deletes_only_entries_older_than_cutoff(self):
        from apps.audit.retention import purge_older_than

        old = self._backdated_entry(400)
        recent = self._backdated_entry(10)

        counts = purge_older_than(days=365)

        self.assertEqual(counts["audit_log"], 1)
        self.assertFalse(AuditLogEntry.objects.filter(pk=old.pk).exists())
        self.assertTrue(AuditLogEntry.objects.filter(pk=recent.pk).exists())

    def test_purge_also_covers_login_attempts_on_the_same_cutoff(self):
        from apps.audit.retention import purge_older_than

        old = self._backdated_login_attempt(400)
        recent = self._backdated_login_attempt(10)

        counts = purge_older_than(days=365)

        self.assertEqual(counts["login_attempts"], 1)
        self.assertFalse(LoginAttempt.objects.filter(pk=old.pk).exists())
        self.assertTrue(LoginAttempt.objects.filter(pk=recent.pk).exists())

    def test_count_older_than_is_a_dry_run(self):
        from apps.audit.retention import count_older_than

        old = self._backdated_entry(400)
        counts = count_older_than(days=365)

        self.assertEqual(counts["audit_log"], 1)
        self.assertTrue(AuditLogEntry.objects.filter(pk=old.pk).exists())


class PartitionedRetentionTests(TransactionTestCase):
    serialized_rollback = True

    def _create_year_partition(self, year):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS audit_auditlogentry_{year} "
                f"PARTITION OF audit_auditlogentry FOR VALUES FROM (%s) TO (%s)",
                [f"{year}-01-01", f"{year + 1}-01-01"],
            )

    def _partition_exists(self, name):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
            return cursor.fetchone()[0]

    def test_fully_expired_year_partition_is_dropped_not_row_deleted(self):
        from apps.audit.retention import purge_older_than

        self._create_year_partition(2020)
        old = AuditLogEntry.objects.create(
            actor_username="ancient", action="x", method="GET", path="/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=old.pk).update(
            created_at=timezone.datetime(2020, 6, 1, tzinfo=timezone.get_default_timezone())
        )
        self.assertTrue(self._partition_exists("audit_auditlogentry_2020"))

        counts = purge_older_than(days=365)

        self.assertEqual(counts["audit_log"], 1)
        self.assertFalse(self._partition_exists("audit_auditlogentry_2020"))
        self.assertFalse(AuditLogEntry.objects.filter(pk=old.pk).exists())

    def test_partition_spanning_the_cutoff_is_not_dropped_only_matching_rows_are(self):
        from apps.audit.retention import purge_older_than

        self._create_year_partition(2020)
        old = AuditLogEntry.objects.create(
            actor_username="old-in-2020", action="x", method="GET", path="/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=old.pk).update(
            created_at=timezone.datetime(2020, 1, 5, tzinfo=timezone.get_default_timezone())
        )
        recent = AuditLogEntry.objects.create(
            actor_username="recent-in-2020", action="x", method="GET", path="/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=recent.pk).update(
            created_at=timezone.datetime(2020, 12, 20, tzinfo=timezone.get_default_timezone())
        )
        cutoff = timezone.datetime(2020, 6, 1, tzinfo=timezone.get_default_timezone())
        cutoff_days = (timezone.now() - cutoff).days

        purge_older_than(days=cutoff_days)

        self.assertTrue(self._partition_exists("audit_auditlogentry_2020"))
        self.assertFalse(AuditLogEntry.objects.filter(pk=old.pk).exists())
        self.assertTrue(AuditLogEntry.objects.filter(pk=recent.pk).exists())

    def test_default_catchall_partition_is_never_dropped(self):
        from apps.audit.retention import purge_older_than

        old = AuditLogEntry.objects.create(
            actor_username="in-default", action="x", method="GET", path="/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=old.pk).update(
            created_at=timezone.datetime(2015, 1, 1, tzinfo=timezone.get_default_timezone())
        )

        purge_older_than(days=365)

        self.assertTrue(self._partition_exists("audit_auditlogentry_default"))
        self.assertFalse(AuditLogEntry.objects.filter(pk=old.pk).exists())


class PurgeViewTests(TestCase):
    def setUp(self):
        self.url = reverse("audit:purge")
        self.superadmin = self._make_superadmin()

    def _make_superadmin(self):
        return make_user(User.Role.SUPERADMIN)

    def _backdated_entry(self, days_old):
        entry = AuditLogEntry.objects.create(
            actor_username="x", action="findings:create", method="POST", path="/x/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_old)
        )
        return entry

    def test_non_superadmin_cannot_purge(self):
        client = Client()
        login(client, make_user(User.Role.TEAM_LEAD))
        resp = client.post(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_get_does_not_delete_anything(self):
        old = self._backdated_entry(3000)
        client = Client()
        login(client, self.superadmin)
        client.get(self.url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=old.pk).exists())

    def test_post_purges_and_redirects(self):
        old = self._backdated_entry(3000)
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url)
        self.assertRedirects(resp, reverse("audit:list"))
        self.assertFalse(AuditLogEntry.objects.filter(pk=old.pk).exists())


class PurgeAllViewTests(TestCase):
    def setUp(self):
        self.confirm_url = reverse("audit:purge_all_confirm")
        self.url = reverse("audit:purge_all")
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def _entry(self, days_old=0):
        entry = AuditLogEntry.objects.create(
            actor_username="x", action="findings:create", method="POST", path="/x/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_old)
        )
        return entry

    def test_non_superadmin_cannot_reach_confirm_page_or_clear(self):
        client = Client()
        login(client, make_user(User.Role.TEAM_LEAD))
        self.assertEqual(client.get(self.confirm_url).status_code, 403)
        self.assertEqual(client.post(self.url, {"confirm_phrase": "DELETE ALL LOGS"}).status_code, 403)

    def test_wrong_confirm_phrase_deletes_nothing(self):
        entry = self._entry()
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {"confirm_phrase": "delete all logs"})
        self.assertRedirects(resp, self.confirm_url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=entry.pk).exists())

    def test_correct_phrase_alone_is_not_enough_without_a_second_approver(self):
        entry = self._entry()
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {"confirm_phrase": "DELETE ALL LOGS"})
        self.assertRedirects(resp, self.confirm_url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=entry.pk).exists())

    def test_second_approver_with_wrong_password_deletes_nothing(self):
        other_superadmin = make_user(User.Role.SUPERADMIN)
        entry = self._entry()
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {
            "confirm_phrase": "DELETE ALL LOGS",
            "approver_username": other_superadmin.username, "approver_password": "wrong-password",
        })
        self.assertRedirects(resp, self.confirm_url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=entry.pk).exists())

    def test_approving_your_own_purge_is_rejected(self):
        entry = self._entry()
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {
            "confirm_phrase": "DELETE ALL LOGS",
            "approver_username": self.superadmin.username, "approver_password": TEST_PASSWORD,
        })
        self.assertRedirects(resp, self.confirm_url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=entry.pk).exists())

    def test_non_superadmin_approver_deletes_nothing(self):
        team_lead = make_user(User.Role.TEAM_LEAD)
        entry = self._entry()
        client = Client()
        login(client, self.superadmin)
        resp = client.post(self.url, {
            "confirm_phrase": "DELETE ALL LOGS",
            "approver_username": team_lead.username, "approver_password": TEST_PASSWORD,
        })
        self.assertRedirects(resp, self.confirm_url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=entry.pk).exists())

    def test_correct_phrase_and_a_different_superadmin_approver_deletes_everything_regardless_of_age(self):
        other_superadmin = make_user(User.Role.SUPERADMIN)
        recent = self._entry(days_old=0)
        old = self._entry(days_old=3000)
        client = Client()
        login(client, self.superadmin)

        resp = client.post(self.url, {
            "confirm_phrase": "DELETE ALL LOGS",
            "approver_username": other_superadmin.username, "approver_password": TEST_PASSWORD,
        })

        self.assertRedirects(resp, reverse("audit:list"))
        self.assertFalse(AuditLogEntry.objects.filter(pk=recent.pk).exists())
        self.assertFalse(AuditLogEntry.objects.filter(pk=old.pk).exists())

    def test_get_on_purge_all_does_not_delete_anything(self):
        entry = self._entry()
        client = Client()
        login(client, self.superadmin)
        client.get(self.url)
        self.assertTrue(AuditLogEntry.objects.filter(pk=entry.pk).exists())


class PurgeCommandTests(TestCase):
    def _backdated_entry(self, days_old):
        entry = AuditLogEntry.objects.create(
            actor_username="x", action="findings:create", method="POST", path="/x/", status_code=200,
        )
        AuditLogEntry.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_old)
        )
        return entry

    def test_dry_run_does_not_delete(self):
        from django.core.management import call_command

        old = self._backdated_entry(3000)
        call_command("purge_audit_log", "--dry-run")
        self.assertTrue(AuditLogEntry.objects.filter(pk=old.pk).exists())

    def test_days_override_takes_precedence_over_setting(self):
        from django.core.management import call_command

        entry = self._backdated_entry(30)
        call_command("purge_audit_log", "--days", "10")
        self.assertFalse(AuditLogEntry.objects.filter(pk=entry.pk).exists())


class CreateAuditPartitionCommandTests(TestCase):
    def _partition_exists(self, name):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
            return cursor.fetchone()[0]

    def test_creates_partition_for_given_year(self):
        from django.core.management import call_command

        call_command("create_audit_partition", "--year", "2030")
        self.assertTrue(self._partition_exists("audit_auditlogentry_2030"))

    def test_idempotent_rerun_does_not_error(self):
        from django.core.management import call_command

        call_command("create_audit_partition", "--year", "2031")
        call_command("create_audit_partition", "--year", "2031")
        self.assertTrue(self._partition_exists("audit_auditlogentry_2031"))

    def test_defaults_to_next_calendar_year(self):
        from django.core.management import call_command

        expected_year = timezone.now().year + 1
        call_command("create_audit_partition")
        self.assertTrue(self._partition_exists(f"audit_auditlogentry_{expected_year}"))


class HashChainTests(TestCase):
    def setUp(self):
        self.url = reverse("audit:list")
        self.superadmin = make_user(User.Role.SUPERADMIN)

    def _make(self, **overrides):
        from apps.audit.integrity import append_with_chain

        fields = dict(actor_username="x", action="findings:create", method="POST", path="/x/", status_code=200)
        fields.update(overrides)
        return append_with_chain(**fields)

    def test_first_entry_chains_from_genesis(self):
        from apps.audit.integrity import GENESIS_HASH, compute_entry_hash

        entry = self._make()
        self.assertEqual(entry.entry_hash, compute_entry_hash(entry, GENESIS_HASH))

    def test_each_entry_chains_onto_the_previous_ones_hash(self):
        from apps.audit.integrity import compute_entry_hash

        first = self._make()
        second = self._make(action="findings:edit")
        third = self._make(action="findings:archive")

        self.assertEqual(second.entry_hash, compute_entry_hash(second, first.entry_hash))
        self.assertEqual(third.entry_hash, compute_entry_hash(third, second.entry_hash))
        self.assertNotEqual(first.entry_hash, second.entry_hash)

    def test_verify_command_succeeds_on_untampered_chain(self):
        from django.core.management import call_command
        from io import StringIO

        self._make()
        self._make()
        self._make()

        out = StringIO()
        call_command("verify_audit_log", stdout=out)
        self.assertIn("Verified 3 audit log entries", out.getvalue())

    def test_verify_command_reports_empty_log(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("verify_audit_log", stdout=out)
        self.assertIn("empty", out.getvalue())

    def test_verify_command_detects_a_tampered_field(self):
        from django.core.management import CommandError, call_command

        self._make()
        second = self._make()
        self._make()

        AuditLogEntry.objects.filter(pk=second.pk).update(path="/something/else/")

        with self.assertRaises(CommandError):
            call_command("verify_audit_log")

    def test_verify_command_detects_a_hash_rewritten_to_match_a_tampered_field(self):
        from apps.audit.integrity import compute_entry_hash
        from django.core.management import CommandError, call_command

        first = self._make()
        second = self._make()
        third = self._make()

        second.refresh_from_db()
        tampered_hash = compute_entry_hash(
            AuditLogEntry.objects.get(pk=second.pk), first.entry_hash
        )
        AuditLogEntry.objects.filter(pk=second.pk).update(path="/something/else/", entry_hash=tampered_hash)

        with self.assertRaises(CommandError):
            call_command("verify_audit_log")

    def test_purged_history_leaves_a_verifiable_anchor_not_a_failure(self):
        from django.core.management import call_command
        from io import StringIO

        first = self._make()
        second = self._make()
        AuditLogEntry.objects.filter(pk=first.pk).delete()

        out = StringIO()
        call_command("verify_audit_log", stdout=out)
        self.assertIn(f"Entry {second.pk}: anchor", out.getvalue())
        self.assertIn("purged", out.getvalue())

    def test_hash_is_keyed_with_secret_key_not_forgeable_from_row_data_alone(self):
        from django.test import override_settings

        from apps.audit.integrity import GENESIS_HASH, compute_entry_hash

        entry = self._make()

        with override_settings(SECRET_KEY="a-different-secret-key-entirely"):
            forged = compute_entry_hash(entry, GENESIS_HASH)

        self.assertNotEqual(entry.entry_hash, forged)

    def test_real_request_through_middleware_is_chained(self):
        client = Client()
        login(client, self.superadmin)
        client.get(self.url)

        entry = AuditLogEntry.objects.filter(action="audit:list").latest("created_at")
        self.assertTrue(entry.entry_hash)
