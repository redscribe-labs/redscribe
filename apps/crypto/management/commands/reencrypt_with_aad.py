from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.checklist.models import ChecklistItem, ChecklistItemComment
from apps.crypto.models import EncryptedBlob
from apps.crypto.root_key import NONCE_LENGTH_BYTES
from apps.crypto.services import encrypt_bytes, get_data_key, record_aad
from apps.engagements.models import Engagement
from apps.findings.models import CommentEntry, CommentThread, FindingSection, RetestRecord


class Command(BaseCommand):
    help = (
        "One-time data migration: re-encrypts every "
        "EncryptedBlob and encrypted text field (finding sections, retest "
        "notes, comment threads/entries, checklist item results/comments) "
        "with its correct record-bound AAD. Idempotent — safe to run more "
        "than once, and safe to run against a live instance with in-flight "
        "requests, since each record is re-encrypted in its own transaction. "
        "Uses its own legacy-tolerant decrypt (tries the correct AAD first, "
        "falls back to no AAD only if that fails) rather than "
        "apps.crypto.services.decrypt_bytes, which is strict-AAD-only — that "
        "fallback was deliberately removed from the shared/hot decrypt path "
        "once this command's first run confirmed no live data needed it "
        "anymore, but stays here so this command can still handle a restore "
        "from a backup taken before that first run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Report counts without writing anything."
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        totals = {
            "blobs": 0,
            "finding_sections": 0,
            "retest_notes": 0,
            "comment_threads": 0,
            "comment_entries": 0,
            "checklist_results": 0,
            "checklist_comments": 0,
        }
        skipped_engagements = []

        for engagement in Engagement.objects.all():
            try:
                data_key = get_data_key(engagement)
            except Exception as exc:
                skipped_engagements.append(engagement.pk)
                self.stderr.write(
                    self.style.ERROR(
                        f"Skipping engagement {engagement.pk} ({engagement.client_name}): {exc}"
                    )
                )
                continue

            totals["blobs"] += self._reencrypt_blobs(engagement, data_key, dry_run)
            totals["finding_sections"] += self._reencrypt_finding_sections(engagement, data_key, dry_run)
            totals["retest_notes"] += self._reencrypt_retest_notes(engagement, data_key, dry_run)
            totals["comment_threads"] += self._reencrypt_comment_threads(engagement, data_key, dry_run)
            totals["comment_entries"] += self._reencrypt_comment_entries(engagement, data_key, dry_run)
            totals["checklist_results"] += self._reencrypt_checklist_results(engagement, data_key, dry_run)
            totals["checklist_comments"] += self._reencrypt_checklist_comments(engagement, data_key, dry_run)

        label = "[dry run] Would re-encrypt" if dry_run else "Re-encrypted"
        self.stdout.write(
            self.style.SUCCESS(f"{label}: " + ", ".join(f"{v} {k}" for k, v in totals.items()))
        )
        if skipped_engagements:
            self.stderr.write(
                self.style.ERROR(
                    f"{len(skipped_engagements)} engagement(s) skipped (no usable "
                    f"ProjectKey): {skipped_engagements}. Their records were NOT "
                    "touched — investigate and re-run."
                )
            )

    @staticmethod
    def _legacy_tolerant_decrypt(ciphertext, data_key: bytes, aad: bytes) -> bytes:
        raw = bytes(ciphertext)
        nonce, ct = raw[:NONCE_LENGTH_BYTES], raw[NONCE_LENGTH_BYTES:]
        aesgcm = AESGCM(data_key)
        try:
            return aesgcm.decrypt(nonce, ct, aad)
        except InvalidTag:
            return aesgcm.decrypt(nonce, ct, None)

    def _rewrap(self, ciphertext, data_key: bytes, aad: bytes) -> bytes:
        plaintext = self._legacy_tolerant_decrypt(ciphertext, data_key, aad)
        return encrypt_bytes(plaintext, data_key, associated_data=aad)

    @transaction.atomic
    def _reencrypt_blobs(self, engagement, data_key, dry_run) -> int:
        count = 0
        for blob in EncryptedBlob.objects.filter(engagement=engagement).select_for_update():
            aad = record_aad("encryptedblob", blob.id, "ciphertext")
            new_ciphertext = self._rewrap(blob.ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                blob.ciphertext = new_ciphertext
                blob.save(update_fields=["ciphertext"])
        return count

    @transaction.atomic
    def _reencrypt_finding_sections(self, engagement, data_key, dry_run) -> int:
        count = 0
        sections = (
            FindingSection.objects.filter(finding__engagement=engagement)
            .select_related("definition")
            .select_for_update()
        )
        for section in sections:
            aad = record_aad("finding", section.finding_id, section.definition.slug)
            new_ciphertext = self._rewrap(section.content_ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                section.content_ciphertext = new_ciphertext
                section.save(update_fields=["content_ciphertext"])
        return count

    @transaction.atomic
    def _reencrypt_retest_notes(self, engagement, data_key, dry_run) -> int:
        count = 0
        records = (
            RetestRecord.objects.filter(finding__engagement=engagement)
            .exclude(notes_ciphertext__isnull=True)
            .select_for_update()
        )
        for record in records:
            if not bytes(record.notes_ciphertext):
                continue
            aad = record_aad("retestrecord", record.pk, "notes")
            new_ciphertext = self._rewrap(record.notes_ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                record.notes_ciphertext = new_ciphertext
                record.save(update_fields=["notes_ciphertext"])
        return count

    @transaction.atomic
    def _reencrypt_comment_threads(self, engagement, data_key, dry_run) -> int:
        count = 0
        threads = CommentThread.objects.filter(finding__engagement=engagement).select_for_update()
        for thread in threads:
            aad = record_aad("commentthread", thread.pk, "anchored_text")
            new_ciphertext = self._rewrap(thread.anchored_text_ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                thread.anchored_text_ciphertext = new_ciphertext
                thread.save(update_fields=["anchored_text_ciphertext"])
        return count

    @transaction.atomic
    def _reencrypt_comment_entries(self, engagement, data_key, dry_run) -> int:
        count = 0
        entries = CommentEntry.objects.filter(thread__finding__engagement=engagement).select_for_update()
        for entry in entries:
            aad = record_aad("commententry", entry.pk, "body")
            new_ciphertext = self._rewrap(entry.body_ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                entry.body_ciphertext = new_ciphertext
                entry.save(update_fields=["body_ciphertext"])
        return count

    @transaction.atomic
    def _reencrypt_checklist_results(self, engagement, data_key, dry_run) -> int:
        count = 0
        items = (
            ChecklistItem.objects.filter(run__engagement=engagement)
            .exclude(test_results_ciphertext__isnull=True)
            .select_for_update()
        )
        for item in items:
            if not bytes(item.test_results_ciphertext):
                continue
            aad = record_aad("checklistitem", item.pk, "test_results")
            new_ciphertext = self._rewrap(item.test_results_ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                item.test_results_ciphertext = new_ciphertext
                item.save(update_fields=["test_results_ciphertext"])
        return count

    @transaction.atomic
    def _reencrypt_checklist_comments(self, engagement, data_key, dry_run) -> int:
        count = 0
        comments = ChecklistItemComment.objects.filter(
            checklist_item__run__engagement=engagement
        ).select_for_update()
        for comment in comments:
            aad = record_aad("checklistitemcomment", comment.pk, "body")
            new_ciphertext = self._rewrap(comment.body_ciphertext, data_key, aad)
            count += 1
            if not dry_run:
                comment.body_ciphertext = new_ciphertext
                comment.save(update_fields=["body_ciphertext"])
        return count
