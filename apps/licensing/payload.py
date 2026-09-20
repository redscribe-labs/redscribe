import base64
import json


def canonical_payload_bytes(org: str, issued: str, expires: str, license_type: str = "commercial") -> bytes:
    data = {"org": org, "issued": issued, "expires": expires, "type": license_type}
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def encode_license_key(payload_bytes: bytes, signature: bytes) -> str:
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64(payload_bytes)}.{b64(signature)}"


def decode_license_key(key_text: str) -> tuple[bytes, bytes]:
    payload_b64, _, sig_b64 = key_text.strip().partition(".")
    if not payload_b64 or not sig_b64:
        raise ValueError("Malformed license key — expected '<payload>.<signature>'.")

    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    return unb64(payload_b64), unb64(sig_b64)
