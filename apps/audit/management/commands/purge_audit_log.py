from django.conf import settings
from django.core.management.base import BaseCommand

from apps.audit.retention import count_older_than, purge_older_than


class Command(BaseCommand):
    help = "Delete audit log / login attempt entries older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=None,
            help=f"Override settings.AUDIT_LOG_RETENTION_DAYS ({settings.AUDIT_LOG_RETENTION_DAYS}).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report how many rows would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        effective_days = settings.AUDIT_LOG_RETENTION_DAYS if days is None else days

        if options["dry_run"]:
            counts = count_older_than(days)
            self.stdout.write(
                f"Would delete {counts['audit_log']} audit log entr{'y' if counts['audit_log'] == 1 else 'ies'} "
                f"and {counts['login_attempts']} login attempt(s) older than {effective_days} days."
            )
            return

        counts = purge_older_than(days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {counts['audit_log']} audit log entr{'y' if counts['audit_log'] == 1 else 'ies'} "
                f"and {counts['login_attempts']} login attempt(s) older than {effective_days} days."
            )
        )
