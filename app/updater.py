"""Auto-updater for Up Front Shop (Windows) — hardened edition.

Why the hardening
-----------------
The naive "download the .exe from a URL, run it" loop is a code-execution
primitive for anyone who can tamper with the URL. In our setting that
includes: a hijacked DNS record, an ISP that MITMs the shop wifi, a CMS
bug on the webhost, a lapsed domain registration, or a misconfigured CA.

Two independent controls stop all of those:

  1. The manifest carries a MANDATORY sha256 of the installer. An
     installer that doesn't match is thrown out.
  2. The manifest itself is signed with an Ed25519 private key that
     lives ONLY on Josh's build laptop (offline). The public key is
     compiled into this module. A manifest that doesn't verify is
     thrown out — even if it was served over https from the legit URL.

So a full webhost takeover is not enough to push malware. The attacker
would also need Josh's release signing key.

Protocol (wire format)
----------------------
The manifest JSON looks like:

    {
      "version": "1.4.0",
      "url":     "https://upfrontautorepair207.com/upfront-shop/UpFrontShopSetup-1.4.0.exe",
      "sha256":  "<64-char hex>",
      "notes":   "<release notes>",
      "required": false,
      "min_version": "1.0.0",          # optional
      "signature": "<base64 ed25519>"  # signs a canonical blob of the
                                        # fields above (sort_keys, no spaces)
    }

See tools/gen_release_key.py to create the keypair, and
tools/sign_manifest.py to sign an unsigned manifest before upload.

Release flow (see README.md for the full runbook):
  1. Bump APP_VERSION in app/__init__.py.
  2. Bump MyAppVersion in build/installer.iss.
  3. Run build\\build.bat — produces dist\\UpFrontShopSetup.exe.
  4. Compute SHA-256 of the installer:
         certutil -hashfile dist\\UpFrontShopSetup.exe SHA256
  5. Author latest.json with version/url/sha256/notes.
  6. Run: python tools\\sign_manifest.py --key <priv> --in latest.json --out latest-signed.json
  7. Upload UpFrontShopSetup-<ver>.exe + latest-signed.json (rename it to
     latest.json on the server) to the webhost.

Everything in this module uses only Python stdlib + `cryptography`.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from . import APP_VERSION


# ===================================================================
#                        RELEASE SIGNING KEY
# ===================================================================
# This is the 32-byte Ed25519 public key corresponding to the release
# signing key that lives on Josh's build laptop. Paste a real key here
# (hex, 64 chars) after running tools/gen_release_key.py.
#
# If this constant is left as the placeholder value, every signature
# verification will fail — which is the correct fail-closed behaviour
# for a dev build. Never ship to the shop laptop without a real key.
# ===================================================================
_RELEASE_PUBKEY_HEX: str = "890380fe558f93b78d47e30fc08f91ea3409dc299e97231f5c51db5e902cec74"

# Fields that go into the signed blob (in canonical order).
# Anything NOT in this list is not protected by the signature.
_SIGNED_FIELDS = ("version", "url", "sha256", "notes", "required", "min_version")


# --------------------------- Version compare ---------------------------

_VER_SPLIT = re.compile(r"[.\-+]")


def parse_version(s: str) -> tuple[int, ...]:
    """Parse '1.4.0' / '1.4.0-beta.2' / '1.4' into a sortable tuple.
    Non-numeric bits become 0 so numeric tails still sort correctly."""
    if not s:
        return (0,)
    parts = []
    for p in _VER_SPLIT.split(s.strip()):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


# --------------------------- Manifest ---------------------------

@dataclass
class Manifest:
    version: str
    url: str
    sha256: str                      # REQUIRED — no longer Optional
    signature: str                   # REQUIRED — base64 ed25519
    notes: str = ""
    required: bool = False
    min_version: str = ""

    @classmethod
    def from_json(cls, data: dict) -> "Manifest":
        return cls(
            version=str(data.get("version", "")).strip(),
            url=str(data.get("url", "")).strip(),
            sha256=str(data.get("sha256", "")).strip().lower(),
            signature=str(data.get("signature", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
            required=bool(data.get("required", False)),
            min_version=str(data.get("min_version", "")).strip(),
        )


class UpdateError(Exception):
    """Any failure in the update pipeline — network, parse, hash, or
    signature. Callers should treat every UpdateError as 'do not run
    anything'."""
    pass


