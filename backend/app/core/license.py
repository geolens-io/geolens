"""Signed offline license verification (entitlement layer).

The community/enterprise edition is currently decided by ``GEOLENS_EDITION`` or
the mere presence of a loaded extension (see :mod:`app.core.edition`), which is
an honor-system boundary: anyone who installs the overlay or sets one env var
unlocks every paid feature. This module adds the real entitlement check — a
cryptographically **signed, offline** license token.

Design:

- The token is an EdDSA (Ed25519) JWT carrying ``edition`` + ``exp`` (+ optional
  ``customer``, ``seats``, ``features``, ``license_id``, ``aud``).
- It is verified against the **bundled, immutable** Ed25519 public key at
  ``app/core/license_public_key.pem``. The matching **private** signing key
  never ships — it lives only with the vendor's minting tooling
  (``scripts/license_tool.py``). Shipping the public key in the (soon
  Apache-2.0) core is safe — that is the point of asymmetric signatures.
- The verifier key is deliberately **NOT** environment-configurable. The party
  that supplies the license token (the operator) must not also be able to
  choose the key it is checked against — otherwise they could mint their own
  enterprise token against their own key and the entitlement check is moot
  (it would just re-create the env-only bypass it is meant to close).
- Verification is fully **offline** — no phone-home — so it works air-gapped,
  with a small ``leeway`` to tolerate clock skew between signer and verifier.
- It is **graceful**: a missing / malformed / expired / forged token, or a
  missing bundled key, yields ``None`` (→ community). It never raises into the
  app lifespan.

Inputs (all optional; absence → no license → community):

- ``GEOLENS_LICENSE_KEY``      — the signed license token (preferred), or
- ``GEOLENS_LICENSE_FILE``     — path to a file containing the token.
- ``GEOLENS_LICENSE_AUDIENCE`` — optional deployment identifier. When set, the
  token's ``aud`` claim MUST match it, binding a license to this deployment so a
  token issued for one customer cannot be replayed on another.

This module owns verification only; :mod:`app.core.edition` owns the policy of
how a verified (or absent) license maps to the running edition, including the
**runtime** re-check of ``expires_at`` (a token valid at startup must stop
unlocking enterprise once it expires, without a restart).
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

# The bundled, immutable verifier trust root. The vendor commits THEIR public
# key here in the enterprise build. Intentionally a code/asset constant, never
# an env var (see module docstring).
_TRUSTED_PUBLIC_KEY_PATH = Path(__file__).with_name("license_public_key.pem")

# Tolerate modest clock skew between the signer and the verifying host for the
# time-based claims (exp / nbf / iat). Small relative to a multi-month license.
_LEEWAY_SECONDS = 300


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


def _load_trusted_public_key() -> str | None:
    """Return the bundled verifier public key (PEM), or None if not present.

    Read ONLY from the committed trust-root path — never from the environment.
    A build with no bundled key can never grant enterprise via a license (the
    safe default), so this returns None silently in that case.
    """
    try:
        if _TRUSTED_PUBLIC_KEY_PATH.is_file():
            return _TRUSTED_PUBLIC_KEY_PATH.read_text()
    except OSError:
        logger.warning(
            "Could not read bundled license public key",
            path=str(_TRUSTED_PUBLIC_KEY_PATH),
        )
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


def verify_license_token(
    token: str, public_key_pem: str, *, audience: str | None = None
) -> LicenseInfo | None:
    """Verify a token against the public key. Return LicenseInfo or None.

    Returns None (never raises) for any verification failure: bad signature,
    expired, immature, missing required claims, wrong algorithm, audience
    mismatch, or a non-enterprise edition claim. ``exp`` and ``edition`` are
    always required. When ``audience`` is given, ``aud`` is required and must
    match (binds the license to this deployment); otherwise ``aud`` is not
    checked. ``_LEEWAY_SECONDS`` of clock skew is tolerated.
    """
    required = ["exp", "edition"]
    options: dict = {"require": required}
    decode_kwargs: dict = {"algorithms": [_ALGORITHM], "leeway": _LEEWAY_SECONDS}
    if audience:
        decode_kwargs["audience"] = audience
        required.append("aud")
    else:
        # No audience configured for this deployment: don't reject tokens that
        # happen to carry an `aud` claim (PyJWT verifies aud by default).
        options["verify_aud"] = False

    try:
        claims = jwt.decode(token, public_key_pem, options=options, **decode_kwargs)
    except jwt.PyJWTError as exc:
        # Includes ExpiredSignatureError, ImmatureSignatureError,
        # InvalidSignatureError, MissingRequiredClaimError, InvalidAudienceError,
        # InvalidAlgorithmError, etc.
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

    Fully graceful: any problem (no token, no bundled key, bad signature,
    expired, audience mismatch) returns None so the caller falls back to
    community. Never raises.
    """
    token = _load_token()
    if not token:
        return None

    public_key = _load_trusted_public_key()
    if not public_key:
        # A token is present but this build bundles no verifying key. We cannot
        # trust an unverifiable token -> community.
        logger.warning(
            "GEOLENS_LICENSE_KEY is set but this build bundles no license "
            "public key; treating as unlicensed."
        )
        return None

    audience = _read_first(os.environ.get("GEOLENS_LICENSE_AUDIENCE"))
    info = verify_license_token(token, public_key, audience=audience)
    if info is not None:
        logger.info(
            "Enterprise license verified",
            customer=info.customer,
            expires_at=info.expires_at.isoformat() if info.expires_at else None,
            license_id=info.license_id,
        )
    return info
