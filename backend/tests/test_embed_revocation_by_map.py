"""builder-audit P0-01 regression: embed tokens must not survive share revocation,
visibility downgrade, or layer removal.

These tests prove the two halves of the fix in
``app.modules.embed_tokens.service``:

  1. ``revoke_embed_tokens_by_map`` deactivates every active embed token for a
     map AND purges its Redis positive-cache entry, so a copied embed token
     stops validating immediately (this is the function the maps router wires
     into share-revoke / public->non-public visibility-downgrade paths).

  2. ``validate_embed_token_access`` performs a fail-closed live
     layer-membership re-check, so removing the dataset's layer from the map
     denies a token scoped to that dataset even when a positive cache entry
     still exists.

Requirements: Docker database running + migrations applied (same as
``test_embed_tokens.py``).
"""

import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.embed_tokens.service import (
    create_embed_token,
    revoke_embed_tokens_by_map,
    validate_embed_token_access,
)
from app.platform.cache import init_cache
from app.platform.cache.provider import get_cache

from tests.factories import create_dataset, get_user_id


async def _setup_map_with_layer(
    session: AsyncSession, *, created_by: uuid.UUID
) -> tuple[uuid.UUID, Map, MapLayer]:
    """Create a public dataset + public map + a single layer linking them.

    Returns (dataset_id, map, layer).
    """
    dataset = await create_dataset(
        session,
        created_by=created_by,
        name="P0-01 Embed DS",
        visibility="public",
        geometry_type="Point",
        feature_count=1,
    )
    map_obj = Map(
        name=f"P0-01 Embed Map {uuid.uuid4().hex[:6]}",
        description="builder-audit P0-01 revocation test",
        visibility="public",
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()
    layer = MapLayer(map_id=map_obj.id, dataset_id=dataset.id, sort_order=0)
    session.add(layer)
    await session.commit()
    await session.refresh(map_obj)
    await session.refresh(layer)
    return dataset.id, map_obj, layer


def _cache_key(raw_token: str) -> str:
    return f"embed_token:{hashlib.sha256(raw_token.encode()).hexdigest()}"


async def test_revoke_by_map_denies_validation_and_clears_cache(
    test_db_session: AsyncSession, clean_tables
):
    """revoke_embed_tokens_by_map flips is_active=False, purges the positive
    cache, and makes subsequent validation fail immediately."""
    init_cache()
    uid = await get_user_id(test_db_session, settings.geolens_admin_username)
    dataset_id, map_obj, _layer = await _setup_map_with_layer(
        test_db_session, created_by=uid
    )
    _token, raw = await create_embed_token(test_db_session, map_obj.id, uid)
    await test_db_session.commit()

    cache = get_cache()
    await cache.delete(_cache_key(raw))

    # 1. Valid before revocation — this primes the positive cache.
    assert (
        await validate_embed_token_access(raw, dataset_id, test_db_session) is True
    ), "Sanity: a fresh active embed token must validate before revocation."
    assert await cache.get(_cache_key(raw)) is not None, (
        "Sanity: a successful validation must prime the positive cache."
    )

    # 2. Revoke all embed tokens for the map (the share-revoke / downgrade path).
    revoked = await revoke_embed_tokens_by_map(test_db_session, map_obj.id)
    await test_db_session.commit()
    assert revoked == 1

    # The positive cache entry must be gone (cannot outlive the revocation).
    assert await cache.get(_cache_key(raw)) is None, (
        "P0-01: revoke_embed_tokens_by_map must purge the Redis positive cache."
    )

    # 3. Validation now fails immediately (DB is_active=False -> deny).
    assert (
        await validate_embed_token_access(raw, dataset_id, test_db_session) is False
    ), "P0-01: a revoked embed token must fail tile validation immediately."


async def test_revoke_by_map_is_idempotent_when_no_active_tokens(
    test_db_session: AsyncSession, clean_tables
):
    """Calling revoke on a map with no active embed tokens returns 0 (no-op)."""
    init_cache()
    uid = await get_user_id(test_db_session, settings.geolens_admin_username)
    _dataset_id, map_obj, _layer = await _setup_map_with_layer(
        test_db_session, created_by=uid
    )
    # No embed token created for this map.
    revoked = await revoke_embed_tokens_by_map(test_db_session, map_obj.id)
    assert revoked == 0


async def test_layer_removal_denies_scoped_token_even_when_cached(
    test_db_session: AsyncSession, clean_tables
):
    """builder-audit P0-01 live membership re-check: removing the dataset's layer
    from the map denies a token scoped to that dataset, even with a positive
    cache entry present (the snapshot scoped_dataset_ids must not outlive the
    layer removal)."""
    init_cache()
    uid = await get_user_id(test_db_session, settings.geolens_admin_username)
    dataset_id, map_obj, layer = await _setup_map_with_layer(
        test_db_session, created_by=uid
    )
    _token, raw = await create_embed_token(test_db_session, map_obj.id, uid)
    await test_db_session.commit()

    cache = get_cache()
    await cache.delete(_cache_key(raw))

    # Prime the positive cache via a successful validation.
    assert await validate_embed_token_access(raw, dataset_id, test_db_session) is True
    assert await cache.get(_cache_key(raw)) is not None

    # Remove the dataset's layer from the map. The token is still active and the
    # positive cache entry still exists — only the live membership changed.
    await test_db_session.delete(layer)
    await test_db_session.commit()

    # The fail-closed live membership re-check must deny on the cache-hit path.
    assert (
        await validate_embed_token_access(raw, dataset_id, test_db_session) is False
    ), (
        "P0-01: a cached embed token must be denied once its dataset's layer is "
        "removed from the map (live layer-membership re-check)."
    )
