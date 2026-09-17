from django.core.management.base import BaseCommand, CommandError

from apps.audit.integrity import GENESIS_HASH, compute_entry_hash
from apps.audit.models import AuditLogEntry


class Command(BaseCommand):
    help = "Verify the audit log's hash chain hasn't been tampered with."

    def handle(self, *args, **options):
        entries = AuditLogEntry.objects.order_by("pk").iterator()

        checked = 0
        prev_hash = None
        for entry in entries:
            checked += 1
            if prev_hash is None:
                if not entry.entry_hash:
                    raise CommandError(f"Entry {entry.pk} has no hash at all — was it ever chained?")
                anchor_note = (
                    " (genesis)"
                    if entry.entry_hash == compute_entry_hash(entry, GENESIS_HASH)
                    else " (oldest surviving row — earlier history may have been purged, not a failure)"
                )
                self.stdout.write(f"Entry {entry.pk}: anchor{anchor_note}")
                prev_hash = entry.entry_hash
                continue

            expected = compute_entry_hash(entry, prev_hash)
            if entry.entry_hash != expected:
                raise CommandError(
                    f"Entry {entry.pk} failed verification — stored hash does not match its "
                    f"recomputed hash. Either this row or an earlier one was modified outside "
                    "apps.audit.integrity.append_with_chain."
                )
            prev_hash = entry.entry_hash

        if checked == 0:
            self.stdout.write("Audit log is empty — nothing to verify.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Verified {checked} audit log entries — chain is intact."))
