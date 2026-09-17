import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.exceptions import PermissionDenied

from .models import ProjectKey
from .root_key import NONCE_LENGTH_BYTES, root_key_provider

DATA_KEY_LENGTH_BYTES = 32


def _engagement_aad(engagement) -> bytes:
    return f"engagement:{engagement.pk}".encode()


def generate_project_key(engagement) -> ProjectKey:
    if ProjectKey.objects.filter(engagement=engagement).exists():
        raise ValueError(f"Engagement {engagement.pk} already has a ProjectKey.")

    raw_key = secrets.token_bytes(DATA_KEY_LENGTH_BYTES)
    wrapped = root_key_provider.wrap(raw_key, associated_data=_engagement_aad(engagement))
    return ProjectKey.objects.create(engagement=engagement, wrapped_key=wrapped)


def get_data_key(engagement) -> bytes:
    try:
        project_key = engagement.project_key
    except ProjectKey.DoesNotExist:
        raise PermissionDenied(f"Engagement {engagement.pk} has no ProjectKey.")

    try:
        return root_key_provider.unwrap(
            bytes(project_key.wrapped_key), associated_data=_engagement_aad(engagement)
        )
    except InvalidTag:
        raise PermissionDenied(f"ProjectKey for engagement {engagement.pk} failed integrity check.")


def record_aad(model_label: str, pk, field: str) -> bytes:
    return f"{model_label}:{pk}:{field}".encode()


def encrypt_bytes(plaintext: bytes, data_key: bytes, *, associated_data: bytes = b"") -> bytes:
    nonce = os.urandom(NONCE_LENGTH_BYTES)
    aesgcm = AESGCM(data_key)
    return nonce + aesgcm.encrypt(nonce, plaintext, associated_data or None)


def decrypt_bytes(blob: bytes, data_key: bytes, *, associated_data: bytes = b"") -> bytes:
    nonce, ciphertext = blob[:NONCE_LENGTH_BYTES], blob[NONCE_LENGTH_BYTES:]
    aesgcm = AESGCM(data_key)
    return aesgcm.decrypt(nonce, ciphertext, associated_data or None)


def decrypt_or_blank(blob, data_key: bytes, *, associated_data: bytes = b"") -> str:
    if not blob:
        return ""
    return decrypt_bytes(bytes(blob), data_key, associated_data=associated_data).decode("utf-8")
