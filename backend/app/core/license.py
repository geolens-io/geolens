"""Verify signed GeoLens Enterprise licenses without a network request.

The token is an Ed25519 JWT with an Enterprise edition, a license ID, and a
maintenance end date. A valid token grants perpetual use of the installed
version. The maintenance date controls access to updates and support, not
whether the application keeps running. Tokens issued before this contract used
``exp`` for the same date; the verifier accepts that signed claim as a legacy
maintenance date so upgrades do not invalidate an installed license.

The verifier trusts only the public key bundled at
``app/core/license_public_key.pem``. The private signing key stays with the
vendor. Operators cannot replace the verifier key through environment
configuration. Verification works offline and allows a small amount of clock
skew for issued-at and not-before claims.

Set ``GEOLENS_LICENSE_KEY`` to the token or ``GEOLENS_LICENSE_FILE`` to a file
that contains it. ``GEOLENS_LICENSE_AUDIENCE`` can bind a license to one
deployment. Missing, malformed, forged, or mismatched tokens yield ``None`` so
the caller can use the Community edition.
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
# time-based claims such as nbf and iat.
_LEEWAY_SECONDS = 300


@dataclass(frozen=True)
class LicenseInfo:
    """A verified Enterprise license for the installed version."""

    edition: str
    maintenance_until: datetime
    license_id: str
    customer: str | None = None
    seats: int | None = None
    features: tuple[str, ...] = ()
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

    Returns None for a bad signature, an immature token, missing claims, a
    wrong algorithm, an audience mismatch, or a non-Enterprise edition.
    ``edition`` and ``license_id`` are required. New tokens carry
    ``maintenance_until``. A legacy signed ``exp`` claim is accepted as the
    maintenance date, but it does not expire the installed version.
    """
    required = ["edition", "license_id"]
    options: dict = {"require": required, "verify_exp": False}
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

    maintenance_timestamp = (
        claims.get("maintenance_until")
        if "maintenance_until" in claims
        else claims.get("exp")
    )
    if isinstance(maintenance_timestamp, bool) or not isinstance(
        maintenance_timestamp, (int, float)
    ):
        logger.warning("License token has no valid maintenance timestamp")
        return None
    try:
        maintenance_until = datetime.fromtimestamp(maintenance_timestamp, tz=UTC)
    except (OSError, OverflowError, ValueError):
        logger.warning("License token maintenance_until is outside the valid range")
        return None
    license_id = claims.get("license_id")
    if not isinstance(license_id, str) or not license_id.strip():
        logger.warning("License token license_id is empty")
        return None
    seats = claims.get("seats")
    features = claims.get("features") or ()

    return LicenseInfo(
        edition="enterprise",
        maintenance_until=maintenance_until,
        customer=claims.get("customer") or claims.get("sub"),
        seats=int(seats) if isinstance(seats, (int, float)) else None,
        features=tuple(features) if isinstance(features, (list, tuple)) else (),
        license_id=license_id.strip(),
        claims=claims,
    )


def load_license() -> LicenseInfo | None:
    """Load + verify the license from the environment. None if absent/invalid.

    Any problem with the token or bundled key returns None so the caller can
    use Community. This function never raises.
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
            maintenance_until=info.maintenance_until.isoformat(),
            license_id=info.license_id,
        )
    return info
