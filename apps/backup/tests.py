import os
import subprocess
import tempfile
import time
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, TransactionTestCase, override_settings

from apps.accounts.models import Role

from .crypto import BackupDecryptionError, decrypt_backup, encrypt_backup

User = get_user_model()


def make_user(role, **kwargs):
    kwargs.setdefault("username", f"user-{role.lower()}-{os.urandom(4).hex()}")
    kwargs.setdefault("email", f"{kwargs['username']}@example.com")
    user = User.objects.create(
        role=Role.objects.get(slug=role.lower()), auth_type=User.AuthType.LOCAL, **kwargs
    )
    user.set_password("a-very-long-test-password-123!")
    user.save()
    return user


class BackupEnvelopeCryptoTests(TestCase):
    def test_round_trip(self):
        raw = b"PGDMP" + b"fake dump content"
        encrypted = encrypt_backup(raw, "correct horse battery staple")
        decrypted = decrypt_backup(encrypted, "correct horse battery staple")
        self.assertEqual(decrypted, raw)

    def test_wrong_passphrase_fails(self):
        encrypted = encrypt_backup(b"PGDMPdata", "right passphrase here")
        with self.assertRaises(BackupDecryptionError):
            decrypt_backup(encrypted, "wrong passphrase here")

    def test_garbage_input_rejected(self):
        with self.assertRaises(BackupDecryptionError):
            decrypt_backup(b"not a backup file at all", "whatever")

    def test_ciphertext_does_not_contain_plaintext(self):
        raw = b"PGDMP" + b"super secret finding content"
        encrypted = encrypt_backup(raw, "a passphrase")
        self.assertNotIn(b"super secret finding content", encrypted)


class CreateBackupCommandTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.backup_dir = Path(tempfile.mkdtemp())

    def test_writes_an_encrypted_backup_file(self):
        with override_settings(BACKUP_DIR=str(self.backup_dir)):
            call_command("create_backup", "--passphrase", "a-test-passphrase-123")

        files = list(self.backup_dir.glob("redscribe-backup-*.rsbk"))
        self.assertEqual(len(files), 1)

        decrypted = decrypt_backup(files[0].read_bytes(), "a-test-passphrase-123")
        self.assertTrue(decrypted.startswith(b"PGDMP"))

    def test_file_is_not_world_readable(self):
        with override_settings(BACKUP_DIR=str(self.backup_dir)):
            call_command("create_backup", "--passphrase", "a-test-passphrase-123")

        f = next(self.backup_dir.glob("redscribe-backup-*.rsbk"))
        mode = f.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_missing_passphrase_raises(self):
        with override_settings(BACKUP_DIR=str(self.backup_dir), BACKUP_ENCRYPTION_PASSPHRASE=""):
            with self.assertRaises(CommandError):
                call_command("create_backup")

    def test_backup_dir_is_created_not_world_readable(self):
        fresh_dir = self.backup_dir / "fresh-backup-dir"
        with override_settings(BACKUP_DIR=str(fresh_dir)):
            call_command("create_backup", "--passphrase", "a-test-passphrase-123")

        mode = fresh_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)

    def test_prune_tolerates_a_file_removed_concurrently(self):
        from unittest.mock import patch

        from apps.backup.management.commands.create_backup import Command

        stale = self.backup_dir / "redscribe-backup-20200101-000000.rsbk"
        stale.write_bytes(b"stale")
        os.utime(stale, (0, 0))

        def vanished(*args, **kwargs):
            raise FileNotFoundError()

        with patch.object(Path, "unlink", vanished):
            pruned = Command()._prune_old_backups(self.backup_dir)
        self.assertEqual(pruned, 0)

    def test_prunes_backups_older_than_retention(self):
        old_file = self.backup_dir / "redscribe-backup-20200101-000000.rsbk"
        old_file.write_bytes(b"whatever")
        old_time = time.time() - 40 * 86400
        os.utime(old_file, (old_time, old_time))

        with override_settings(BACKUP_DIR=str(self.backup_dir), BACKUP_RETENTION_DAYS=30):
            call_command("create_backup", "--passphrase", "a-test-passphrase-123")

        self.assertFalse(old_file.exists())
        self.assertEqual(len(list(self.backup_dir.glob("redscribe-backup-*.rsbk"))), 1)