# --------------------------- Signature verification ---------------------------

def _canonical_signed_blob(data: dict) -> bytes:
    """Byte representation of the fields the signature covers. Must be
    IDENTICAL on the signer and verifier sides — hence sort_keys and no
    whitespace."""
    signed = {k: data[k] for k in _SIGNED_FIELDS if k in data}
    return json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _release_pubkey() -> ed25519.Ed25519PublicKey:
    """Decode the compiled-in public key. Raises UpdateError if the
    constant is still the placeholder value or is malformed — that's a
    fail-closed guard against a dev build accidentally going live."""
    if not _RELEASE_PUBKEY_HEX or set(_RELEASE_PUBKEY_HEX) <= {"0"}:
        raise UpdateError(
            "Release public key is not configured in this build. "
            "This is a safety interlock — no updates can be verified."
        )
    try:
        raw = bytes.fromhex(_RELEASE_PUBKEY_HEX)
    except ValueError:
        raise UpdateError("Release public key is not valid hex.")
    if len(raw) != 32:
        raise UpdateError(
            f"Release public key is {len(raw)} bytes; expected 32 (Ed25519)."
        )
    try:
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)
    except Exception as e:
        raise UpdateError(f"Release public key is malformed: {e}")


def verify_manifest_signature(data: dict) -> None:
    """Raise UpdateError unless the manifest carries a valid Ed25519
    signature made with the release private key over its canonical blob."""
    sig_b64 = data.get("signature", "")
    if not sig_b64:
        raise UpdateError("Manifest is unsigned — refusing to update.")
    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except Exception:
        raise UpdateError("Manifest signature is not valid base64.")
    pub = _release_pubkey()
    try:
        pub.verify(signature, _canonical_signed_blob(data))
    except InvalidSignature:
        raise UpdateError(
            "Manifest signature is invalid — refusing to update. "
            "Somebody may have tampered with the update feed."
        )


