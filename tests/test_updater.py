"""Tests for the hardened auto-updater.

These tests DO NOT hit the network. They exercise:
  * version parsing and ordering
  * manifest dataclass parsing
  * Ed25519 signature verify (happy path)
  * Ed25519 signature verify (bad sig, wrong key, unsigned, tampered fields)
  * mandatory-sha256 enforcement
  * user-consent interlock on launch_installer_and_exit
"""
from __future__ import annotations
import base64
import json
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app import updater
from app.updater import (
    Manifest, UpdateError,
    parse_version, is_newer,
    _canonical_signed_blob, verify_manifest_signature,
    launch_installer_and_exit,
)


# ---------- helpers ----------

def _new_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub.hex()


def _sign(priv, data: dict) -> dict:
    data = dict(data)  # copy
    blob = _canonical_signed_blob(data)
    data["signature"] = base64.b64encode(priv.sign(blob)).decode("ascii")
    return data


@pytest.fixture
def signed_manifest(monkeypatch):
    """Install a fresh release keypair into the module for the duration
    of the test, and return (priv, signed_manifest_dict)."""
    priv, pub_hex = _new_keypair()
    monkeypatch.setattr(updater, "_RELEASE_PUBKEY_HEX", pub_hex)
    base = {
        "version": "1.4.0",
        "url": "https://shop.upfrontautorepair207.com/UpFrontShopSetup-1.4.0.exe",
        "sha256": "a" * 64,
        "notes": "Test release.",
        "required": False,
        "min_version": "",
    }
    return priv, _sign(priv, base)


# ---------- version parsing ----------

def test_parse_version_basic():
    assert parse_version("1.4.0") == (1, 4, 0)
    assert parse_version("1.4") == (1, 4)
    assert parse_version("1.4.0-beta.2") == (1, 4, 0, 0, 2)


def test_parse_version_empty():
    assert parse_version("") == (0,)


def test_is_newer_true_false():
    assert is_newer("1.4.0", local="1.3.5") is True
    assert is_newer("1.3.0", local="1.3.0") is False
    assert is_newer("1.3.0", local="1.3.1") is False


# ---------- manifest dataclass ----------

def test_manifest_from_json():
    m = Manifest.from_json({
        "version": "1.4.0",
        "url": "https://x/y.exe",
        "sha256": "A" * 64,   # note uppercase — should normalise
        "signature": "xxx",
        "notes": "hi",
        "required": True,
    })
    assert m.version == "1.4.0"
    assert m.sha256 == "a" * 64
    assert m.required is True


# ---------- signature verification ----------

def test_verify_good_signature(signed_manifest):
    _, data = signed_manifest
    verify_manifest_signature(data)  # should not raise


def test_verify_unsigned_is_rejected(monkeypatch):
    _, pub_hex = _new_keypair()
    monkeypatch.setattr(updater, "_RELEASE_PUBKEY_HEX", pub_hex)
    with pytest.raises(UpdateError, match="unsigned"):
        verify_manifest_signature({
            "version": "1.4.0",
            "url": "https://x/y.exe",
            "sha256": "a" * 64,
        })


def test_verify_bad_base64_is_rejected(signed_manifest):
    _, data = signed_manifest
    data["signature"] = "not-valid-base64!!!"
    with pytest.raises(UpdateError, match="base64"):
        verify_manifest_signature(data)


def test_verify_wrong_key_is_rejected(signed_manifest, monkeypatch):
    _, data = signed_manifest
    # Rotate the pubkey to a different one — signature should no longer verify.
    _, other_pub = _new_keypair()
    monkeypatch.setattr(updater, "_RELEASE_PUBKEY_HEX", other_pub)
    with pytest.raises(UpdateError, match="signature is invalid"):
        verify_manifest_signature(data)


def test_verify_tampered_field_is_rejected(signed_manifest):
    priv, data = signed_manifest
    # Attacker swaps the download URL after signing.
    data["url"] = "https://evil.example/pwn.exe"
    with pytest.raises(UpdateError, match="signature is invalid"):
        verify_manifest_signature(data)


def test_verify_tampered_sha_is_rejected(signed_manifest):
    _, data = signed_manifest
    data["sha256"] = "b" * 64
    with pytest.raises(UpdateError, match="signature is invalid"):
        verify_manifest_signature(data)


def test_verify_placeholder_pubkey_is_fail_closed(monkeypatch):
    # A build that forgot to paste the real key in must refuse to update.
    monkeypatch.setattr(updater, "_RELEASE_PUBKEY_HEX", "0" * 64)
    with pytest.raises(UpdateError, match="not configured"):
        verify_manifest_signature({
            "version": "1.4.0",
            "url": "https://x/y.exe",
            "sha256": "a" * 64,
            "signature": base64.b64encode(b"x" * 64).decode(),
        })


# ---------- consent interlock ----------

def test_launch_installer_requires_consent(tmp_path):
    fake = tmp_path / "installer.exe"
    fake.write_bytes(b"MZ")  # pretend it's a PE file
    with pytest.raises(UpdateError, match="consent"):
        launch_installer_and_exit(fake, user_consent=False)


def test_launch_installer_missing_file_raises(tmp_path):
    with pytest.raises(UpdateError, match="Installer missing"):
        launch_installer_and_exit(tmp_path / "nope.exe", user_consent=True)