class AccountImpactTests(TransactionTestCase):
    serialized_rollback = True

    def _dump(self):
        from apps.backup.pg import dump_database

        return dump_database()

    def test_deactivated_since_backup_shows_as_reactivated(self):
        from apps.backup.impact import compute_account_impact

        user = make_user(User.Role.CONSULTANT, username="soon-to-be-deactivated")
        dump = self._dump()

        user.is_active = False
        user.save()

        impact = compute_account_impact(dump)
        self.assertIn("soon-to-be-deactivated", impact.reactivated)
        self.assertTrue(impact.has_changes)

    def test_reactivated_since_backup_shows_as_newly_deactivated(self):
        from apps.backup.impact import compute_account_impact

        user = make_user(User.Role.CONSULTANT, username="was-inactive", is_active=False)
        dump = self._dump()

        user.is_active = True
        user.save()

        impact = compute_account_impact(dump)
        self.assertIn("was-inactive", impact.newly_deactivated)

    def test_account_created_after_backup_shows_as_disappearing(self):
        from apps.backup.impact import compute_account_impact

        dump = self._dump()
        make_user(User.Role.CONSULTANT, username="brand-new-hire")

        impact = compute_account_impact(dump)
        self.assertIn("brand-new-hire", impact.disappearing)

    def test_account_deleted_after_backup_shows_as_reappearing(self):
        from apps.backup.impact import compute_account_impact

        user = make_user(User.Role.CONSULTANT, username="deleted-later")
        dump = self._dump()
        user.delete()

        impact = compute_account_impact(dump)
        self.assertIn("deleted-later", impact.reappearing)

    def test_no_changes_reports_clean(self):
        from apps.backup.impact import compute_account_impact

        make_user(User.Role.CONSULTANT, username="unchanged-user")
        dump = self._dump()

        impact = compute_account_impact(dump)
        self.assertFalse(impact.has_changes)


class PgSubprocessErrorHandlingTests(TestCase):
    def test_timeout_becomes_a_restore_error(self):
        import subprocess
        from unittest.mock import patch

        from apps.backup.pg import RestoreError, dump_database

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=600)):
            with self.assertRaises(RestoreError):
                dump_database()

    def test_missing_binary_becomes_a_restore_error(self):
        from unittest.mock import patch

        from apps.backup.pg import RestoreError, dump_database

        with patch("subprocess.run", side_effect=FileNotFoundError("pg_dump: not found")):
            with self.assertRaises(RestoreError):
                dump_database()


class ComputeAccountImpactErrorHandlingTests(TestCase):
    def test_a_database_error_becomes_a_restore_error(self):
        import psycopg
        from unittest.mock import patch

        from apps.backup.impact import compute_account_impact
        from apps.backup.pg import RestoreError

        with patch("apps.backup.impact._admin_connect", side_effect=psycopg.OperationalError("connection refused")):
            with self.assertRaises(RestoreError):
                compute_account_impact(b"PGDMP" + b"\x00" * 16)


class RestoreBackupCommandTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.backup_dir = Path(tempfile.mkdtemp())
        self._override = override_settings(BACKUP_DIR=str(self.backup_dir))
        self._override.enable()
        self.addCleanup(self._override.disable)

    def test_yes_flag_skips_prompt_and_restores(self):
        from apps.backup.pg import dump_database

        make_user(User.Role.CONSULTANT, username="present-at-backup-time")
        dump = dump_database()
        encrypted = encrypt_backup(dump, "a-test-passphrase-123")

        tmp = Path(tempfile.mkdtemp()) / "test.rsbk"
        tmp.write_bytes(encrypted)

        make_user(User.Role.CONSULTANT, username="created-after-backup")

        out = StringIO()
        call_command("restore_backup", str(tmp), "--passphrase", "a-test-passphrase-123", "--yes", stdout=out)

        self.assertIn("Restore complete", out.getvalue())
        self.assertIn("REMOVED", out.getvalue())
        self.assertTrue(User.objects.filter(username="present-at-backup-time").exists())
        self.assertFalse(User.objects.filter(username="created-after-backup").exists())

    def test_takes_pre_restore_safety_snapshot_before_touching_live_db(self):
        from apps.backup.pg import dump_database

        make_user(User.Role.CONSULTANT, username="should-survive-in-safety-snapshot")
        dump = dump_database()
        encrypted = encrypt_backup(dump, "a-test-passphrase-123")
        tmp = Path(tempfile.mkdtemp()) / "test.rsbk"
        tmp.write_bytes(encrypted)

        out = StringIO()
        call_command("restore_backup", str(tmp), "--passphrase", "a-test-passphrase-123", "--yes", stdout=out)

        self.assertIn("Safety snapshot written to", out.getvalue())
        safety_files = list(self.backup_dir.glob("redscribe-pre-restore-safety-*.rsbk"))
        self.assertEqual(len(safety_files), 1)

        mode = safety_files[0].stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

        decrypted = decrypt_backup(safety_files[0].read_bytes(), "a-test-passphrase-123")
        rendered = subprocess.run(
            ["pg_restore", "-f", "-"], input=decrypted, capture_output=True, timeout=60,
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"should-survive-in-safety-snapshot", rendered.stdout)

    def test_wrong_passphrase_raises_without_restoring(self):
        from apps.backup.pg import dump_database

        dump = dump_database()
        encrypted = encrypt_backup(dump, "correct-passphrase-123")
        tmp = Path(tempfile.mkdtemp()) / "test.rsbk"
        tmp.write_bytes(encrypted)

        with self.assertRaises(CommandError):
            call_command("restore_backup", str(tmp), "--passphrase", "wrong-passphrase-123", "--yes")

        self.assertEqual(list(self.backup_dir.glob("redscribe-pre-restore-safety-*.rsbk")), [])

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            call_command("restore_backup", "/nonexistent/path.rsbk", "--passphrase", "x", "--yes")