# --------------------------- Manifest fetch ---------------------------

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def fetch_manifest(url: str, timeout: int = 10) -> Manifest:
    """Pull the JSON manifest, verify its signature, verify shape, and
    return a Manifest. Raises UpdateError on any failure (network,
    parse, signature, missing fields, malformed sha256)."""
    if not url:
        raise UpdateError("No update URL configured.")
    if not url.lower().startswith("https://"):
        # Plain http:// is a MITM invitation. TLS is not sufficient on
        # its own (see the signature check below) but it raises the bar.
        raise UpdateError("Update URL must be https://")

    req = urllib.request.Request(url, headers={
        "User-Agent": f"UpFrontShop/{APP_VERSION}",
        "Cache-Control": "no-cache",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.URLError as e:
        raise UpdateError(f"Couldn't reach update server: {e.reason}")
    except Exception as e:
        raise UpdateError(f"Update check failed: {e}")

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as e:
        raise UpdateError(f"Manifest is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise UpdateError("Manifest is not a JSON object.")

    # CHECK SIGNATURE FIRST — don't trust any field before this passes.
    verify_manifest_signature(data)

    m = Manifest.from_json(data)

    # Shape checks — post-signature but pre-download.
    if not m.version:
        raise UpdateError("Manifest is missing `version`.")
    if not m.url or not m.url.lower().startswith("https://"):
        raise UpdateError("Manifest `url` must be https://")
    if not _SHA256_RE.match(m.sha256):
        raise UpdateError("Manifest `sha256` is missing or not a 64-char hex string.")
    return m


# --------------------------- Download + verify ---------------------------

def download_installer(
    url: str,
    expected_sha256: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: int = 120,
) -> Path:
    """Download the installer to a secure temp file, verify the sha256,
    return the path. Raises UpdateError on any failure. The sha256 is
    REQUIRED — callers must pass the hash from a signature-verified
    manifest. Never call this with None."""
    if not expected_sha256 or not _SHA256_RE.match(expected_sha256.lower()):
        raise UpdateError("Refusing to download without a valid sha256.")
    if not url.lower().startswith("https://"):
        raise UpdateError("Installer URL must be https://")

    req = urllib.request.Request(url, headers={
        "User-Agent": f"UpFrontShop/{APP_VERSION}",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:
        raise UpdateError(f"Couldn't start download: {e}")

    total = int(resp.headers.get("Content-Length") or 0)
    # Random temp name — predictable filenames (pid, ppid, etc.) invite
    # pre-staged-file races on shared machines.
    fd, tmp_str = tempfile.mkstemp(prefix="UpFrontShopSetup-", suffix=".exe")
    tmp = Path(tmp_str)
    h = hashlib.sha256()
    got = 0
    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress_cb:
                    progress_cb(got, total)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"Download interrupted: {e}")

    got_digest = h.hexdigest().lower()
    if got_digest != expected_sha256.lower():
        tmp.unlink(missing_ok=True)
        raise UpdateError(
            "Checksum mismatch — refusing to run installer.\n"
            f"  expected: {expected_sha256}\n"
            f"  got:      {got_digest}"
        )
    return tmp


# --------------------------- Launch + exit ---------------------------

def launch_installer_and_exit(
    installer: Path,
    *,
    user_consent: bool,
    silent: bool = True,
) -> None:
    """Run the downloaded installer and quit the app.

    `user_consent` is a REQUIRED keyword-only flag. Pass True ONLY after
    a human (Josh or a tech) has seen the version/notes and clicked
    'Install now' in the UI. Passing False — or forgetting to pass it —
    raises UpdateError. This is a paranoia interlock so that a future
    refactor can't accidentally wire up a silent auto-install path."""
    if not user_consent:
        raise UpdateError(
            "launch_installer_and_exit requires explicit user consent; "
            "the UI must confirm with a dialog before calling this."
        )

    installer = Path(installer)
    if not installer.is_file():
        raise UpdateError(f"Installer missing: {installer}")

    # Inno Setup silent flags:
    #   /VERYSILENT          — no installer UI
    #   /SUPPRESSMSGBOXES    — don't block on prompts
    #   /CLOSEAPPLICATIONS   — ask our process to exit
    #   /RESTARTAPPLICATIONS — re-launch after install
    #   /NORESTART           — don't reboot the laptop
    args = [str(installer)]
    if silent:
        args += ["/VERYSILENT", "/SUPPRESSMSGBOXES",
                 "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS",
                 "/NORESTART"]

    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            args, close_fds=True,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        )
    else:
        # Dev machine path — just shell-open so the flow is testable.
        subprocess.Popen(args, close_fds=True)

    sys.exit(0)


# --------------------------- Housekeeping ---------------------------

def cleanup_stale_installers(older_than_hours: int = 24) -> int:
    """Sweep %TEMP% for leftover UpFrontShopSetup-*.exe files and delete
    any older than `older_than_hours`. Safe to call on every launch.
    Returns the number of files deleted."""
    import time
    tmpdir = Path(tempfile.gettempdir())
    cutoff = time.time() - (older_than_hours * 3600)
    n = 0
    for p in tmpdir.glob("UpFrontShopSetup-*.exe"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                n += 1
        except OSError:
            pass
    return n


# --------------------------- Convenience ---------------------------

def summarize_manifest(m: Manifest, local: str = APP_VERSION) -> str:
    """User-facing blurb for the 'update is available' dialog."""
    lines = [
        "A new version of Up Front Shop is available.",
        "",
        f"  Installed version:  {local}",
        f"  New version:        {m.version}",
    ]
    if m.notes:
        lines += ["", "What's new:", m.notes]
    if m.required:
        lines += ["", "This update is marked REQUIRED by the shop admin."]
    return "\n".join(lines)
