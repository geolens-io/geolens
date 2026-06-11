"""HMAC-SHA256 tile URL signing and verification.

Provides signed parameters (sig, exp, scope) for tile access tokens.
The signing key falls back to jwt_secret_key if tile_signing_secret is not set.
"""

import hmac
import hashlib
import time

import structlog

from app.core.config import settings

logger = structlog.stdlib.get_logger(__name__)

# SEC-11 / L-64: one-shot flag — emit the fallback warning at most once per
# process. Re-running on every tile request would flood the log.
_warned_fallback: bool = False


def _get_signing_key() -> bytes:
    """Return the signing key bytes, preferring tile_signing_secret.

    SEC-11: when tile_signing_secret is None, fall back to jwt_secret_key
    AND emit a one-shot WARN so operators know they're sharing one secret
    for two purposes (JWT signing + tile URL signing).
    """
    global _warned_fallback
    # SecretStr implements __bool__ against the inner value, so the `or`
    # fallthrough yields jwt_secret_key when tile_signing_secret is None or
    # an empty SecretStr (the latter is already coerced to None by
    # empty_str_to_none in config.py, but the check is defensive either way).
    if settings.tile_signing_secret is None and not _warned_fallback:
        logger.warning(
            "tile_signing_secret_fallback",
            message=(
                "TILE_SIGNING_SECRET is unset; falling back to JWT_SECRET_KEY "
                "for HMAC tile signing. Set TILE_SIGNING_SECRET to a separate "
                "secret (openssl rand -hex 32) to isolate tile-signing key "
                "rotation from JWT key rotation."
            ),
        )
        _warned_fallback = True

    secret = settings.tile_signing_secret or settings.jwt_secret_key
    return secret.get_secret_value().encode()


_MIN_VALIDITY_SECONDS: int = 60
"""Minimum number of seconds a minted token must be valid for.

When the next 15-minute boundary is closer than this threshold the function
skips to the FOLLOWING boundary so clients always have a meaningful validity
window.  BUG-012: previously a token minted 5 s before a boundary had only
5 s validity — well below the client refresh floor — causing deterministic 403
bursts every 15 minutes.
"""


def round_expiry(
    ttl_seconds: int = 900, min_validity: int = _MIN_VALIDITY_SECONDS
) -> int:
    """Round expiry to the next 15-minute boundary that is at least min_validity seconds away.

    Returns a Unix timestamp that is always a multiple of 900 and at least
    min_validity seconds greater than the current time (BUG-012).

    Args:
        ttl_seconds: Boundary interval in seconds (default 900 = 15 min).
        min_validity: Minimum seconds of validity the returned timestamp must
            provide.  When the next boundary is closer than this value, the
            FOLLOWING boundary is returned instead.
    """
    now = int(time.time())
    nxt = ((now // ttl_seconds) + 1) * ttl_seconds
    if (nxt - now) >= min_validity:
        return nxt
    return nxt + ttl_seconds


def generate_tile_signature(scope: str, exp: int) -> str:
    """Generate an HMAC-SHA256 signature for the given scope and expiry.

    Args:
        scope: The tile scope (typically the dataset table_name).
        exp: Unix timestamp expiry.

    Returns:
        64-character hex digest string.
    """
    message = f"{scope}:{exp}"
    return hmac.new(_get_signing_key(), message.encode(), hashlib.sha256).hexdigest()


def verify_tile_signature(scope: str, exp: int, sig: str) -> bool:
    """Verify a tile signature.

    Checks expiry first (rejects if expired), then validates the HMAC.

    Args:
        scope: The tile scope.
        exp: Unix timestamp expiry.
        sig: The signature to verify.

    Returns:
        True if valid and not expired, False otherwise.
    """
    if time.time() > exp:
        return False
    expected = generate_tile_signature(scope, exp)
    return hmac.compare_digest(expected, sig)
