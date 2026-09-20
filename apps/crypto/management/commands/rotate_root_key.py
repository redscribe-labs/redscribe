import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.crypto.models import ProjectKey
from apps.crypto.root_key import KEY_LENGTH_BYTES, NONCE_LENGTH_BYTES, root_key_provider


class Command(BaseCommand):
    help = (
        "Rotate the instance root key: re-wraps every ProjectKey.wrapped_key "
        "under a NEW root key while the app is still configured with the OLD "
        "one (read via the normal RootKeyProvider). Run this BEFORE updating "
        "the deployed root key (secrets/root_key.txt or REDSCRIBE_ROOT_KEY) "
        "— once it succeeds, replace the deployed key with the same value "
        "passed to --new-key and restart. Per-field ciphertext (findings, "
        "checklist items, encrypted blobs, etc.) is untouched by this "
        "command — those stay protected by their own unchanged per-engagement "
        "data key, so only the (small) ProjectKey table is rewritten "
        "regardless of how much encrypted content exists. Take a full "
        "backup first (see apps.backup) and run during a maintenance window: "
        "an engagement whose ProjectKey is created *during* this command "
        "(via generate_project_key) is wrapped under whichever key was "
        "active at that moment, and this command only rotates rows that "
        "existed when it started."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--new-key",
            required=True,
            help="Base64-encoded 32-byte AES key, e.g. from `generate_root_key`.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        try:
            new_key = base64.b64decode(options["new_key"], validate=True)
        except Exception as exc:
            raise CommandError(f"--new-key is not valid base64: {exc}") from exc
        if len(new_key) != KEY_LENGTH_BYTES:
            raise CommandError(
                f"--new-key must decode to exactly {KEY_LENGTH_BYTES} bytes "
                f"(got {len(new_key)})."
            )

        try:
            root_key_provider.key
        except Exception as exc:
            raise CommandError(f"Could not load the current root key: {exc}") from exc

        dry_run = options["dry_run"]

        with transaction.atomic():
            project_keys = list(
                ProjectKey.objects.select_for_update().select_related("engagement")
            )
            if not project_keys:
                self.stdout.write("No ProjectKey rows found — nothing to rotate.")
                return

            rewrapped = []
            for pk in project_keys:
                aad = f"engagement:{pk.engagement_id}".encode()
                try:
                    raw = root_key_provider.unwrap(bytes(pk.wrapped_key), associated_data=aad)
                except InvalidTag:
                    raise CommandError(
                        f"ProjectKey for engagement {pk.engagement_id} failed to unwrap "
                        "under the current root key — aborting before any writes. Check "
                        "that the currently configured root key is the one this data was "
                        "wrapped under (no rows have been changed)."
                    )
                nonce = os.urandom(NONCE_LENGTH_BYTES)
                ciphertext = AESGCM(new_key).encrypt(nonce, raw, aad)
                rewrapped.append((pk, nonce + ciphertext))

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"[dry run] Would rotate {len(rewrapped)} ProjectKey row(s). "
                        "No changes made."
                    )
                )
                transaction.set_rollback(True)
                return

            for pk, wrapped in rewrapped:
                pk.wrapped_key = wrapped
                pk.key_version += 1
                pk.save(update_fields=["wrapped_key", "key_version"])

        self.stdout.write(self.style.SUCCESS(f"Rotated {len(rewrapped)} ProjectKey row(s)."))
        self.stderr.write(
            self.style.WARNING(
                "Now replace the deployed root key (secrets/root_key.txt or "
                "REDSCRIBE_ROOT_KEY) with the --new-key value and restart. Until "
                "you do, the app is still using the OLD key and will fail to "
                "unwrap these rows."
            )
        )
