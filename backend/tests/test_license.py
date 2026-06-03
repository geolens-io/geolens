"""Tests for the signed-license entitlement layer (app.core.license + edition).

Hermetic: each test generates an ephemeral Ed25519 keypair, mints tokens
in-process, and verifies against the matching public key. No DB, no network.
The verifier trust root is the BUNDLED key file; tests pin it via the
``install_trusted_key`` fixture (a code-level override), never an env var.
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
        "GEOLENS_LICENSE_AUDIENCE",
        # No longer trusted (verifier key is bundled, not env) — clear anyway so
        # a stray value in the ambient env can't influence a test.
        "GEOLENS_LICENSE_PUBLIC_KEY",
        "GEOLENS_LICENSE_PUBLIC_KEY_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    saved = edition_mod._info
    yield
    edition_mod._info = saved


def _pub_pem(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


@pytest.fixture(scope="module")
def keypair() -> tuple[Ed25519PrivateKey, str]:
    """An Ed25519 (private key object, public-key PEM string)."""
    key = Ed25519PrivateKey.generate()
    return key, _pub_pem(key)


@pytest.fixture
def install_trusted_key(keypair, tmp_path, monkeypatch):
    """Pin the test keypair's public key as the bundled verifier trust root."""
    _key, pub = keypair
    path = tmp_path / "license_public_key.pem"
    path.write_text(pub)
    monkeypatch.setattr("app.core.license._TRUSTED_PUBLIC_KEY_PATH", path)
    return path


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
# Audience binding (P2: prevent cross-deployment token replay)
# --------------------------------------------------------------------------- #


def test_verify_audience_match(keypair):
    key, pub = keypair
    token = _mint(key, aud="deploy-123")
    assert verify_license_token(token, pub, audience="deploy-123") is not None


def test_verify_audience_mismatch(keypair):
    key, pub = keypair
    token = _mint(key, aud="deploy-123")
    assert verify_license_token(token, pub, audience="other-deploy") is None


def test_verify_audience_required_when_configured(keypair):
    key, pub = keypair
    token = _mint(key)  # no aud claim
    # Deployment expects an audience but the token carries none -> reject.
    assert verify_license_token(token, pub, audience="deploy-123") is None


def test_verify_no_audience_ignores_aud_claim(keypair):
    key, pub = keypair
    token = _mint(key, aud="deploy-123")  # token has aud; deployment sets none
    # Back-compat: a token with aud still passes when audience isn't enforced.
    assert verify_license_token(token, pub) is not None


# --------------------------------------------------------------------------- #
# Clock-skew leeway (P2)
# --------------------------------------------------------------------------- #


def test_verify_tolerates_clock_skew_within_leeway(keypair):
    key, pub = keypair
    now = datetime.now(UTC)
    # nbf 2 min in the future: within the 300s leeway, must still verify.
    token = jwt.encode(
        {
            "edition": "enterprise",
            "nbf": now + timedelta(seconds=120),
            "exp": now + timedelta(days=30),
        },
        key,
        algorithm="EdDSA",
    )
    assert verify_license_token(token, pub) is not None


def test_verify_rejects_beyond_leeway(keypair):
    key, pub = keypair
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "edition": "enterprise",
            "nbf": now + timedelta(seconds=900),  # 15 min > 300s leeway
            "exp": now + timedelta(days=30),
        },
        key,
        algorithm="EdDSA",
    )
    assert verify_license_token(token, pub) is None


# --------------------------------------------------------------------------- #
# load_license (token from env/file; key from the BUNDLED trust root only)
# --------------------------------------------------------------------------- #


def test_load_license_no_token(monkeypatch):
    assert load_license() is None


def test_load_license_token_but_no_bundled_key(monkeypatch, keypair):
    key, _pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key))
    # Trust root absent -> cannot verify -> None (community).
    monkeypatch.setattr(
        "app.core.license._TRUSTED_PUBLIC_KEY_PATH", _nonexistent_path()
    )
    assert load_license() is None


