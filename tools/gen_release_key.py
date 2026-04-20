"""One-time keygen for the Up Front Shop release signing key.

Run this ONCE on the build laptop. It produces two files:

    release_signing_key.pem   — private key (KEEP SECRET, back up offline)
    release_public_key.hex    — public key (paste into app/updater.py)

Usage:
    python tools/gen_release_key.py

Important:
  * Never put release_signing_key.pem on the webhost.
  * Never email it. Never commit it to git.
  * Back it up to an offline USB drive kept with the shop safe or your
    accountant. If you lose this key, you can't sign updates — you'd
    have to ship a new app version carrying a replacement public key.
  * The public key is safe to share and IS intended to live inside the
    compiled app.
"""
from __future__ import annotations
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def main() -> int:
    out_priv = Path("release_signing_key.pem")
    out_pub = Path("release_public_key.hex")

    if out_priv.exists():
        print(f"ERROR: {out_priv} already exists. Refusing to overwrite.")
        print("If you really want a new key, move the old one aside first.")
        return 2

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    out_priv.write_bytes(priv_pem)
    # Lock permissions where the OS honours it.
    try:
        out_priv.chmod(0o600)
    except Exception:
        pass

    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_hex = pub_bytes.hex()
    out_pub.write_text(pub_hex + "\n")

    print("Generated Ed25519 release keypair.")
    print()
    print(f"  Private key : {out_priv}   (KEEP SECRET — back up offline)")
    print(f"  Public key  : {out_pub}")
    print()
    print("Paste the public key hex into app/updater.py:")
    print()
    print(f'    _RELEASE_PUBKEY_HEX: str = "{pub_hex}"')
    print()
    print("Then rebuild the app (build\\build.bat) to compile the public")
    print("key into the shipped binary. From that point on, only manifests")
    print("signed with the matching private key will be accepted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
