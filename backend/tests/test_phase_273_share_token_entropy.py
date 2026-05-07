"""SEC-10: Share-token entropy is 32 bytes (256 bits), parity with embed tokens.

Pins the v13.13 closure of L-60. Existing 16-byte tokens (already hashed in
the DB as sha256) continue to validate — the entropy bump applies only to
newly generated tokens.
"""

import base64
import hashlib
import secrets
import uuid

from app.modules.auth.models import User
from app.modules.catalog.maps.models import Map, MapShareToken
from app.modules.catalog.maps.service_public import (
    _validate_share_token,
    create_share_token,
)
from sqlalchemy import select


def _decoded_byte_length(urlsafe_b64: str) -> int:
    """Reverse secrets.token_urlsafe → raw byte length.

    secrets.token_urlsafe strips '=' padding; urlsafe_b64decode wants it back.
    """
    pad = 4 - (len(urlsafe_b64) % 4)
    if pad != 4:
        urlsafe_b64 = urlsafe_b64 + ("=" * pad)
    return len(base64.urlsafe_b64decode(urlsafe_b64.encode()))


async def _get_admin_id(session) -> uuid.UUID:
    from app.core.config import settings

    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    user = result.scalar_one()
    return user.id


async def _create_map(session, *, created_by: uuid.UUID) -> Map:
    """Insert a Map row directly into the DB (no layers needed for token tests)."""
    map_obj = Map(
        name=f"SEC-10 Test Map {uuid.uuid4().hex[:6]}",
        description="share-token entropy test",
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()
    await session.refresh(map_obj)
    return map_obj


async def test_new_share_token_is_32_bytes(test_db_session):
    """create_share_token generates a 32-byte (256-bit) raw token."""
    admin_id = await _get_admin_id(test_db_session)
    map_obj = await _create_map(test_db_session, created_by=admin_id)
    token_obj = await create_share_token(test_db_session, map_obj.id, admin_id)
    raw = token_obj._raw_token  # transient attribute set by the service
    assert _decoded_byte_length(raw) == 32, (
        f"Expected 32-byte raw token (256-bit entropy), got {_decoded_byte_length(raw)} bytes"
    )


async def test_token_hash_storage_shape_unchanged(test_db_session):
    """sha256-hexdigest = 64 chars regardless of input entropy."""
    admin_id = await _get_admin_id(test_db_session)
    map_obj = await _create_map(test_db_session, created_by=admin_id)
    token_obj = await create_share_token(test_db_session, map_obj.id, admin_id)
    assert len(token_obj.token_hash) == 64
    assert all(c in "0123456789abcdef" for c in token_obj.token_hash)


async def test_legacy_16_byte_token_still_validates(test_db_session):
    """A 16-byte raw token (the OLD form) inserted directly via sha256 hash
    continues to validate via _validate_share_token."""
    admin_id = await _get_admin_id(test_db_session)
    map_obj = await _create_map(test_db_session, created_by=admin_id)
    raw_legacy = secrets.token_urlsafe(16)  # ← OLD form
    legacy_hash = hashlib.sha256(raw_legacy.encode()).hexdigest()
    legacy_token = MapShareToken(
        map_id=map_obj.id,
        token_hash=legacy_hash,
        token_hint=raw_legacy[:8],
        created_by=admin_id,
        is_active=True,
    )
    test_db_session.add(legacy_token)
    await test_db_session.flush()

    # Lookup by raw token (the user presents the original token)
    result = await _validate_share_token(test_db_session, raw_legacy)
    assert result is not None
    assert result != "expired"
    assert isinstance(result, MapShareToken)
    assert result.token_hash == legacy_hash


def test_secrets_token_urlsafe_32_byte_length():
    """Independent unit-level confirmation that secrets.token_urlsafe(32) → 32 raw bytes.

    Guards against a regression where someone might 'optimize' the call to
    secrets.token_urlsafe(24) for shorter URLs.
    """
    raw = secrets.token_urlsafe(32)
    assert _decoded_byte_length(raw) == 32
