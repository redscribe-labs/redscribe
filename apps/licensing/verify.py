import json

from django.conf import settings

from .payload import decode_license_key


def verify_license_key(key_text: str) -> dict | None:
    if not key_text or not key_text.strip():
        return None
    if not settings.LICENSE_SIGNING_PUBLIC_KEY:
        return None

    try:
        from cryptography.hazmat.primitives.serialization import load_ssh_public_key

        public_key = load_ssh_public_key(settings.LICENSE_SIGNING_PUBLIC_KEY.encode())
        payload_bytes, signature = decode_license_key(key_text)
        public_key.verify(signature, payload_bytes)
        return json.loads(payload_bytes)
    except Exception:
        return None
