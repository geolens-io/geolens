"""Tests for the signed-license entitlement layer (app.core.license + edition).

Hermetic: each test generates an ephemeral Ed25519 keypair, mints tokens
in-process, and verifies against the matching public key. No DB, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.license import load_license, verify_license_token


@pytest.fixture(autouse=True)
def _isolate_edition(monkeypatch):
    """Clear license/edition env and restore the edition singleton per test."""
    import app.core.edition as edition_mod

    for var in (
        "GEOLENS_EDITION",
        "GEOLENS_LICENSE_ENFORCE",
        "GEOLENS_LICENSE_KEY",
        "GEOLENS_LICENSE_FILE",
        "GEOLENS_LICENSE_PUBLIC_KEY",
        "GEOLENS_LICENSE_PUBLIC_KEY_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    saved = edition_mod._info
    yield
    edition_mod._info = saved


@pytest.fixture(scope="module")
def keypair() -> tuple[Ed25519PrivateKey, str]:
    """An Ed25519 (private key object, public-key PEM string)."""
    key = Ed25519PrivateKey.generate()
    pub_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return key, pub_pem


def _mint(
    private_key, *, exp_delta=timedelta(days=30), edition="enterprise", **extra
) -> str:
    payload = {"edition": edition, "exp": datetime.now(UTC) + exp_delta}
    payload.update(extra)
    return jwt.encode(payload, private_key, algorithm="EdDSA")


# --------------------------------------------------------------------------- #
# verify_license_token
# --------------------------------------------------------------------------- #


def test_verify_valid_token(keypair):
    key, pub = keypair
    token = _mint(
        key, customer="Acme", seats=250, license_id="lic-1", features=["scim"]
    )
    info = verify_license_token(token, pub)
    assert info is not None
    assert info.edition == "enterprise"
    assert info.customer == "Acme"
    assert info.seats == 250
    assert info.license_id == "lic-1"
    assert info.features == ("scim",)
    assert info.expires_at is not None and info.expires_at > datetime.now(UTC)


def test_verify_expired_token(keypair):
    key, pub = keypair
    token = _mint(key, exp_delta=timedelta(days=-1))
    assert verify_license_token(token, pub) is None


def test_verify_non_enterprise_edition(keypair):
    key, pub = keypair
    token = _mint(key, edition="community")
    assert verify_license_token(token, pub) is None


def test_verify_tampered_signature(keypair):
    key, pub = keypair
    token = _mint(key)
    header, payload, signature = token.split(".")
    # Flip the FIRST signature char (top 6 bits of byte 0 — always significant).
    # The LAST base64url char can carry unused padding bits, so flipping it may
    # decode to the same signature bytes and be a no-op.
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = f"{header}.{payload}.{flipped}"
    assert verify_license_token(tampered, pub) is None


def test_verify_forged_with_other_key(keypair):
    _key, pub = keypair
    attacker = Ed25519PrivateKey.generate()
    token = _mint(attacker)  # signed by a key the deployment doesn't trust
    assert verify_license_token(token, pub) is None


def test_verify_missing_exp(keypair):
    key, pub = keypair
    token = jwt.encode({"edition": "enterprise"}, key, algorithm="EdDSA")  # no exp
    assert verify_license_token(token, pub) is None


def test_verify_rejects_non_eddsa_algorithm(keypair):
    """Any non-EdDSA token must be rejected because the verifier pins
    algorithms=['EdDSA']. This is what defeats the classic alg-confusion
    downgrade (where an attacker re-signs with HS256 using the public key as an
    HMAC secret so the verifier validates it). PyJWT additionally refuses to
    *encode* with an asymmetric key as an HMAC secret, but the decisive control
    is our decode-side pinning — verified here with a plain HS256 token."""
    _key, pub = keypair
    hs_token = jwt.encode(
        {"edition": "enterprise", "exp": datetime.now(UTC) + timedelta(days=30)},
        "any-shared-secret",
        algorithm="HS256",
    )
    assert verify_license_token(hs_token, pub) is None


# --------------------------------------------------------------------------- #
# load_license (env / file resolution)
# --------------------------------------------------------------------------- #


def test_load_license_no_token(monkeypatch):
    assert load_license() is None


def test_load_license_token_but_no_public_key(monkeypatch, keypair):
    key, _pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key))
    # No public key configured -> cannot verify -> None (community).
    monkeypatch.setattr(
        "app.core.license._DEFAULT_PUBLIC_KEY_PATH", _nonexistent_path()
    )
    assert load_license() is None


def test_load_license_valid_via_env(monkeypatch, keypair):
    key, pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key, customer="EnvCo"))
    monkeypatch.setenv("GEOLENS_LICENSE_PUBLIC_KEY", pub)
    info = load_license()
    assert info is not None and info.customer == "EnvCo"


def test_load_license_from_files(monkeypatch, tmp_path, keypair):
    key, pub = keypair
    token_file = tmp_path / "license.key"
    token_file.write_text(_mint(key, customer="FileCo"))
    pub_file = tmp_path / "pub.pem"
    pub_file.write_text(pub)
    monkeypatch.setenv("GEOLENS_LICENSE_FILE", str(token_file))
    monkeypatch.setenv("GEOLENS_LICENSE_PUBLIC_KEY_FILE", str(pub_file))
    info = load_license()
    assert info is not None and info.customer == "FileCo"


# --------------------------------------------------------------------------- #
# init_edition integration
# --------------------------------------------------------------------------- #


def _init(extensions):
    import app.core.edition as edition_mod

    edition_mod.init_edition(extensions)
    return edition_mod


def test_init_licensed_grants_enterprise(monkeypatch, keypair):
    key, pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key, customer="Licensed Inc"))
    monkeypatch.setenv("GEOLENS_LICENSE_PUBLIC_KEY", pub)
    ed = _init([])
    assert ed.is_enterprise() is True
    info = ed.get_edition()
    assert info.licensed is True
    assert info.customer == "Licensed Inc"


def test_init_backcompat_extensions_enterprise_unlicensed(monkeypatch):
    """No license, no enforce: loaded extension still flips enterprise (legacy),
    but licensed=False marks it as honor-system."""
    ed = _init(["enterprise"])
    assert ed.is_enterprise() is True
    assert ed.get_edition().licensed is False


def test_init_enforce_blocks_extensions(monkeypatch):
    monkeypatch.setenv("GEOLENS_LICENSE_ENFORCE", "true")
    ed = _init(["enterprise"])
    assert ed.is_enterprise() is False  # bypass closed


def test_init_enforce_blocks_env_edition(monkeypatch):
    monkeypatch.setenv("GEOLENS_LICENSE_ENFORCE", "1")
    monkeypatch.setenv("GEOLENS_EDITION", "enterprise")
    ed = _init([])
    assert ed.is_enterprise() is False


def test_init_enforce_allows_valid_license(monkeypatch, keypair):
    key, pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_ENFORCE", "true")
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key))
    monkeypatch.setenv("GEOLENS_LICENSE_PUBLIC_KEY", pub)
    ed = _init([])
    assert ed.is_enterprise() is True
    assert ed.get_edition().licensed is True


def test_init_env_community_override(monkeypatch):
    monkeypatch.setenv("GEOLENS_EDITION", "community")
    ed = _init(["enterprise"])  # extension present but env forces community
    assert ed.is_enterprise() is False


def _nonexistent_path():
    from pathlib import Path

    return Path("/nonexistent/geolens-license-public-key-should-not-exist.pem")
