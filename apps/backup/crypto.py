import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from apps.crypto.services import decrypt_bytes, encrypt_bytes

MAGIC = b"RSBK1"
SALT_LENGTH_BYTES = 16
KEY_LENGTH_BYTES = 32
PBKDF2_ITERATIONS = 600_000


class BackupDecryptionError(Exception):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=KEY_LENGTH_BYTES, salt=salt, iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_backup(raw: bytes, passphrase: str) -> bytes:
    salt = os.urandom(SALT_LENGTH_BYTES)
    key = _derive_key(passphrase, salt)
    return MAGIC + salt + encrypt_bytes(raw, key)


def decrypt_backup(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise BackupDecryptionError("Not a RedScribe backup file (bad header).")

    salt = blob[len(MAGIC):len(MAGIC) + SALT_LENGTH_BYTES]
    ciphertext_blob = blob[len(MAGIC) + SALT_LENGTH_BYTES:]
    key = _derive_key(passphrase, salt)
    try:
        return decrypt_bytes(ciphertext_blob, key)
    except Exception as exc:
        raise BackupDecryptionError("Wrong passphrase, or the file is corrupted.") from exc
