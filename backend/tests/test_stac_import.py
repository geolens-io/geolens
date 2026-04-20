"""Tests for STAC catalog import endpoints.

Tests cover: connect, collections, search, import — with mocked external
STAC API responses. Also covers SSRF validation, auth requirements,
duplicate detection, and partial import failure handling.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Canned STAC API responses
# ---------------------------------------------------------------------------

STAC_LANDING = {
    "id": "test-catalog",
    "type": "Catalog",
    "title": "Test STAC Catalog",
    "description": "A test catalog",
    "stac_version": "1.0.0",
    "conformsTo": ["https://api.stacspec.org/v1.0.0/core"],
}

STAC_COLLECTIONS = {
    "collections": [
        {
            "id": "dem-collection",
            "title": "DEM Collection",
            "description": "Digital elevation models",
            "license": "proprietary",
            "keywords": ["dem", "elevation"],
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {
                    "interval": [["2021-01-01T00:00:00Z", "2021-12-31T00:00:00Z"]]
                },
            },
        },
        {
            "id": "imagery",
            "title": "Satellite Imagery",
            "description": "Multi-spectral imagery",
            "license": "CC-BY-4.0",
            "keywords": ["satellite"],
            "extent": {
                "spatial": {"bbox": [[-120, 30, -80, 50]]},
                "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]},
            },
        },
    ]
}

STAC_SEARCH_RESULTS = {
    "type": "FeatureCollection",
    "features": [
        {
            "id": "item-001",
            "type": "Feature",
            "collection": "dem-collection",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
            },
            "bbox": [-1, -1, 1, 1],
            "properties": {
                "datetime": "2021-06-15T00:00:00Z",
                "title": "DEM Tile 001",
                "proj:epsg": 4326,
                "gsd": 30,
            },
            "assets": {
                "data": {
                    "href": "https://example.com/data/item-001.tif",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "roles": ["data"],
                },
                "thumbnail": {
                    "href": "https://example.com/thumbs/item-001.png",
                    "type": "image/png",
                    "roles": ["thumbnail"],
                },
            },
        },
        {
            "id": "item-002",
            "type": "Feature",
            "collection": "dem-collection",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[1, -1], [3, -1], [3, 1], [1, 1], [1, -1]]],
            },
            "bbox": [1, -1, 3, 1],
            "properties": {
                "datetime": "2021-06-16T00:00:00Z",
                "title": "DEM Tile 002",
                "proj:epsg": 4326,
                "gsd": 30,
            },
            "assets": {
                "data": {
                    "href": "https://example.com/data/item-002.tif",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "roles": ["data"],
                },
            },
        },
    ],
    "numberMatched": 2,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_stac_ssrf():
    """Patch SSRF validation on STAC router to allow all URLs."""
    with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf") as mock:
        yield mock


@pytest.fixture
def mock_stac_connect():
    """Patch connect_stac_api to return canned landing page."""
    with patch(
        "app.modules.catalog.sources.stac_router.connect_stac_api",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = {
            "id": "test-catalog",
            "title": "Test STAC Catalog",
            "description": "A test catalog",
            "stac_version": "1.0.0",
            "conforms_to": [],
        }
        yield mock


@pytest.fixture
def mock_stac_collections():
    """Patch list_stac_collections to return canned collections."""
    with patch(
        "app.modules.catalog.sources.stac_router.list_stac_collections",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = [
            {
                "id": "dem-collection",
                "title": "DEM Collection",
                "description": "Digital elevation models",
                "license": "proprietary",
                "keywords": ["dem", "elevation"],
                "bbox": [-180, -90, 180, 90],
                "temporal_start": "2021-01-01T00:00:00Z",
                "temporal_end": "2021-12-31T00:00:00Z",
                "item_count": 100,
            },
        ]
        yield mock


@pytest.fixture
def mock_stac_search():
    """Patch search_stac_items to return canned items."""
    with patch(
        "app.modules.catalog.sources.stac_router.search_stac_items",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = {
            "items": [
                {
                    "id": "item-001",
                    "collection": "dem-collection",
                    "bbox": [-1, -1, 1, 1],
                    "datetime": "2021-06-15T00:00:00Z",
                    "datetime_start": "2021-06-15T00:00:00Z",
                    "datetime_end": "2021-06-15T00:00:00Z",
                    "title": "DEM Tile 001",
                    "epsg": 4326,
                    "gsd": 30,
                    "cloud_cover": None,
                    "data_asset_href": "https://example.com/data/item-001.tif",
                    "data_asset_type": "image/tiff",
                    "thumbnail_href": "https://example.com/thumbs/item-001.png",
                    "asset_count": 2,
                },
            ],
            "matched": 1,
            "returned": 1,
        }
        yield mock


# ---------------------------------------------------------------------------
# Connect endpoint
# ---------------------------------------------------------------------------


class TestStacConnect:
    async def test_connect_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        mock_stac_connect,
    ):
        resp = await client.post(
            "/services/stac/connect",
            json={"url": "https://stac.example.com/v1"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["catalog_id"] == "test-catalog"
        assert data["title"] == "Test STAC Catalog"
        assert data["stac_version"] == "1.0.0"

    async def test_connect_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/services/stac/connect",
            json={"url": "https://stac.example.com/v1"},
        )
        assert resp.status_code == 401

    async def test_connect_not_stac(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        with patch(
            "app.modules.catalog.sources.stac_router.connect_stac_api",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                "/services/stac/connect",
                json={"url": "https://not-stac.example.com"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 400
            assert "not appear to be a valid STAC API" in resp.json()["detail"]

    async def test_connect_ssrf_blocked(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        with patch(
            "app.modules.catalog.sources.stac_router.validate_url_for_ssrf",
            side_effect=__import__(
                "app.modules.catalog.sources.security", fromlist=["SSRFError"]
            ).SSRFError("URLs targeting private/internal networks are not allowed"),
        ):
            resp = await client.post(
                "/services/stac/connect",
                json={"url": "http://169.254.169.254/latest/meta-data"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 400
            assert "private" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Collections endpoint
# ---------------------------------------------------------------------------


class TestStacCollections:
    async def test_collections_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        mock_stac_collections,
    ):
        resp = await client.post(
            "/services/stac/collections",
            json={"url": "https://stac.example.com/v1"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["collections"]) == 1
        assert data["collections"][0]["id"] == "dem-collection"
        assert data["collections"][0]["title"] == "DEM Collection"

    async def test_collections_fetch_failure(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        with patch(
            "app.modules.catalog.sources.stac_router.list_stac_collections",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            resp = await client.post(
                "/services/stac/collections",
                json={"url": "https://unreachable.example.com"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------


class TestStacSearch:
    async def test_search_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        mock_stac_search,
    ):
        resp = await client.post(
            "/services/stac/search",
            json={
                "url": "https://stac.example.com/v1",
                "collections": ["dem-collection"],
                "limit": 10,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["returned"] == 1
        assert data["items"][0]["id"] == "item-001"
        assert data["items"][0]["epsg"] == 4326

    async def test_search_invalid_bbox_length(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        resp = await client.post(
            "/services/stac/search",
            json={
                "url": "https://stac.example.com/v1",
                "bbox": [1.0, 2.0],  # too short
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_search_fetch_failure(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        with patch(
            "app.modules.catalog.sources.stac_router.search_stac_items",
            new_callable=AsyncMock,
            side_effect=Exception("Timeout"),
        ):
            resp = await client.post(
                "/services/stac/search",
                json={"url": "https://stac.example.com/v1"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------


class TestStacImport:
    async def test_import_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": f"test-item-{uuid.uuid4().hex[:8]}",
                        "collection": "dem-collection",
                        "title": "Test DEM Import",
                        "data_asset_href": "https://example.com/data/test.tif",
                        "bbox": [-1, -1, 1, 1],
                        "epsg": 4326,
                        "datetime_start": "2021-06-15T00:00:00Z",
                        "datetime_end": "2021-06-15T00:00:00Z",
                        "keywords": ["dem"],
                    }
                ],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert data["errors"] == 0
        assert data["results"][0]["status"] == "created"
        assert data["results"][0]["dataset_id"] is not None

    async def test_import_duplicate_skipped(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        item_id = f"dup-test-{uuid.uuid4().hex[:8]}"
        href = f"https://example.com/data/dup-{uuid.uuid4().hex[:8]}.tif"
        payload = {
            "url": "https://stac.example.com/v1",
            "items": [
                {
                    "id": item_id,
                    "title": "Duplicate Test",
                    "data_asset_href": href,
                    "keywords": [],
                }
            ],
            "visibility": "private",
        }

        # First import — should create
        resp1 = await client.post(
            "/services/stac/import", json=payload, headers=admin_auth_header
        )
        assert resp1.json()["created"] == 1

        # Second import — same href, should skip
        payload["items"][0]["id"] = f"dup-test-2-{uuid.uuid4().hex[:8]}"
        resp2 = await client.post(
            "/services/stac/import", json=payload, headers=admin_auth_header
        )
        assert resp2.json()["skipped"] == 1
        assert resp2.json()["results"][0]["status"] == "skipped"

    async def test_import_invalid_visibility(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": "vis-test",
                        "title": "Vis Test",
                        "data_asset_href": "https://example.com/test.tif",
                        "keywords": [],
                    }
                ],
                "visibility": "INVALID",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_import_ssrf_blocks_internal_url(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """Asset URLs pointing to internal networks are rejected per-item."""
        from app.modules.catalog.sources.security import SSRFError

        with patch(
            "app.modules.catalog.sources.stac_router.validate_url_for_ssrf",
            side_effect=lambda url: (
                (_ for _ in ()).throw(
                    SSRFError(
                        "URLs targeting private/internal networks are not allowed"
                    )
                )
                if "internal" in url
                else None
            ),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": "ssrf-test",
                            "title": "SSRF Test",
                            "data_asset_href": "http://internal.corp/secret.tif",
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["errors"] == 1
            assert "private" in data["results"][0]["error"].lower()

    async def test_import_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": "x",
                        "title": "X",
                        "data_asset_href": "https://e.com/x.tif",
                        "keywords": [],
                    }
                ],
                "visibility": "private",
            },
        )
        assert resp.status_code == 401

    async def test_import_empty_items_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


class TestStacAdapter:
    """Unit tests for the STAC adapter functions with mocked httpx."""

    async def test_connect_stac_api_success(self):
        from app.modules.catalog.sources.adapters.stac import connect_stac_api

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = STAC_LANDING
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=mock_client,
        ):
            result = await connect_stac_api("https://stac.example.com/v1")

        assert result is not None
        assert result["id"] == "test-catalog"
        assert result["stac_version"] == "1.0.0"

    async def test_connect_stac_api_not_stac(self):
        from app.modules.catalog.sources.adapters.stac import connect_stac_api

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"type": "html", "content": "not stac"}
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=mock_client,
        ):
            result = await connect_stac_api("https://not-stac.example.com")

        assert result is None

    async def test_connect_stac_api_http_error(self):
        import httpx
        from app.modules.catalog.sources.adapters.stac import connect_stac_api

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TransportError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=mock_client,
        ):
            result = await connect_stac_api("https://unreachable.example.com")

        assert result is None

    async def test_list_collections(self):
        from app.modules.catalog.sources.adapters.stac import list_stac_collections

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = STAC_COLLECTIONS
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=mock_client,
        ):
            result = await list_stac_collections("https://stac.example.com/v1")

        assert len(result) == 2
        assert result[0]["id"] == "dem-collection"
        assert result[0]["bbox"] == [-180, -90, 180, 90]
        assert result[1]["id"] == "imagery"

    async def test_search_items(self):
        from app.modules.catalog.sources.adapters.stac import search_stac_items

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = STAC_SEARCH_RESULTS
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=mock_client,
        ):
            result = await search_stac_items(
                "https://stac.example.com/v1",
                collections=["dem-collection"],
                limit=10,
            )

        assert result["matched"] == 2
        assert result["returned"] == 2
        assert result["items"][0]["id"] == "item-001"
        assert result["items"][0]["epsg"] == 4326
        assert (
            result["items"][0]["data_asset_href"]
            == "https://example.com/data/item-001.tif"
        )
        assert result["items"][1]["thumbnail_href"] is None
