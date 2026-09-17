import base64
import os

from django.core.management.base import BaseCommand

from apps.crypto.root_key import KEY_LENGTH_BYTES


class Command(BaseCommand):
    help = (
        "Generate a new instance root key (AES-256, base64-encoded). Run "
        "once per instance. Under Docker Compose, store the output in "
        "secrets/root_key.txt (see secrets/README.md); otherwise set it as "
        "REDSCRIBE_ROOT_KEY in your secrets manager / .env. Never commit "
        "it to version control. Losing this key makes every engagement's "
        "data permanently unrecoverable; rotating it requires re-wrapping "
        "every ProjectKey (see rotate_root_key)."
    )

    def handle(self, *args, **options):
        key = os.urandom(KEY_LENGTH_BYTES)
        encoded = base64.b64encode(key).decode("ascii")
        self.stdout.write(encoded)
        self.stderr.write(
            self.style.WARNING(
                "Store this in secrets/root_key.txt (Docker Compose) or as "
                "REDSCRIBE_ROOT_KEY (bare-metal/CI). It will not be shown again."
            )
        )
