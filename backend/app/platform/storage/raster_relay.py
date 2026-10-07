"""Relay addresses that hand Titiler a remote raster without its URL.

Titiler never fetches a remote raster itself. It is given an address on the
API's internal relay route instead, and the relay fetches the bytes with the
pinned client. The address carries the asset URL, the dataset it belongs to
and an expiry, encrypted and authenticated with a key derived from
``JWT_SECRET_KEY``: the URL can hold a presigned query, and Titiler logs every
address it is asked to open.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
import uuid
from typing import NamedTuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RELAY_ROUTE_PREFIX = "/internal/raster-relay"
RELAY_FILENAME = "raster.tif"

_KEY_INFO = b"geolens remote-raster-relay v1"
_NONCE_BYTES = 12
# An address stays the same for a whole bucket, so Titiler's per-address
# block cache keeps working across tiles, and lives one more bucket after it.
_BUCKET_SECONDS = 3600
_MAX_TOKEN_CHARS = 16384


class RelayClaims(NamedTuple):
    url: str
    dataset_id: uuid.UUID | None


def is_remote_asset_uri(asset_uri: str) -> bool:
    """Whether a stored asset URI names a remote object rather than a managed key."""
    return asset_uri.lower().startswith(("http://", "https://"))


def _keys() -> tuple[bytes, bytes]:
    """The cipher key and the nonce key, derived per call so a rotated secret
    takes effect without a restart."""
    from app.core.config import settings

    okm = HKDF(algorithm=hashes.SHA256(), length=64, salt=None, info=_KEY_INFO).derive(
        settings.jwt_secret_key.get_secret_value().encode()
    )
    return okm[:32], okm[32:]


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_relay_token(
    url: str, dataset_id: uuid.UUID | None, *, now: float | None = None
) -> str:
    """An opaque, path-safe token for ``url``.

    The nonce is a MAC of the plaintext, so the same claims in the same
    bucket always give the same token and different claims never share a
    nonce.
    """
    issued = int(time.time() if now is None else now)
    expires = (issued // _BUCKET_SECONDS + 2) * _BUCKET_SECONDS
    plaintext = json.dumps(
        {"u": url, "d": str(dataset_id) if dataset_id else None, "e": expires},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    cipher_key, nonce_key = _keys()
    nonce = hmac.new(nonce_key, plaintext, hashlib.sha256).digest()[:_NONCE_BYTES]
    sealed = AESGCM(cipher_key).encrypt(nonce, plaintext, _KEY_INFO)
    return _b64encode(nonce + sealed)


def read_relay_token(token: str, *, now: float | None = None) -> RelayClaims | None:
    """The claims of a token this deployment issued and that has not expired."""
    if not token or len(token) > _MAX_TOKEN_CHARS or not token.isascii():
        return None
    try:
        raw = _b64decode(token)
    except (binascii.Error, ValueError):
        return None
    if len(raw) <= _NONCE_BYTES:
        return None
    cipher_key, _ = _keys()
    try:
        plaintext = AESGCM(cipher_key).decrypt(
            raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], _KEY_INFO
        )
        claims = json.loads(plaintext)
        url, dataset, expires = claims["u"], claims["d"], int(claims["e"])
        dataset_id = uuid.UUID(dataset) if dataset else None
    except (InvalidTag, ValueError, KeyError, TypeError):
        return None
    if not isinstance(url, str) or not is_remote_asset_uri(url):
        return None
    if int(time.time() if now is None else now) >= expires:
        return None
    return RelayClaims(url, dataset_id)


def _relay_base() -> str:
    from app.core.config import settings

    return settings.remote_raster_relay_base_url.rstrip("/") + RELAY_ROUTE_PREFIX + "/"


def relay_url(url: str, dataset_id: uuid.UUID | None) -> str:
    """The address Titiler opens to read the remote raster at ``url``."""
    return f"{_relay_base()}{issue_relay_token(url, dataset_id)}/{RELAY_FILENAME}"


def is_relay_url(value: str) -> bool:
    """Whether ``value`` is an address :func:`relay_url` could have built."""
    base = _relay_base()
    if not value.startswith(base) or not value.endswith("/" + RELAY_FILENAME):
        return False
    token = value[len(base) : -len(RELAY_FILENAME) - 1]
    return bool(token) and all(c.isalnum() or c in "-_" for c in token)
