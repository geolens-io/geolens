"""Signed offline license verification (entitlement layer).

The community/enterprise edition is currently decided by ``GEOLENS_EDITION`` or
the mere presence of a loaded extension (see :mod:`app.core.edition`), which is
an honor-system boundary: anyone who installs the overlay or sets one env var
unlocks every paid feature. This module adds the real entitlement check — a
cryptographically **signed, offline** license token.

Design:

- The token is an EdDSA (Ed25519) JWT carrying ``edition`` + ``exp`` (+ optional
  ``customer``, ``seats``, ``features``, ``license_id``).
- It is verified against an Ed25519 **public** key bundled/configured in the
  deployment. The matching **private** signing key never ships with the product
  — it lives only with the vendor's license-minting tooling
  (``scripts/license_tool.py``). Shipping the public key in the (soon Apache-2.0)
  core is safe: that is the whole point of asymmetric signatures.
- Verification is fully **offline** — no phone-home — so it works air-gapped.
- It is **graceful**: a missing / malformed / expired / forged token, or a
  missing public key, yields ``None`` (→ community). It never raises into the
  app lifespan.

Inputs (all optional; absence → no license → community):

- ``GEOLENS_LICENSE_KEY``        — the signed license token (preferred), or
- ``GEOLENS_LICENSE_FILE``       — path to a file containing the token.
- ``GEOLENS_LICENSE_PUBLIC_KEY`` — the verifying Ed25519 public key (PEM), or
- ``GEOLENS_LICENSE_PUBLIC_KEY_FILE`` — path to the public-key PEM, else the
  bundled default at ``app/core/license_public_key.pem`` if present.

This module owns verification only; :mod:`app.core.edition` owns the policy of
how a verified (or absent) license maps to the running edition.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import jwt
import structlog

logger = structlog.stdlib.get_logger(__name__)

# Ed25519 -> EdDSA in JOSE terms. Pinned to a single asymmetric algorithm so a
# forged token cannot downgrade to HS* and have the public key treated as an
# HMAC secret (the classic "alg confusion" attack).
_ALGORITHM = "EdDSA"

_DEFAULT_PUBLIC_KEY_PATH = Path(__file__).with_name("license_public_key.pem")


@dataclass(frozen=True)
class LicenseInfo:
    """A verified, non-expired enterprise license."""

    edition: str
    expires_at: datetime | None = None
    customer: str | None = None
    seats: int | None = None
    features: tuple[str, ...] = ()
    license_id: str | None = None
    claims: dict = field(default_factory=dict)


def _read_first(*candidates: str | None) -> str | None:
    """Return the first non-empty value, stripped; else None."""
    for value in candidates:
        if value and value.strip():
            return value.strip()
    return None


def _load_public_key() -> str | None:
    """Resolve the verifying Ed25519 public key (PEM), or None if unconfigured.

    Order: explicit PEM env > explicit file env > bundled default file. A
    deployment with no public key configured can never be enterprise — the safe
    default — so this returns None silently in that case.
    """
    inline = _read_first(os.environ.get("GEOLENS_LICENSE_PUBLIC_KEY"))
    if inline:
        return inline

    file_env = _read_first(os.environ.get("GEOLENS_LICENSE_PUBLIC_KEY_FILE"))
    candidates = [Path(file_env)] if file_env else []
    candidates.append(_DEFAULT_PUBLIC_KEY_PATH)
    for path in candidates:
        try:
            if path.is_file():
                return path.read_text()
        except OSError:
            logger.warning("Could not read license public key", path=str(path))
    return None


def _load_token() -> str | None:
    """Resolve the license token from env or file, or None."""
    inline = _read_first(os.environ.get("GEOLENS_LICENSE_KEY"))
    if inline:
        return inline

    file_env = _read_first(os.environ.get("GEOLENS_LICENSE_FILE"))
    if file_env:
        try:
            path = Path(file_env)
            if path.is_file():
                return path.read_text().strip()
            logger.warning("GEOLENS_LICENSE_FILE does not exist", path=file_env)
        except OSError:
            logger.warning("Could not read GEOLENS_LICENSE_FILE", path=file_env)
    return None


def verify_license_token(token: str, public_key_pem: str) -> LicenseInfo | None:
    """Verify a token against the public key. Return LicenseInfo or None.

    Returns None (never raises) for any verification failure: bad signature,
    expired, missing required claims, wrong algorithm, or a non-enterprise
    edition claim. ``exp`` is enforced by PyJWT; ``edition`` is required and
    must be ``"enterprise"`` (the only paid edition today).
    """
    try:
        claims = jwt.decode(
            token,
            public_key_pem,
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "edition"]},
        )
    except jwt.PyJWTError as exc:
        # Includes ExpiredSignatureError, InvalidSignatureError,
        # MissingRequiredClaimError, InvalidAlgorithmError, etc.
        logger.warning("License token rejected", reason=type(exc).__name__)
        return None

    if claims.get("edition") != "enterprise":
        logger.warning(
            "License token edition is not enterprise", edition=claims.get("edition")
        )
        return None

    exp = claims.get("exp")
    expires_at = (
        datetime.fromtimestamp(exp, tz=UTC) if isinstance(exp, (int, float)) else None
    )
    seats = claims.get("seats")
    features = claims.get("features") or ()

    return LicenseInfo(
        edition="enterprise",
        expires_at=expires_at,
        customer=claims.get("customer") or claims.get("sub"),
        seats=int(seats) if isinstance(seats, (int, float)) else None,
        features=tuple(features) if isinstance(features, (list, tuple)) else (),
        license_id=claims.get("license_id") or claims.get("jti"),
        claims=claims,
    )


def load_license() -> LicenseInfo | None:
    """Load + verify the license from the environment. None if absent/invalid.

    Fully graceful: any problem (no token, no public key, bad signature,
    expired) returns None so the caller falls back to community. Never raises.
    """
    token = _load_token()
    if not token:
        return None

    public_key = _load_public_key()
    if not public_key:
        # A token is present but the deployment has no verifying key configured.
        # We cannot trust an unverifiable token -> community.
        logger.warning(
            "GEOLENS_LICENSE_KEY is set but no license public key is configured; "
            "set GEOLENS_LICENSE_PUBLIC_KEY(_FILE). Treating as unlicensed."
        )
        return None

    info = verify_license_token(token, public_key)
    if info is not None:
        logger.info(
            "Enterprise license verified",
            customer=info.customer,
            expires_at=info.expires_at.isoformat() if info.expires_at else None,
            license_id=info.license_id,
        )
    return info
