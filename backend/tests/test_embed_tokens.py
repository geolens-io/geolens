"""Integration tests for embed token CRUD and tile middleware.

Covers:
  - EMBED-01: Token creation with SHA-256 hashing
  - EMBED-02: Scoped dataset tile access
  - EMBED-03: Default and max expiration
  - EMBED-04: Tile middleware X-Embed-Token validation before HMAC
  - EMBED-05: Cache-based validation
  - EMBED-06: Token revocation
  - EMBED-07: Token listing

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.schemas import ADVANCED_SHARING_ERROR
from app.modules.embed_tokens.service import create_embed_token, update_embed_token
from app.platform.cache.provider import get_cache

from tests.factories import create_dataset, get_user_id


@pytest.fixture(autouse=True)
async def _init_tile_pool_for_tests(request):
    """Initialize asyncpg pool for tile tests."""
    db_fixtures = {
        "admin_auth_header",
        "clean_tables",
        "cleanup_data_tables",
        "client",
        "editor_auth_header",
        "test_db_session",
        "viewer_auth_header",
    }
    if not db_fixtures.intersection(request.fixturenames):
        yield
        return

    import app.processing.tiles.pool as pool_module

    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=3, command_timeout=10
    )
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_private_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str | None = None,
) -> Dataset:
    """Insert a Record + Dataset with private visibility."""
    return await create_dataset(
        session,
        created_by=created_by,
        name="Embed Test DS",
        table_name=table_name,
        visibility="private",
        description="Dataset for embed token tests",
        geometry_type="Point",
        feature_count=1,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "geom", "type": "geometry"},
        ],
    )


async def _create_map_with_layer(
    session,
    client: AsyncClient,
    headers: dict,
    dataset: Dataset,
    *,
    created_by: uuid.UUID,
) -> tuple[Map, MapLayer]:
    """Create a map and add a layer pointing to the given dataset."""
    map_obj = Map(
        name=f"Embed Test Map {uuid.uuid4().hex[:6]}",
        description="test",
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()

    layer = MapLayer(
        map_id=map_obj.id,
        dataset_id=dataset.id,
        sort_order=0,
    )
    session.add(layer)
    await session.commit()
    await session.refresh(map_obj)
    await session.refresh(layer)
    return map_obj, layer


async def _create_data_table(session, table_name: str) -> None:
    """Create a PostGIS data table in the 'data' schema for tile serving."""
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  geom GEOMETRY(Point, 3857),"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES ("
            f"  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            f")"
        )
    )
    await session.commit()


async def _cleanup_data_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


@pytest.fixture
async def cleanup_data_tables(test_db_session):
    """Fixture that guarantees cleanup of data tables even on test failure.

    Usage: call ``cleanup_data_tables(table_name)`` to register a table for
    cleanup.  All registered tables are dropped in the ``finally`` block after
    the test completes (whether it passes or fails).
    """
    tables: list[str] = []

    def _register(table_name: str) -> str:
        tables.append(table_name)
        return table_name

    yield _register

    for t in tables:
        await _cleanup_data_table(test_db_session, t)


# ---------------------------------------------------------------------------
# Tests: Token CRUD (EMBED-01, EMBED-03, EMBED-06, EMBED-07)
# ---------------------------------------------------------------------------


class TestCreateEmbedToken:
    """EMBED-01: Token creation."""

    async def test_create_embed_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """POST creates a token with raw_token, token_hint, and scoped_dataset_ids."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "My Token"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["raw_token"].startswith("et_")
        assert data["token_hint"].startswith("et_...")
        assert str(dataset.id) in data["scoped_dataset_ids"]
        assert data["is_active"] is True
        assert data["name"] == "My Token"

    async def test_create_embed_token_default_expiration(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """EMBED-03: Default expiration is ~30 days."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Capture the time window around the request to bound the expected
        # expiration deterministically (no wall-clock comparison after the fact).
        before = datetime.now(timezone.utc)
        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={},
            headers=admin_auth_header,
        )
        after = datetime.now(timezone.utc)
        assert resp.status_code == 201
        data = resp.json()
        expires_at = datetime.fromisoformat(data["expires_at"])
        # The server generated expires_at at some point t in [before, after].
        # So expires_at must be in [before + 30d, after + 30d].
        assert before + timedelta(days=30) <= expires_at <= after + timedelta(days=30)

    async def test_custom_expiration_requires_enterprise(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        community_edition,
    ):
        """Community cannot create embed tokens with custom expiration."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"expires_in_days": 90},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert ADVANCED_SHARING_ERROR in resp.text

    async def test_allowed_origins_require_enterprise(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        community_edition,
    ):
        """Community cannot create embed tokens with origin restrictions."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"allowed_origins": ["https://example.com"]},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert ADVANCED_SHARING_ERROR in resp.text

    async def test_create_embed_token_max_expiration(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        enterprise_edition,
    ):
        """EMBED-03: Expiration is capped at 365 days even if requesting more.
        The schema enforces le=365 so 400 is expected.
        """
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"expires_in_days": 400},
            headers=admin_auth_header,
        )
        # Schema enforces le=365, so 422 (validation error) is expected
        assert resp.status_code == 422

        # Verify max value (365) works
        before = datetime.now(timezone.utc)
        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"expires_in_days": 365},
            headers=admin_auth_header,
        )
        after = datetime.now(timezone.utc)
        assert resp.status_code == 201
        data = resp.json()
        expires_at = datetime.fromisoformat(data["expires_at"])
        # Bound the expected expiration to [before + 365d, after + 365d].
        assert before + timedelta(days=365) <= expires_at <= after + timedelta(days=365)


class TestEmbedTokenServiceGuards:
    """Service-layer guards for schema bypasses."""

    async def test_create_custom_expiration_guard_runs_before_db_lookup(
        self, community_edition
    ):
        with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
            await create_embed_token(
                object(),
                uuid.uuid4(),
                uuid.uuid4(),
                expires_in_days=90,
            )

    async def test_create_allowed_origins_guard_runs_before_db_lookup(
        self, community_edition
    ):
        with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
            await create_embed_token(
                object(),
                uuid.uuid4(),
                uuid.uuid4(),
                allowed_origins=["https://example.com"],
            )

    async def test_update_allowed_origins_guard_runs_before_db_lookup(
        self, community_edition
    ):
        with pytest.raises(ValueError, match=ADVANCED_SHARING_ERROR):
            await update_embed_token(
                object(),
                uuid.uuid4(),
                uuid.uuid4(),
                ["https://example.com"],
            )


class TestListEmbedTokens:
    """EMBED-07: Token listing."""

    async def test_list_embed_tokens(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Create 2 tokens, list them, verify both returned."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create 2 tokens
        for i in range(2):
            resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={"name": f"Token {i}"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201

        # List tokens
        resp = await client.get(
            f"/maps/{map_obj.id}/embed-tokens/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["tokens"]) == 2
        # Verify raw_token is NOT in list responses
        for token in data["tokens"]:
            assert "raw_token" not in token
            assert "token_hint" in token
            assert "scoped_dataset_ids" in token


class TestRevokeEmbedToken:
    """EMBED-06: Token revocation."""

    async def test_revoke_embed_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Revoke a token; verify is_active=false. Listing shows revoked token."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create a token
        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "To Revoke"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        token_id = create_resp.json()["id"]

        # Revoke it
        revoke_resp = await client.delete(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
            headers=admin_auth_header,
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["is_active"] is False

        # Verify in list
        list_resp = await client.get(
            f"/maps/{map_obj.id}/embed-tokens/",
            headers=admin_auth_header,
        )
        tokens = list_resp.json()["tokens"]
        revoked = [t for t in tokens if t["id"] == token_id]
        assert len(revoked) == 1
        assert revoked[0]["is_active"] is False


# ---------------------------------------------------------------------------
# Tests: Tile middleware (EMBED-02, EMBED-04, EMBED-05)
# ---------------------------------------------------------------------------


class TestTileEmbedTokenAccess:
    """EMBED-02, EMBED-04: Tile access with embed tokens."""

    async def test_tile_access_with_valid_embed_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Valid embed token grants tile access for scoped dataset (EMBED-02, EMBED-04)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_tile_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create embed token
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]

            # Tile request with embed token header
            tile_resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp.status_code in (200, 204)
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_access_unscoped_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Embed token for map A rejects access to unscoped dataset (EMBED-02)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)

        # Create two datasets - token will only scope to dataset_a
        table_a = f"embed_scope_a_{uuid.uuid4().hex[:8]}"
        table_b = f"embed_scope_b_{uuid.uuid4().hex[:8]}"
        dataset_a = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_a
        )
        await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_b
        )

        # Map only has dataset_a as a layer
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset_a, created_by=user_id
        )
        await _create_data_table(test_db_session, table_b)

        try:
            # Create embed token (scoped to dataset_a only)
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]

            # Try accessing dataset_b tiles with this token -- should fail
            tile_resp = await client.get(
                f"/tiles/data.{table_b}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_b)

    async def test_tile_access_expired_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Expired embed token is rejected (EMBED-04)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_exp_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create embed token
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={"expires_in_days": 1},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]
            token_id = create_resp.json()["id"]

            # Manually expire the token in the DB
            await test_db_session.execute(
                update(EmbedToken)
                .where(EmbedToken.id == uuid.UUID(token_id))
                .values(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )
            await test_db_session.commit()

            # Clear cache so the expired value is picked up from DB
            from app.platform.cache.provider import get_cache
            import hashlib

            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            cache = get_cache()
            await cache.delete(f"embed_token:{token_hash}")

            # Tile request should fail
            tile_resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_access_revoked_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Revoked embed token is rejected (EMBED-04, EMBED-06)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_rev_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create embed token
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]
            token_id = create_resp.json()["id"]

            # Revoke via API
            revoke_resp = await client.delete(
                f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
                headers=admin_auth_header,
            )
            assert revoke_resp.status_code == 200

            # Tile request should fail
            tile_resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tile_access_no_embed_token_falls_through(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Without X-Embed-Token, non-public tiles require HMAC sig (EMBED-04)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_fall_{uuid.uuid4().hex[:8]}"
        await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Request without X-Embed-Token and without HMAC sig
            tile_resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert tile_resp.status_code == 403
            assert "Signature required" in tile_resp.json()["detail"]
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_cache_hit_avoids_db_query(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """EMBED-05: Second tile request succeeds via cache path."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_cache_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create embed token
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]

            # First request -- populates cache
            tile_resp1 = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp1.status_code in (200, 204)

            # Second request -- should use cache
            tile_resp2 = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp2.status_code in (200, 204)
        finally:
            await _cleanup_data_table(test_db_session, table_name)


