import getpass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.backup.crypto import BackupDecryptionError, decrypt_backup, encrypt_backup
from apps.backup.impact import compute_account_impact
from apps.backup.pg import RestoreError, dump_database, restore_database
from apps.backup.storage import write_encrypted_backup_file

SAFETY_FILENAME_FORMAT = "redscribe-pre-restore-safety-%Y%m%d-%H%M%S.rsbk"


class Command(BaseCommand):
    help = "Restore a RedScribe backup, after reporting which accounts would change."

    def add_arguments(self, parser):
        parser.add_argument("backup_file", help="Path to a .rsbk backup file")
        parser.add_argument(
            "--passphrase",
            help="Backup encryption passphrase — prompted interactively (not echoed, never in argv) "
            "if omitted, which is the safer default on any shared host: a CLI argument is visible "
            "to other local users/processes via `ps`/`/proc/<pid>/cmdline` for as long as this "
            "process runs, and lands in shell history if typed interactively.",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Skip the interactive confirmation prompt (for scripted DR). "
            "The account-impact report is still computed and printed either way.",
        )

    def handle(self, *args, **options):
        path = options["backup_file"]
        passphrase = options["passphrase"] or getpass.getpass("Backup passphrase: ")

        try:
            with open(path, "rb") as f:
                blob = f.read()
        except OSError as exc:
            raise CommandError(f"Couldn't read {path}: {exc}")

        try:
            dump = decrypt_backup(blob, passphrase)
        except BackupDecryptionError as exc:
            raise CommandError(str(exc))

        self.stdout.write("Loading backup into a scratch database to compare accounts...")
        try:
            impact = compute_account_impact(dump)
        except RestoreError as exc:
            raise CommandError(f"Couldn't preview the backup: {exc}")

        self._print_impact(impact)

        if not options["yes"]:
            confirm = input("\nType 'restore' to overwrite the LIVE database, anything else to abort: ")
            if confirm.strip().lower() != "restore":
                self.stdout.write("Aborted — no changes made.")
                return

        self.stdout.write("Taking a safety snapshot of the current live database first...")
        try:
            safety_dump = dump_database()
        except RestoreError as exc:
            raise CommandError(
                f"Couldn't take a pre-restore safety snapshot, aborting before touching anything live: {exc}"
            )
        backup_dir = Path(settings.BACKUP_DIR)
        safety_filename = timezone.now().strftime(SAFETY_FILENAME_FORMAT)
        try:
            safety_path = write_encrypted_backup_file(
                encrypt_backup(safety_dump, passphrase), backup_dir, safety_filename
            )
        except OSError as exc:
            raise CommandError(
                f"Couldn't write the pre-restore safety snapshot, aborting before touching anything live: {exc}"
            )
        self.stdout.write(f"Safety snapshot written to {safety_path} — keep this until you've confirmed the restore.")

        self.stdout.write("Restoring...")
        try:
            restore_database(dump)
        except RestoreError as exc:
            raise CommandError(
                f"Restore failed partway through: {exc}\n"
                f"The database may now be in an inconsistent state — restore {safety_path} "
                "(same passphrase) to recover to how it was just before this attempt."
            )

        self.stdout.write(self.style.SUCCESS("Restore complete."))

    def _print_impact(self, impact):
        if not impact.has_changes:
            self.stdout.write(self.style.SUCCESS("\nNo account differences — restoring changes nothing about who can log in."))
            return

        self.stdout.write("")
        if impact.reactivated:
            self.stdout.write(self.style.WARNING(
                f"REACTIVATED — inactive now, but active in this backup ({len(impact.reactivated)}):"
            ))
            self.stdout.write(self.style.WARNING(
                "  These accounts would regain access. If any were deactivated on purpose "
                "(e.g. someone who left) since this backup was taken, restoring undoes that."
            ))
            for u in impact.reactivated:
                self.stdout.write(f"    - {u}")
        if impact.newly_deactivated:
            self.stdout.write(f"\nWould become inactive again ({len(impact.newly_deactivated)}):")
            for u in impact.newly_deactivated:
                self.stdout.write(f"    - {u}")
        if impact.disappearing:
            self.stdout.write(
                f"\nCreated after this backup, would be REMOVED by restoring ({len(impact.disappearing)}):"
            )
            for u in impact.disappearing:
                self.stdout.write(f"    - {u}")
        if impact.reappearing:
            self.stdout.write(
                f"\nDeleted since this backup, would REAPPEAR by restoring ({len(impact.reappearing)}):"
            )
            for u in impact.reappearing:
                self.stdout.write(f"    - {u}")
