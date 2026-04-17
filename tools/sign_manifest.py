"""Sign an Up Front Shop update manifest.

Usage:
    python tools/sign_manifest.py \\
        --key release_signing_key.pem \\
        --in  latest.json \\
        --out latest.json

Typical release workflow:
    1. Build UpFrontShopSetup-<ver>.exe.
    2. certutil -hashfile UpFrontShopSetup-<ver>.exe SHA256
    3. Author an unsigned latest.json with the fields:
           version, url, sha256, notes, required (optional),
           min_version (optional)
    4. Run this tool — it adds a `signature` field in place.
    5. Upload UpFrontShopSetup-<ver>.exe and the signed latest.json
       to the webhost.

The signature covers a canonical, sort_keys, whitespace-free JSON of
these fields (must match what the client re-computes):
    version, url, sha256, notes, required, min_version

Any field not in that list — e.g. human comments, server-side metadata
— is NOT protected by the signature, so the server can add them but
they're untrusted on the client.
"""
from __future__ import annotations
import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


SIGNED_FIELDS = ("version", "url", "sha256", "notes", "required", "min_version")


def canonical_signed_blob(data: dict) -> bytes:
    signed = {k: data[k] for k in SIGNED_FIELDS if k in data}
    return json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True, help="Path to Ed25519 private key PEM (PKCS8, no passphrase).")
    ap.add_argument("--in", dest="infile", required=True, help="Path to unsigned manifest JSON.")
    ap.add_argument("--out", required=True, help="Path to write signed manifest.")
    args = ap.parse_args()

    key_path = Path(args.key)
    in_path = Path(args.infile)
    out_path = Path(args.out)

    if not key_path.is_file():
        print(f"ERROR: private key not found: {key_path}", file=sys.stderr)
        return 2
    if not in_path.is_file():
        print(f"ERROR: input manifest not found: {in_path}", file=sys.stderr)
        return 2

    priv = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(priv, ed25519.Ed25519PrivateKey):
        print("ERROR: private key is not an Ed25519 key.", file=sys.stderr)
        return 2

    data = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("ERROR: manifest must be a JSON object.", file=sys.stderr)
        return 2

    # Refuse to sign nonsense — catches typos before they hit the shop.
    for required in ("version", "url", "sha256"):
        if not data.get(required):
            print(f"ERROR: manifest is missing required field `{required}`.", file=sys.stderr)
            return 2

    sha = str(data["sha256"]).strip().lower()
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
        print("ERROR: `sha256` must be a 64-char lowercase hex string.", file=sys.stderr)
        return 2
    data["sha256"] = sha

    url = str(data["url"])
    if not url.lower().startswith("https://"):
        print("ERROR: `url` must be https://", file=sys.stderr)
        return 2

    blob = canonical_signed_blob(data)
    sig = priv.sign(blob)
    data["signature"] = base64.b64encode(sig).decode("ascii")

    out_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Signed manifest written to {out_path}.")
    print("Upload this to your webhost as latest.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