# ---------------------------------------------------------------------------
# Tests: Domain locking (DOMAIN-01 through DOMAIN-04)
# ---------------------------------------------------------------------------


class TestCreateEmbedTokenWithOrigins:
    """DOMAIN-01: Token creation with allowed_origins."""

    pytestmark = pytest.mark.usefixtures("enterprise_edition")

    async def test_create_with_allowed_origins(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Create token with allowed_origins and verify it is returned."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "Locked", "allowed_origins": ["https://example.com"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["allowed_origins"] == ["https://example.com"]


class TestTileDomainLocking:
    """DOMAIN-02, DOMAIN-03, DOMAIN-04: Origin validation on tile requests."""

    pytestmark = pytest.mark.usefixtures("enterprise_edition")

    async def _setup(
        self,
        test_db_session,
        client,
        admin_auth_header,
        allowed_origins,
        cleanup_data_tables,
    ):
        """Helper: create dataset, map, data table, and embed token."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = cleanup_data_tables(f"embed_dl_{uuid.uuid4().hex[:8]}")
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"allowed_origins": allowed_origins},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        raw_token = create_resp.json()["raw_token"]

        # Clear cache to ensure fresh validation path
        import hashlib as _hl
        from app.platform.cache.provider import get_cache

        token_hash = _hl.sha256(raw_token.encode()).hexdigest()
        cache = get_cache()
        await cache.delete(f"embed_token:{token_hash}")

        return table_name, raw_token

    async def test_tile_allowed_origin_passes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        cleanup_data_tables,
    ):
        """Token with allowed_origins, request with matching Origin header -> 200."""
        table_name, raw_token = await self._setup(
            test_db_session,
            client,
            admin_auth_header,
            ["https://example.com"],
            cleanup_data_tables,
        )
        resp = await client.get(
            f"/tiles/data.{table_name}/0/0/0.pbf",
            headers={"X-Embed-Token": raw_token, "Origin": "https://example.com"},
        )
        assert resp.status_code in (200, 204)

    async def test_tile_unlisted_origin_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        cleanup_data_tables,
    ):
        """Token with allowed_origins, request with unlisted Origin -> 403."""
        table_name, raw_token = await self._setup(
            test_db_session,
            client,
            admin_auth_header,
            ["https://example.com"],
            cleanup_data_tables,
        )
        resp = await client.get(
            f"/tiles/data.{table_name}/0/0/0.pbf",
            headers={"X-Embed-Token": raw_token, "Origin": "https://evil.com"},
        )
        assert resp.status_code == 403

    async def test_tile_no_origin_header_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        cleanup_data_tables,
    ):
        """Token with domain-locking, no Origin/Referer -> 403."""
        table_name, raw_token = await self._setup(
            test_db_session,
            client,
            admin_auth_header,
            ["https://example.com"],
            cleanup_data_tables,
        )
        resp = await client.get(
            f"/tiles/data.{table_name}/0/0/0.pbf",
            headers={"X-Embed-Token": raw_token},
        )
        assert resp.status_code == 403

    async def test_tile_null_origins_unrestricted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        cleanup_data_tables,
    ):
        """Token with allowed_origins=None, any origin -> 200."""
        table_name, raw_token = await self._setup(
            test_db_session, client, admin_auth_header, None, cleanup_data_tables
        )
        resp = await client.get(
            f"/tiles/data.{table_name}/0/0/0.pbf",
            headers={"X-Embed-Token": raw_token, "Origin": "https://anything.com"},
        )
        assert resp.status_code in (200, 204)

    async def test_tile_localhost_auto_allowed(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        cleanup_data_tables,
    ):
        """Token with domain-locking, localhost Origin -> 200 (auto-allowed)."""
        table_name, raw_token = await self._setup(
            test_db_session,
            client,
            admin_auth_header,
            ["https://example.com"],
            cleanup_data_tables,
        )
        resp = await client.get(
            f"/tiles/data.{table_name}/0/0/0.pbf",
            headers={"X-Embed-Token": raw_token, "Origin": "http://localhost:3000"},
        )
        assert resp.status_code in (200, 204)

    async def test_tile_referer_fallback(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        cleanup_data_tables,
    ):
        """Token with domain-locking, no Origin but Referer matches -> 200."""
        table_name, raw_token = await self._setup(
            test_db_session,
            client,
            admin_auth_header,
            ["https://example.com"],
            cleanup_data_tables,
        )
        resp = await client.get(
            f"/tiles/data.{table_name}/0/0/0.pbf",
            headers={
                "X-Embed-Token": raw_token,
                "Referer": "https://example.com/page/1",
            },
        )
        assert resp.status_code in (200, 204)


# ---------------------------------------------------------------------------
# Tests: Usage tracking (OBS-01)
# ---------------------------------------------------------------------------


class TestUsageTracking:
    """OBS-01: use_count and last_used_at tracking on cache miss."""

    async def test_usage_tracking_on_cache_miss(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Cache miss triggers atomic use_count increment and last_used_at update."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_usage_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create embed token
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]
            token_id = create_resp.json()["id"]

            # Clear cache to force cache miss
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            cache = get_cache()
            await cache.delete(f"embed_token:{token_hash}")

            # Make tile request (cache miss -> DB lookup -> usage tracking)
            tile_resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp.status_code in (200, 204)

            # Verify use_count and last_used_at in DB
            test_db_session.expire_all()
            result = await test_db_session.execute(
                select(EmbedToken).where(EmbedToken.id == uuid.UUID(token_id))
            )
            token = result.scalar_one()
            assert token.use_count == 1
            assert token.last_used_at is not None
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_usage_tracking_not_on_cache_hit(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Cache hit does not increment use_count."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_cache_hit_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create embed token
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]
            token_id = create_resp.json()["id"]

            # Clear cache and make first request (cache miss -> use_count=1)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            cache = get_cache()
            await cache.delete(f"embed_token:{token_hash}")

            tile_resp1 = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp1.status_code in (200, 204)

            # Second request (cache hit -> no increment)
            tile_resp2 = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp2.status_code in (200, 204)

            # Expire the session cache to get fresh DB read
            test_db_session.expire_all()
            result = await test_db_session.execute(
                select(EmbedToken).where(EmbedToken.id == uuid.UUID(token_id))
            )
            token = result.scalar_one()
            assert token.use_count == 1  # Only 1 from cache miss, not 2
        finally:
            await _cleanup_data_table(test_db_session, table_name)


# ---------------------------------------------------------------------------
# Tests: Admin embed token list (OBS-02, ADMIN-01, ADMIN-02)
# ---------------------------------------------------------------------------


class TestAdminEmbedTokenList:
    """Admin list endpoint for all embed tokens."""

    async def test_admin_list_all_tokens(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /admin/embed-tokens/ returns tokens with map_name, creator_username, usage stats."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset1 = await _create_private_dataset(test_db_session, created_by=user_id)
        dataset2 = await _create_private_dataset(test_db_session, created_by=user_id)
        map1, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset1, created_by=user_id
        )
        map2, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset2, created_by=user_id
        )

        # Create tokens on different maps
        for m in [map1, map2]:
            resp = await client.post(
                f"/maps/{m.id}/embed-tokens/",
                json={"name": f"Token for {m.name}"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201

        # Admin list
        resp = await client.get(
            "/admin/embed-tokens/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["tokens"]) >= 2

        # Check response fields
        token = data["tokens"][0]
        assert "map_name" in token
        assert "creator_username" in token
        assert "use_count" in token
        assert "last_used_at" in token
        assert "allowed_origins" in token
        assert "token_hint" in token

    async def test_admin_list_filter_by_status(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Filter by status=revoked returns only revoked tokens."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create and revoke a token
        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "To Revoke Admin"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        token_id = create_resp.json()["id"]

        revoke_resp = await client.delete(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
            headers=admin_auth_header,
        )
        assert revoke_resp.status_code == 200

        # Filter by revoked
        resp = await client.get(
            "/admin/embed-tokens/?status=revoked",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        # All returned tokens should be revoked
        for token in data["tokens"]:
            assert token["is_active"] is False

    async def test_admin_list_requires_admin(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Non-admin user gets 403."""
        # Create a viewer user
        viewer_resp = await client.post(
            "/admin/users/",
            json={
                "username": f"viewer_{uuid.uuid4().hex[:6]}",
                "password": "testpass123",
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert viewer_resp.status_code == 201
        viewer_username = viewer_resp.json()["username"]

        # Login as viewer
        login_resp = await client.post(
            "/auth/login/",
            data={"username": viewer_username, "password": "testpass123"},
        )
        assert login_resp.status_code == 200
        viewer_token = login_resp.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # Try admin endpoint
        resp = await client.get(
            "/admin/embed-tokens/",
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: Bulk revoke (ADMIN-03)
# ---------------------------------------------------------------------------


class TestBulkRevokeEmbedTokens:
    """Bulk revoke endpoint for embed tokens."""

    async def test_bulk_revoke(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Bulk-revoke 2 of 3 tokens; verify revoked_count and remaining active."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        token_ids: list[str] = []
        map_ids: list[str] = []
        for i in range(3):
            dataset = await _create_private_dataset(test_db_session, created_by=user_id)
            map_obj, _ = await _create_map_with_layer(
                test_db_session,
                client,
                admin_auth_header,
                dataset,
                created_by=user_id,
            )
            resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={"name": f"Bulk {i}"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201
            token_ids.append(resp.json()["id"])
            map_ids.append(str(map_obj.id))

        # Bulk revoke first 2
        resp = await client.post(
            "/admin/embed-tokens/bulk-revoke/",
            json={"token_ids": token_ids[:2]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["revoked_count"] == 2

        # Verify third token still active
        list_resp = await client.get(
            f"/maps/{map_ids[2]}/embed-tokens/",
            headers=admin_auth_header,
        )
        tokens = list_resp.json()["tokens"]
        third = [t for t in tokens if t["id"] == token_ids[2]]
        assert len(third) == 1
        assert third[0]["is_active"] is True

    async def test_bulk_revoke_skips_already_revoked(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Already-revoked tokens are skipped in bulk revoke count."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        token_ids: list[str] = []
        map_ids: list[str] = []
        for i in range(2):
            dataset = await _create_private_dataset(test_db_session, created_by=user_id)
            map_obj, _ = await _create_map_with_layer(
                test_db_session,
                client,
                admin_auth_header,
                dataset,
                created_by=user_id,
            )
            resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={"name": f"Skip {i}"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201
            token_ids.append(resp.json()["id"])
            map_ids.append(str(map_obj.id))

        # Revoke first token individually
        revoke_resp = await client.delete(
            f"/maps/{map_ids[0]}/embed-tokens/{token_ids[0]}/",
            headers=admin_auth_header,
        )
        assert revoke_resp.status_code == 200

        # Bulk revoke both (first already revoked)
        resp = await client.post(
            "/admin/embed-tokens/bulk-revoke/",
            json={"token_ids": token_ids},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        # Only the second should count as newly revoked
        assert resp.json()["revoked_count"] == 1


# ---------------------------------------------------------------------------
# Tests: Update embed token (EMBED-01, EMBED-02, EMBED-03)
# ---------------------------------------------------------------------------


class TestUpdateEmbedToken:
    """PATCH endpoint for updating embed token allowed_origins."""

    pytestmark = pytest.mark.usefixtures("enterprise_edition")

    async def test_patch_embed_token_update_origins(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH with allowed_origins updates domain restrictions."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create token with no origins (unrestricted)
        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "Update Test"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        token_id = create_resp.json()["id"]

        # PATCH with new origins
        patch_resp = await client.patch(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
            json={"allowed_origins": ["https://new.com"]},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 200, patch_resp.text
        data = patch_resp.json()
        assert data["allowed_origins"] == ["https://new.com"]
        assert data["id"] == token_id

    async def test_patch_embed_token_remove_origins(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH with allowed_origins=null removes restrictions (unrestricted)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create token with origins (restricted)
        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "Remove Test", "allowed_origins": ["https://example.com"]},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        token_id = create_resp.json()["id"]

        # PATCH with null to remove restrictions
        patch_resp = await client.patch(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
            json={"allowed_origins": None},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 200, patch_resp.text
        data = patch_resp.json()
        assert data["allowed_origins"] is None

    async def test_patch_embed_token_add_origins_to_unrestricted(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH with origins on an unrestricted token adds restrictions (auto-prepends https://)."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create unrestricted token
        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "Add Origins"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        token_id = create_resp.json()["id"]
        assert create_resp.json()["allowed_origins"] is None

        # PATCH with bare domain (should auto-prepend https://)
        patch_resp = await client.patch(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
            json={"allowed_origins": ["example.com"]},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 200, patch_resp.text
        data = patch_resp.json()
        assert data["allowed_origins"] == ["https://example.com"]

    async def test_patch_embed_token_not_found(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH on nonexistent token_id returns 404."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        fake_id = uuid.uuid4()
        patch_resp = await client.patch(
            f"/maps/{map_obj.id}/embed-tokens/{fake_id}/",
            json={"allowed_origins": ["https://example.com"]},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 404

    async def test_patch_embed_token_non_owner(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH by non-owner returns 403."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # Create a token
        create_resp = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/",
            json={"name": "Non-owner Test"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        token_id = create_resp.json()["id"]

        # Create a viewer user
        viewer_resp = await client.post(
            "/admin/users/",
            json={
                "username": f"viewer_patch_{uuid.uuid4().hex[:6]}",
                "password": "testpass123",
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert viewer_resp.status_code == 201
        viewer_username = viewer_resp.json()["username"]

        # Login as viewer
        login_resp = await client.post(
            "/auth/login/",
            data={"username": viewer_username, "password": "testpass123"},
        )
        assert login_resp.status_code == 200
        viewer_token = login_resp.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # PATCH as viewer -> 403
        patch_resp = await client.patch(
            f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
            json={"allowed_origins": ["https://example.com"]},
            headers=viewer_headers,
        )
        assert patch_resp.status_code == 403

    async def test_patch_embed_token_cache_invalidation(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """After PATCH, tile request with new origin succeeds and old origin fails."""
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_patch_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Create token with old origin
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={"allowed_origins": ["https://old.com"]},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]
            token_id = create_resp.json()["id"]

            # Verify old origin works
            tile_resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token, "Origin": "https://old.com"},
            )
            assert tile_resp.status_code in (200, 204)

            # PATCH to new origin
            patch_resp = await client.patch(
                f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
                json={"allowed_origins": ["https://new.com"]},
                headers=admin_auth_header,
            )
            assert patch_resp.status_code == 200

            # Old origin should now fail (cache invalidated)
            tile_resp_old = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token, "Origin": "https://old.com"},
            )
            assert tile_resp_old.status_code == 403

            # New origin should work
            tile_resp_new = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token, "Origin": "https://new.com"},
            )
            assert tile_resp_new.status_code in (200, 204)
        finally:
            await _cleanup_data_table(test_db_session, table_name)
