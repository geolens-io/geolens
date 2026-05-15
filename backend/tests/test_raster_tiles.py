"""Integration tests for raster tile auth-check endpoint and raster token branch.

Tests:
  - GET /tiles/raster-auth-check/?dataset_id=... (nginx auth_request target)
  - GET /tiles/token/{dataset_id}/ raster branch

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _create_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
    record_type: str = "raster_dataset",
    with_asset: bool = True,
) -> tuple[Record, Dataset, RasterAsset | None]:
    """Create a Record + Dataset (+ optional RasterAsset) for raster tests."""
    record = Record(
        title=f"Raster Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for raster tile tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type=record_type,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_tile_test_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = None
    if with_asset:
        raster_asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/abc123/source.cog.tif",
            storage_backend="local",
        )
        session.add(raster_asset)
        await session.flush()

    await session.commit()
    await session.refresh(dataset)
    if raster_asset:
        await session.refresh(raster_asset)
    return record, dataset, raster_asset


async def _create_vector_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
) -> tuple[Record, Dataset]:
    """Create a vector Record + Dataset for contrast tests."""
    record = Record(
        title=f"Vector Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for vector tile contrast tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vector_tile_test_{uuid.uuid4().hex[:8]}",
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return record, dataset


async def _get_auth_header(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Auth-check endpoint tests
# ---------------------------------------------------------------------------


class TestRasterAuthCheck:
    """Tests for GET /tiles/raster-auth-check/?dataset_id=..."""

    async def test_auth_check_returns_open_path_for_public_raster(
        self, client: AsyncClient, test_db_session
    ):
        """Public raster dataset, no auth -> 200 with X-GeoLens-Asset-OpenPath header."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 200
        open_path = resp.headers.get("x-geolens-asset-openpath")
        assert open_path is not None
        assert asset.asset_uri in open_path
        # Path should use the configured staging dir (overridden to tmp in tests)
        assert open_path.endswith(asset.asset_uri)
        assert resp.headers.get("x-geolens-cache-status") == "public"

    async def test_auth_check_returns_open_path_for_authenticated_user(
        self, client: AsyncClient, test_db_session
    ):
        """Private raster, valid JWT for owner -> 200 with X-GeoLens-Asset-OpenPath."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        auth_header = await _get_auth_header(
            client,
            settings.geolens_admin_username,
            settings.geolens_admin_password.get_secret_value(),
        )
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=auth_header,
        )
        assert resp.status_code == 200
        open_path = resp.headers.get("x-geolens-asset-openpath")
        assert open_path is not None
        assert open_path.endswith(asset.asset_uri)
        assert resp.headers.get("x-geolens-cache-status") == "private"

    async def test_auth_check_401_for_unauthenticated_private(
        self, client: AsyncClient, test_db_session
    ):
        """Private raster, no auth -> 401."""
        admin_id = await _get_admin_id(test_db_session)
        await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        # Use a fresh private dataset
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 401

    async def test_auth_check_404_for_nonexistent_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Random UUID -> 404."""
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_auth_check_404_for_vector_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Vector dataset ID -> 404 (not a raster dataset)."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset = await _create_vector_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 404

    async def test_auth_check_404_for_no_raster_asset(
        self, client: AsyncClient, test_db_session
    ):
        """Raster record type but no raster_assets row -> 404."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, _ = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public", with_asset=False
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 404

    async def test_auth_check_403_for_invalid_embed_token(
        self, client: AsyncClient, test_db_session
    ):
        """X-Embed-Token header with invalid token -> 403."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers={"X-Embed-Token": "invalid_token_xyz"},
        )
        assert resp.status_code == 403

    async def test_auth_check_blocks_unpublished_for_non_owner(
        self, client: AsyncClient, test_db_session, admin_auth_header: dict
    ):
        """Draft raster, different user -> 404."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="draft",
        )

        # Create a non-owner user
        unique = uuid.uuid4().hex[:8]
        username = f"viewer_{unique}"
        password = "testpass123"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": password, "role": "viewer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        viewer_header = await _get_auth_header(client, username, password)

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=viewer_header,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# RBAC regression: inline raster auth vs check_dataset_access
# ---------------------------------------------------------------------------


class TestRasterAuthRbacParity:
    """Verify the inline RBAC in raster_auth_check mirrors check_dataset_access."""

    async def test_private_dataset_non_owner_blocked_by_both_paths(
        self, client: AsyncClient, test_db_session
    ):
        """Private dataset: non-owner viewer is blocked by raster auth (inline RBAC)
        AND by the token endpoint (check_dataset_access). Both must agree."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        admin_auth_header = await _get_auth_header(
            client,
            settings.geolens_admin_username,
            settings.geolens_admin_password.get_secret_value(),
        )
        username = f"rbac_parity_{uuid.uuid4().hex[:6]}"
        password = "testpass123"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": password, "role": "viewer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        viewer_header = await _get_auth_header(client, username, password)

        # Path A: inline RBAC in raster-auth-check
        auth_check_resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=viewer_header,
        )

        # Path B: check_dataset_access in token endpoint
        token_resp = await client.get(
            f"/tiles/token/{dataset.id}/",
            headers=viewer_header,
        )

        # Both must block the non-owner viewer
        assert auth_check_resp.status_code in (403, 404), (
            f"raster-auth-check returned {auth_check_resp.status_code}, expected 403/404"
        )
        assert token_resp.status_code in (403, 404), (
            f"token endpoint returned {token_resp.status_code}, expected 403/404"
        )

    async def test_public_dataset_accessible_by_both_paths(
        self, client: AsyncClient, test_db_session
    ):
        """Public dataset: unauthenticated access succeeds on both paths."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        # Path A: raster-auth-check (no auth)
        auth_check_resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )

        # Path B: token endpoint (no auth)
        token_resp = await client.get(f"/tiles/token/{dataset.id}/")

        # Both must allow access
        assert auth_check_resp.status_code == 200
        assert token_resp.status_code == 200


# ---------------------------------------------------------------------------
# Token endpoint tests
# ---------------------------------------------------------------------------


class TestRasterTokenEndpoint:
    """Tests for GET /tiles/token/{dataset_id}/ raster branch."""

    async def test_raster_token_returns_kind_raster(
        self, client: AsyncClient, test_db_session
    ):
        """Raster dataset -> response has kind=raster, tile_url, bounds, zoom, etc."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "raster"
        assert "tile_url" in data
        assert "{z}" in data["tile_url"]
        assert "{x}" in data["tile_url"]
        assert "{y}" in data["tile_url"]
        assert str(dataset.id) in data["tile_url"]
        assert "bounds" in data
        assert "minzoom" in data
        assert "maxzoom" in data
        assert "tile_size" in data
        assert "format" in data
        assert data["tile_size"] == 256
        assert data["format"] == "png"

    async def test_raster_token_no_credentials_in_response(
        self, client: AsyncClient, test_db_session
    ):
        """Raster token response body contains no COG path, no asset_uri, no titiler URL."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        body = resp.text
        # Must not leak internal paths in response body
        assert "titiler" not in body.lower()
        assert "/vsis3" not in body
        assert "source.cog.tif" not in body
        assert "asset_uri" not in body

    async def test_vector_token_returns_kind_vector(
        self, client: AsyncClient, test_db_session
    ):
        """Vector dataset -> existing response fields + kind=vector."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset = await _create_vector_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "vector"
        # Original fields still present
        assert "sig" in data
        assert "exp" in data
        assert "scope" in data
        assert "expires_in" in data

    async def test_raster_token_401_for_private_unauthenticated(
        self, client: AsyncClient, test_db_session
    ):
        """Private raster, no auth -> 401."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 401
