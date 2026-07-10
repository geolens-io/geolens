"""builder-audit #338 P0-01 (wiring) + P1-14 (share-expiration edition gate) + STYLE-06.

P0-01 wiring: the maps router must revoke a map's embed tokens (not just its
share token) when sharing is revoked or when a public map is downgraded to
non-public. These tests exercise the wiring end-to-end at the HTTP endpoint
level (the embed-token revocation primitive itself is covered in
``test_embed_revocation_by_map.py``).

P1-14: the backend share create/update endpoints must reject a custom
``expires_at`` in Community with the same advanced-sharing error taxonomy embed
tokens use, while Enterprise accepts a future expiration. The basic Community
share/revoke flow (no custom expiry) must remain unchanged.

STYLE-06: the table-driven history-emission loop in ``update_map_endpoint`` must
still emit one event per changed field
(name/visibility/terrain_config/basemap_config/layers/config_update).

Requirements: Docker database running + migrations applied (same as
``test_embed_tokens.py``).
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.schemas import ADVANCED_SHARING_ERROR
from app.modules.embed_tokens.service import (
    create_embed_token,
    validate_embed_token_access,
)
from app.platform.cache import init_cache
from app.platform.cache.provider import get_cache

from tests.factories import create_dataset, get_user_id

BASEMAP_CONFIG_PAYLOAD = {
    "label_mode": "subtle",
    "road_visibility": "subtle",
    "boundary_visibility": "hidden",
    "building_visibility": False,
    "land_water_tone": "muted",
    "relief_contrast": "strong",
    "opacity": 0.55,
    "background_color": None,
    "sublayer_overrides": None,
    "basemap_position": None,
    "projection": None,
}


def _future_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


def _cache_key(raw_token: str) -> str:
    return f"embed_token:{hashlib.sha256(raw_token.encode()).hexdigest()}"


async def _public_map_with_layer(
    session: AsyncSession, *, created_by: uuid.UUID
) -> tuple[uuid.UUID, Map, MapLayer]:
    """Create a public dataset + public map + a single layer linking them."""
    dataset = await create_dataset(
        session,
        created_by=created_by,
        name=f"P0P1 DS {uuid.uuid4().hex[:6]}",
        visibility="public",
        geometry_type="Point",
        feature_count=1,
    )
    map_obj = Map(
        name=f"P0P1 Map {uuid.uuid4().hex[:6]}",
        description="builder-audit #338 P0-01/P1-14 sharing test",
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


# ---------------------------------------------------------------------------
# P0-01 wiring (endpoint level)
# ---------------------------------------------------------------------------


class TestP001EmbedRevokeWiring:
    async def test_visibility_downgrade_revokes_embed_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
    ):
        """PUT /maps/{id} public->private must revoke the map's embed tokens.

        builder-audit #338 P0-01: previously only the share token was flipped, so a
        copied embed token kept validating after the downgrade.
        """
        init_cache()
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset_id, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        _token, raw = await create_embed_token(test_db_session, map_obj.id, uid)
        await test_db_session.commit()

        cache = get_cache()
        await cache.delete(_cache_key(raw))

        # Sanity: token validates and primes the positive cache while public.
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is True
        )
        assert await cache.get(_cache_key(raw)) is not None

        # Downgrade the map to private via the HTTP endpoint.
        resp = await client.put(
            f"/maps/{map_obj.id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["visibility"] == "private"

        # The embed token must be revoked, its cache purged, and validation deny.
        mid = map_obj.id  # capture before expire_all() to avoid a sync lazy-load
        test_db_session.expire_all()
        row = await test_db_session.execute(
            select(EmbedToken).where(EmbedToken.map_id == mid)
        )
        token = row.scalar_one()
        assert token.is_active is False
        assert await cache.get(_cache_key(raw)) is None
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is False
        )

    async def test_share_revoke_endpoint_revokes_embed_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
    ):
        """DELETE /maps/{id}/share/ must also revoke the map's embed tokens."""
        init_cache()
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset_id, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        _token, raw = await create_embed_token(test_db_session, map_obj.id, uid)
        await test_db_session.commit()

        # Create a share token so the revoke endpoint has something to revoke.
        share_resp = await client.post(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert share_resp.status_code == 200, share_resp.text

        cache = get_cache()
        await cache.delete(_cache_key(raw))
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is True
        )

        revoke_resp = await client.delete(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert revoke_resp.status_code == 204, revoke_resp.text

        mid = map_obj.id  # capture before expire_all() to avoid a sync lazy-load
        test_db_session.expire_all()
        row = await test_db_session.execute(
            select(EmbedToken).where(EmbedToken.map_id == mid)
        )
        assert row.scalar_one().is_active is False
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is False
        )

    async def test_share_revoke_revokes_orphaned_embed_without_share_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
    ):
        """DELETE /maps/{id}/share/ revokes an orphaned embed token even when no
        active share token exists — the embed purge must not be short-circuited by
        the share-token 404 (Codex P1 on builder-audit #338)."""
        init_cache()
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset_id, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        # Embed token but NO share token (the orphaned state).
        _token, raw = await create_embed_token(test_db_session, map_obj.id, uid)
        await test_db_session.commit()

        cache = get_cache()
        await cache.delete(_cache_key(raw))
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is True
        )

        # No share token exists, but the embed token must still be revoked (204,
        # not the old 404 that left it serving tiles).
        mid = map_obj.id
        resp = await client.delete(f"/maps/{mid}/share/", headers=admin_auth_header)
        assert resp.status_code == 204, resp.text

        test_db_session.expire_all()
        row = await test_db_session.execute(
            select(EmbedToken).where(EmbedToken.map_id == mid)
        )
        assert row.scalar_one().is_active is False
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is False
        )

    async def test_layer_replacement_revokes_orphaned_embed_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
    ):
        """PUT /maps/{id} replacing layers so the token's scoped dataset is gone
        must revoke the orphaned embed token (builder-audit #338 P0-01)."""
        init_cache()
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset_id, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        _token, raw = await create_embed_token(test_db_session, map_obj.id, uid)
        await test_db_session.commit()

        # A second public dataset to replace the layer set with.
        other = await create_dataset(
            test_db_session,
            created_by=uid,
            name=f"P0P1 Other DS {uuid.uuid4().hex[:6]}",
            visibility="public",
            geometry_type="Point",
            feature_count=1,
        )
        await test_db_session.commit()

        cache = get_cache()
        await cache.delete(_cache_key(raw))
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is True
        )

        # Replace layers — the original scoped dataset is no longer on the map.
        resp = await client.put(
            f"/maps/{map_obj.id}",
            json={"layers": [{"dataset_id": str(other.id), "sort_order": 0}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        mid = map_obj.id  # capture before expire_all() to avoid a sync lazy-load
        test_db_session.expire_all()
        row = await test_db_session.execute(
            select(EmbedToken).where(EmbedToken.map_id == mid)
        )
        assert row.scalar_one().is_active is False
        assert (
            await validate_embed_token_access(raw, dataset_id, test_db_session) is False
        )


# ---------------------------------------------------------------------------
# P1-14 share expiration edition gate
# ---------------------------------------------------------------------------


class TestP114ShareExpirationEdition:
    async def test_community_rejects_custom_expiration_on_create(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
        community_edition,
    ):
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        _ds, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        resp = await client.post(
            f"/maps/{map_obj.id}/share/",
            json={"expires_at": _future_expires_at().isoformat()},
            headers=admin_auth_header,
        )
        # fix(#435): 422, not 400 — the gate moved from the handler into
        # ShareTokenRequest, matching the embed-token controls.
        assert resp.status_code == 422, resp.text
        assert ADVANCED_SHARING_ERROR in resp.text

    async def test_community_basic_share_without_expiration_succeeds(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
        community_edition,
    ):
        """The basic Community share flow (no custom expiry) stays unchanged."""
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        _ds, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        resp = await client.post(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["expires_at"] is None
        assert body["is_active"] is True

        # Revoke still works in Community.
        revoke = await client.delete(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert revoke.status_code == 204, revoke.text

    async def test_enterprise_accepts_future_expiration(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
        enterprise_edition,
    ):
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        _ds, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        expires = _future_expires_at()
        resp = await client.post(
            f"/maps/{map_obj.id}/share/",
            json={"expires_at": expires.isoformat()},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["expires_at"] is not None

    async def test_community_rejects_custom_expiration_on_update(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
        community_edition,
    ):
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        _ds, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        # Establish a basic share token first.
        created = await client.post(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert created.status_code == 200, created.text

        resp = await client.patch(
            f"/maps/{map_obj.id}/share/",
            json={"expires_at": _future_expires_at().isoformat()},
            headers=admin_auth_header,
        )
        # fix(#435): schema-layer gate → 422 (see the create-path test above).
        assert resp.status_code == 422, resp.text
        assert ADVANCED_SHARING_ERROR in resp.text

    async def test_community_update_null_expiration_allowed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
        community_edition,
    ):
        """Clearing expiration (null) is the basic flow and must stay allowed."""
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        _ds, map_obj, _layer = await _public_map_with_layer(
            test_db_session, created_by=uid
        )
        created = await client.post(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert created.status_code == 200, created.text

        resp = await client.patch(
            f"/maps/{map_obj.id}/share/",
            json={"expires_at": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["expires_at"] is None


# ---------------------------------------------------------------------------
# STYLE-06 table-driven history emission
# ---------------------------------------------------------------------------


class TestStyle06HistoryEvents:
    async def test_update_emits_all_history_event_types(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        clean_tables,
    ):
        """A single PUT touching every tracked field must still emit one history
        event per field (builder-audit #338 STYLE-06 keeps semantics identical)."""
        uid = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await create_dataset(
            test_db_session,
            created_by=uid,
            name=f"STYLE06 DS {uuid.uuid4().hex[:6]}",
            visibility="public",
            geometry_type="Point",
            feature_count=1,
        )
        # Start from a private map with a known name so each field actually
        # changes (history events only fire on a real previous->new diff).
        map_obj = Map(
            name="STYLE06 Original",
            description="orig",
            visibility="private",
            created_by=uid,
        )
        test_db_session.add(map_obj)
        await test_db_session.commit()
        await test_db_session.refresh(map_obj)

        resp = await client.put(
            f"/maps/{map_obj.id}",
            json={
                "name": "STYLE06 Renamed",
                "visibility": "public",
                "terrain_config": {"enabled": True, "exaggeration": 1.5},
                "basemap_config": BASEMAP_CONFIG_PAYLOAD,
                "layers": [{"dataset_id": str(dataset.id), "sort_order": 0}],
                "description": "updated description",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        history = await client.get(
            f"/maps/{map_obj.id}/history", headers=admin_auth_header
        )
        assert history.status_code == 200, history.text
        actions = {event["action"] for event in history.json()["events"]}
        expected = {
            "map.rename",
            "map.visibility_update",
            "map.terrain_update",
            "map.basemap_update",
            "layer.replace",
            "map.config_update",
        }
        assert expected.issubset(actions), (
            f"STYLE-06: missing history events {expected - actions}"
        )