def test_load_license_valid(monkeypatch, keypair, install_trusted_key):
    key, _pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key, customer="EnvCo"))
    info = load_license()
    assert info is not None and info.customer == "EnvCo"


def test_load_license_token_from_file(
    monkeypatch, tmp_path, keypair, install_trusted_key
):
    key, _pub = keypair
    token_file = tmp_path / "license.key"
    token_file.write_text(_mint(key, customer="FileCo"))
    monkeypatch.setenv("GEOLENS_LICENSE_FILE", str(token_file))
    info = load_license()
    assert info is not None and info.customer == "FileCo"


def test_load_license_with_audience(monkeypatch, keypair, install_trusted_key):
    key, _pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key, aud="prod-eu"))
    monkeypatch.setenv("GEOLENS_LICENSE_AUDIENCE", "prod-eu")
    assert load_license() is not None
    # Wrong audience configured -> rejected.
    monkeypatch.setenv("GEOLENS_LICENSE_AUDIENCE", "prod-us")
    assert load_license() is None


def test_public_key_is_not_env_configurable(monkeypatch, install_trusted_key):
    """P1 regression: the verifier key is the bundled trust root only. An
    operator who supplies their own keypair via GEOLENS_LICENSE_PUBLIC_KEY(_FILE)
    plus a self-signed token must NOT reach enterprise — even with enforce on.
    """
    attacker = Ed25519PrivateKey.generate()  # NOT the installed trusted key
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(attacker, customer="Pirate"))
    monkeypatch.setenv("GEOLENS_LICENSE_PUBLIC_KEY", _pub_pem(attacker))  # ignored
    monkeypatch.setenv(
        "GEOLENS_LICENSE_PUBLIC_KEY_FILE", "/tmp/whatever.pem"
    )  # ignored
    monkeypatch.setenv("GEOLENS_LICENSE_ENFORCE", "true")
    assert load_license() is None
    ed = _init([])
    assert ed.is_enterprise() is False


# --------------------------------------------------------------------------- #
# init_edition integration
# --------------------------------------------------------------------------- #


def _init(extensions):
    import app.core.edition as edition_mod

    edition_mod.init_edition(extensions)
    return edition_mod


def test_init_licensed_grants_enterprise(monkeypatch, keypair, install_trusted_key):
    key, _pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key, customer="Licensed Inc"))
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


def test_init_enforce_allows_valid_license(monkeypatch, keypair, install_trusted_key):
    key, _pub = keypair
    monkeypatch.setenv("GEOLENS_LICENSE_ENFORCE", "true")
    monkeypatch.setenv("GEOLENS_LICENSE_KEY", _mint(key))
    ed = _init([])
    assert ed.is_enterprise() is True
    assert ed.get_edition().licensed is True


def test_init_env_community_override(monkeypatch):
    monkeypatch.setenv("GEOLENS_EDITION", "community")
    ed = _init(["enterprise"])  # extension present but env forces community
    assert ed.is_enterprise() is False


# --------------------------------------------------------------------------- #
# Runtime expiry (P1: a token valid at startup must stop unlocking at exp)
# --------------------------------------------------------------------------- #


def test_runtime_expiry_downgrades_to_community():
    import app.core.edition as edition_mod

    past = datetime.now(UTC) - timedelta(seconds=1)
    edition_mod._info = edition_mod.EditionInfo(
        edition="enterprise", licensed=True, expires_at=past
    )
    # No restart / re-init: is_enterprise() must reflect expiry on read.
    assert edition_mod.is_enterprise() is False
    assert edition_mod.get_edition().edition == "community"


def test_runtime_unexpired_license_stays_enterprise():
    import app.core.edition as edition_mod

    future = datetime.now(UTC) + timedelta(days=1)
    edition_mod._info = edition_mod.EditionInfo(
        edition="enterprise", licensed=True, expires_at=future
    )
    assert edition_mod.is_enterprise() is True


def _nonexistent_path():
    from pathlib import Path

    return Path("/nonexistent/geolens-license-public-key-should-not-exist.pem")
