import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.exceptions import ImproperlyConfigured

ROOT_KEY_ENV_VAR = "REDSCRIBE_ROOT_KEY"
ROOT_KEY_FILE_ENV_VAR = "REDSCRIBE_ROOT_KEY_FILE"
DEFAULT_ROOT_KEY_FILE = "/run/secrets/redscribe_root_key"
KEY_LENGTH_BYTES = 32
NONCE_LENGTH_BYTES = 12


class RootKeyUnavailable(ImproperlyConfigured):
    pass


class RootKeyProvider:
    def __init__(self):
        self._key: bytes | None = None

    def _read_raw(self) -> str | None:
        # Docker-secret convention: a mounted file beats the env var, since
        # `docker inspect`/`/proc/<pid>/environ` can leak an env var to any
        # root/same-UID process on the host, while a secret file's access is
        # controlled by the mount itself. `REDSCRIBE_ROOT_KEY` remains the
        # fallback for bare-metal/CI setups with no Docker secret to mount.
        file_path = os.environ.get(ROOT_KEY_FILE_ENV_VAR, DEFAULT_ROOT_KEY_FILE)
        if file_path and os.path.isfile(file_path):
            with open(file_path) as f:
                return f.read().strip()
        return os.environ.get(ROOT_KEY_ENV_VAR)

    def _load(self) -> bytes:
        raw = self._read_raw()
        if not raw:
            raise RootKeyUnavailable(
                f"No root key found. Generate one with `python manage.py "
                f"generate_root_key`, then either mount it as a Docker secret "
                f"(see docker-compose.yml) or set {ROOT_KEY_ENV_VAR} in the "
                "deployment environment before any encrypted data can be "
                "read or written."
            )
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise RootKeyUnavailable(f"{ROOT_KEY_ENV_VAR} is not valid base64.") from exc
        if len(key) != KEY_LENGTH_BYTES:
            raise RootKeyUnavailable(
                f"{ROOT_KEY_ENV_VAR} must decode to exactly {KEY_LENGTH_BYTES} bytes "
                f"(got {len(key)}). Generate a fresh one with `python manage.py generate_root_key`."
            )
        return key

    @property
    def key(self) -> bytes:
        if self._key is None:
            self._key = self._load()
        return self._key

    def wrap(self, plaintext_key: bytes, *, associated_data: bytes) -> bytes:
        nonce = os.urandom(NONCE_LENGTH_BYTES)
        aesgcm = AESGCM(self.key)
        ciphertext = aesgcm.encrypt(nonce, plaintext_key, associated_data)
        return nonce + ciphertext

    def unwrap(self, wrapped: bytes, *, associated_data: bytes) -> bytes:
        nonce, ciphertext = wrapped[:NONCE_LENGTH_BYTES], wrapped[NONCE_LENGTH_BYTES:]
        aesgcm = AESGCM(self.key)
        try:
            return aesgcm.decrypt(nonce, ciphertext, associated_data)
        except InvalidTag:
            raise


root_key_provider = RootKeyProvider()
