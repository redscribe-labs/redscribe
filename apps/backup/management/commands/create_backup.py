import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.backup.crypto import encrypt_backup
from apps.backup.pg import RestoreError, dump_database
from apps.backup.storage import write_encrypted_backup_file

FILENAME_FORMAT = "redscribe-backup-%Y%m%d-%H%M%S.rsbk"


class Command(BaseCommand):
    help = "Create an encrypted backup in settings.BACKUP_DIR and prune ones older than BACKUP_RETENTION_DAYS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--passphrase",
            help="Overrides settings.BACKUP_ENCRYPTION_PASSPHRASE for this run only. Prefer the env "
            "var (or, for restore_backup, the interactive prompt) on any host other than a fully "
            "single-tenant/trusted one — a CLI argument is visible to other local users/processes "
            "via `ps`/`/proc/<pid>/cmdline` for as long as this process runs, and lands in shell "
            "history if typed interactively.",
        )

    def handle(self, *args, **options):
        passphrase = options["passphrase"] or settings.BACKUP_ENCRYPTION_PASSPHRASE
        if not passphrase:
            raise CommandError(
                "No passphrase available — set BACKUP_ENCRYPTION_PASSPHRASE in .env "
                "(required for unattended/cron use) or pass --passphrase."
            )

        backup_dir = Path(settings.BACKUP_DIR)

        self.stdout.write("Dumping database...")
        try:
            dump = dump_database()
        except RestoreError as exc:
            raise CommandError(f"pg_dump failed: {exc}")

        encrypted = encrypt_backup(dump, passphrase)
        filename = timezone.now().strftime(FILENAME_FORMAT)
        path = write_encrypted_backup_file(encrypted, backup_dir, filename)

        self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({len(encrypted):,} bytes)."))

        pruned = self._prune_old_backups(backup_dir)
        if pruned:
            self.stdout.write(f"Pruned {pruned} backup(s) older than {settings.BACKUP_RETENTION_DAYS} days.")

    def _prune_old_backups(self, backup_dir: Path) -> int:
        cutoff = time.time() - settings.BACKUP_RETENTION_DAYS * 86400
        pruned = 0
        for entry in backup_dir.glob("redscribe-backup-*.rsbk"):
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    pruned += 1
            except FileNotFoundError:
                continue
        return pruned
