"""Tests for SEC-S06 — validate_demo_credentials_guard refuses literal
committed values regardless of GEOLENS_DEMO_MODE.

Phase 1061 SEC-S06: the guard previously had an early-return when
GEOLENS_DEMO_MODE=true, which allowed operators to deploy
docker-compose.demo.yml verbatim (with known-public credentials) to a
public-internet host. This test file pins the extended behavior where all
three literal strings are refused unconditionally.
"""

import pytest
from pydantic import ValidationError

from app.core.config import (
    DEMO_ADMIN_PASSWORD,
    DEMO_JWT_SECRET,
    DEMO_POSTGRES_PASSWORD,
    Settings,
)

# Baseline of valid random-ish values that satisfy all validators.
# JWT_SECRET_KEY must be >= 32 chars (validate_jwt_secret_length).
_BASE = {
    "postgres_password": "random-pg-pw-32-chars-aaaaaaaaaaa",
    "jwt_secret_key": "random-jwt-secret-32-chars-bbbbbbb",
    "geolens_admin_username": "admin",
    "geolens_admin_password": "random-admin-pw-32",
    "geolens_demo_mode": False,
}


def _build(**overrides) -> Settings:
    """Construct Settings with sensible defaults, allowing overrides.

    Passes every required field as a kwarg to bypass the env_file fallback,
    so tests are isolated from the host's .env. Each call returns an
    independent Settings instance — the module-level ``settings`` singleton
    in ``app.config`` is never touched.
    """
    params = {**_BASE, **overrides}
    return Settings(**params)


# ─────────────────────────────────────────────────────────────────────────────
# JWT_SECRET_KEY literal — refused in BOTH modes
# ─────────────────────────────────────────────────────────────────────────────


def test_guard_refuses_demo_jwt_in_demo_mode():
    """Even with GEOLENS_DEMO_MODE=true, the literal demo JWT is refused.

    This is the headline SEC-S06 scenario: operator deploys
    docker-compose.demo.yml verbatim (GEOLENS_DEMO_MODE=true set by the
    overlay) but uses .env.demo.example without running init-demo-env.sh.
    """
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        _build(
            jwt_secret_key=DEMO_JWT_SECRET,
            geolens_demo_mode=True,
        )


def test_guard_refuses_demo_jwt_in_non_demo_mode():
    """In non-demo mode (legacy behavior preserved), the literal demo JWT is refused."""
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        _build(
            jwt_secret_key=DEMO_JWT_SECRET,
            geolens_demo_mode=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# GEOLENS_ADMIN_PASSWORD literal — refused in demo mode (was previously allowed)
# ─────────────────────────────────────────────────────────────────────────────


def test_guard_refuses_demo_admin_password_in_demo_mode():
    """The literal admin password ('demodemo') is refused even in demo mode."""
    with pytest.raises(ValidationError, match="GEOLENS_ADMIN_PASSWORD"):
        _build(
            geolens_admin_password=DEMO_ADMIN_PASSWORD,
            geolens_demo_mode=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# POSTGRES_PASSWORD literal — new check in Phase 1061
# ─────────────────────────────────────────────────────────────────────────────


def test_guard_refuses_demo_postgres_password_in_demo_mode():
    """The known-public POSTGRES_PASSWORD ('geolens-demo-2026') is refused in demo mode."""
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        _build(
            postgres_password=DEMO_POSTGRES_PASSWORD,
            geolens_demo_mode=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path — per-deploy random credentials accepted in demo mode
# ─────────────────────────────────────────────────────────────────────────────


def test_guard_accepts_random_credentials_in_demo_mode():
    """Per-deploy random credentials (from init-demo-env.sh) are accepted in demo mode.

    Simulates the output of scripts/init-demo-env.sh — base64 random values
    that are guaranteed not to match any of the three known-public literals.
    """
    settings = _build(
        jwt_secret_key="x" * 32 + "random-not-the-demo-value",
        geolens_admin_password="random-admin-output-from-script",
        postgres_password="random-pg-output-from-script-aaaa",
        geolens_demo_mode=True,
    )
    assert settings.geolens_demo_mode is True
