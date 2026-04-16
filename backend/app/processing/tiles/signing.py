"""HMAC-SHA256 tile URL signing and verification.

Provides signed parameters (sig, exp, scope) for tile access tokens.
The signing key falls back to jwt_secret_key if tile_signing_secret is not set.
"""

import hmac
import hashlib
import time

from app.core.config import settings


def _get_signing_key() -> bytes:
    """Return the signing key bytes, preferring tile_signing_secret."""
    # SecretStr implements __bool__ against the inner value, so the `or`
    # fallthrough yields jwt_secret_key when tile_signing_secret is None or
    # an empty SecretStr (the latter is already coerced to None by
    # empty_str_to_none in config.py, but the check is defensive either way).
    secret = settings.tile_signing_secret or settings.jwt_secret_key
    return secret.get_secret_value().encode()


def round_expiry(ttl_seconds: int = 900) -> int:
    """Round expiry to the NEXT 15-minute boundary.

    Returns a Unix timestamp that is always a multiple of 900 and
    strictly greater than the current time.
    """
    now = int(time.time())
    return ((now // 900) + 1) * 900


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
