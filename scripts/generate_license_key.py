#!/usr/bin/env python3
"""
Signs a RedScribe commercial license key with your Ed25519 SSH private key.

Run this ONLY on your own machine, never inside the deployed app or CI —
the private key must never leave wherever it already lives (e.g. ~/.ssh).
This script reads it locally, signs a license payload, and prints the
signed license key string. That string is the only thing that gets handed
to the customer; the private key itself never appears in its output.

Usage:
    python scripts/generate_license_key.py --org "ACME Corp" --key ~/.ssh/id_ed25519
    python scripts/generate_license_key.py --org "ACME Corp" --duration-days 30   # e.g. a trial

The corresponding PUBLIC key must match settings.LICENSE_SIGNING_PUBLIC_KEY
in every deployed instance that should be able to verify keys this script
signs (see config/settings/base.py) — it already does for RedScribe's
current signing key.
"""
import argparse
import datetime
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.licensing.payload import canonical_payload_bytes, encode_license_key  # noqa: E402


def load_private_key(key_path: Path):
    from cryptography.hazmat.primitives.serialization import load_ssh_private_key

    key_bytes = key_path.read_bytes()
    try:
        return load_ssh_private_key(key_bytes, password=None)
    except Exception:
        password = getpass.getpass(f"Passphrase for {key_path}: ").encode()
        return load_ssh_private_key(key_bytes, password=password)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True, help="Organization name to license (shown in the app footer).")
    parser.add_argument(
        "--key", default=str(Path.home() / ".ssh" / "id_ed25519"),
        help="Path to your Ed25519 SSH private key (default: ~/.ssh/id_ed25519).",
    )
    parser.add_argument(
        "--type", default="commercial", choices=["commercial", "community"],
        help="License type recorded in the payload (default: commercial).",
    )
    parser.add_argument(
        "--duration-days", type=int, default=365,
        help="How many days from today the subscription runs (default: 365, i.e. a standard annual term).",
    )
    args = parser.parse_args()

    private_key = load_private_key(Path(args.key).expanduser())

    issued_date = datetime.date.today()
    issued = issued_date.isoformat()
    expires = (issued_date + datetime.timedelta(days=args.duration_days)).isoformat()
    payload_bytes = canonical_payload_bytes(org=args.org, issued=issued, expires=expires, license_type=args.type)
    signature = private_key.sign(payload_bytes)
    license_key = encode_license_key(payload_bytes, signature)

    print(f"\nLicense key for {args.org!r} (issued {issued}, expires {expires}):\n")
    print(license_key)
    print("\nHand this string to the customer to paste into Superadmin → Licensing.\n")


if __name__ == "__main__":
    main()
