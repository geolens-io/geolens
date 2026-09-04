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
from sqlalchemy import text


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
                "proj:code": "EPSG:4326",
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
                "app.platform.security", fromlist=["SSRFError"]
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


async def _create_stac_dataset(
    session,
    *,
    created_by,
    source_url,
    name="Existing STAC Dataset",
    origin_uri=None,
    origin_ref=None,
):
    """Insert a Dataset simulating a previously imported STAC item.

    ``origin_uri``/``origin_ref`` default to unset — the shape of a row
    migration 0036 could not backfill — so callers that want a fully-bound
    (post-#1218) dataset, or one with a deliberately mismatched pair to
    reproduce a respelling writer, pass both explicitly.
    """
    import uuid as _uuid

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    table_name = f"stac_{_uuid.uuid4().hex[:16]}"
    record = Record(
        title=name,
        summary="STAC import test",
        visibility="private",
        record_status="published",
        created_by=created_by,
        record_type="raster_dataset",
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="stac",
        source_url=source_url,
        source_filename="existing-item",
        origin_uri=origin_uri,
        origin_ref=origin_ref,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


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

        # fix(#1271 review): no Titiler answered in this environment, so
        # fetch_cog_info returned None and nobody can show the origin was
        # contacted — the field stays NULL until a probe settles it. The
        # contacted case is pinned separately below.
        detail = await client.get(
            f"/datasets/{data['results'][0]['dataset_id']}",
            headers=admin_auth_header,
        )
        assert detail.status_code == 200
        assert detail.json()["last_checked_at"] is None
        assert detail.json()["source_health"] == "unknown"

    async def test_import_persists_the_origin_asset_for_generic_clients(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_stac_ssrf,
    ):
        """feat(#1692): the served STAC item carries a readable COG href.

        Before this, a by-reference import stored no ``dataset_assets`` row,
        so the item GeoLens re-published exposed exactly one asset — the
        internal ``raster_tiles`` XYZ template, which renders only in
        GeoLens's own frontend. A generic STAC client (stac-browser, the
        QGIS STAC plugin) could discover the item but had no pixel data to
        read. The import now persists the origin item's primary data asset,
        and the item endpoint serves it verbatim beside the tiles template,
        roled ``data`` against the template's ``visual``.
        """
        from sqlalchemy import select

        from app.processing.raster.models import DatasetAsset

        cog_href = f"https://example.com/data/origin-{uuid.uuid4().hex[:8]}.tif"
        cog_type = "image/tiff; application=geotiff; profile=cloud-optimized"
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": f"origin-asset-{uuid.uuid4().hex[:8]}",
                        "collection": "dem-collection",
                        "title": "Origin Asset Import",
                        "data_asset_href": cog_href,
                        "data_asset_type": cog_type,
                        "data_asset_key": "data",
                        "bbox": [-1, -1, 1, 1],
                        "keywords": [],
                    }
                ],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 1
        dataset_id = resp.json()["results"][0]["dataset_id"]

        # The stored row: the origin COG, roled as the data asset.
        row = (
            await test_db_session.execute(
                select(DatasetAsset).where(
                    DatasetAsset.dataset_id == uuid.UUID(dataset_id),
                    DatasetAsset.key == "data",
                )
            )
        ).scalar_one()
        assert row.href == cog_href
        assert row.media_type == cog_type
        assert row.roles == ["data"]

        # The served item, read the way a generic client reads it. The
        # remote href passes through resolve_asset_url untouched — it is
        # not managed storage, so neither presigning nor the GAP-031 proxy
        # refusal applies — and it sits BESIDE the tiles template, each
        # roled as what it is.
        item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)
        assert item.status_code == 200, item.text
        assets = item.json()["assets"]
        assert assets["data"]["href"] == cog_href
        assert assets["data"]["type"] == cog_type
        assert assets["data"]["roles"] == ["data"]
        assert assets["raster_tiles"]["roles"] == ["visual"]

        # And the dataset detail's stac_assets mirror — the surface the
        # issue observed as null on a by-reference Sentinel-2 dataset.
        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200
        assert detail.json()["stac_assets"]["data"]["href"] == cog_href

    async def test_import_without_a_declared_type_still_persists_the_href(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_stac_ssrf,
    ):
        """feat(#1692): the type echo is optional, like the other echoes.

        An older client — or an item whose asset declares no ``type`` —
        still imports, and still gets the pass-through asset; the row simply
        carries no media type until the first refresh reads one off the live
        item document.
        """
        from sqlalchemy import select

        from app.processing.raster.models import DatasetAsset

        cog_href = f"https://example.com/data/untyped-{uuid.uuid4().hex[:8]}.tif"
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": f"untyped-{uuid.uuid4().hex[:8]}",
                        "title": "Untyped Origin Asset",
                        "data_asset_href": cog_href,
                        "keywords": [],
                    }
                ],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 1
        dataset_id = resp.json()["results"][0]["dataset_id"]

        row = (
            await test_db_session.execute(
                select(DatasetAsset).where(
                    DatasetAsset.dataset_id == uuid.UUID(dataset_id),
                    DatasetAsset.key == "data",
                )
            )
        ).scalar_one()
        assert row.href == cog_href
        assert row.media_type is None
        assert row.roles == ["data"]

    async def test_import_with_cog_info_stamps_the_contact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        """fix(#1271 review): cog info in hand means Titiler reached the COG
        on GeoLens's behalf — that IS a contact, same contract as
        _finalize_ingest and the reupload swap."""
        with patch(
            "app.modules.catalog.sources.stac_router.fetch_cog_info",
            new=AsyncMock(
                return_value={
                    "band_count": 1,
                    "dtype": "float32",
                    "width": 512,
                    "height": 512,
                    "nodata": None,
                    "band_info": None,
                }
            ),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": f"test-item-{uuid.uuid4().hex[:8]}",
                            "collection": "dem-collection",
                            "title": "Contacted STAC Import",
                            "data_asset_href": "https://example.com/data/c.tif",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 4326,
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1

        detail = await client.get(
            f"/datasets/{data['results'][0]['dataset_id']}",
            headers=admin_auth_header,
        )
        assert detail.status_code == 200
        assert detail.json()["last_checked_at"] is not None
        assert detail.json()["source_health"] == "unknown"

    async def test_import_projects_cog_info_georeferencing_onto_the_asset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        test_db_session,
    ):
        """fix(#1334): fetch_cog_info retrieves crs_wkt for a remote asset
        the same way it retrieves band_count/dtype, but nothing wrote it onto
        the raster_assets row. The Titiler probe already runs at import
        time; this only asks that its answer be kept, the same way its
        other fields already are.

        fix(#1375): this probe result carries no transform, which is the
        case where res_x/res_y stay NULL. The sibling test below covers the
        one that does carry it.
        """
        crs_wkt = (
            'PROJCS["WGS 84 / UTM zone 21N",GEOGCS["WGS 84",'
            'DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
            'PROJECTION["Transverse_Mercator"],'
            'PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",-57],'
            'PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],'
            'PARAMETER["false_northing",0],'
            'UNIT["metre",1],AXIS["Easting",EAST],AXIS["Northing",NORTH],'
            'AUTHORITY["EPSG","32621"]]'
        )
        with patch(
            "app.modules.catalog.sources.stac_router.fetch_cog_info",
            new=AsyncMock(
                return_value={
                    "band_count": 1,
                    "dtype": "uint16",
                    "width": 2658,
                    "height": 2667,
                    "nodata": None,
                    "band_info": None,
                    "crs_wkt": crs_wkt,
                }
            ),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": f"test-item-{uuid.uuid4().hex[:8]}",
                            "collection": "dem-collection",
                            "title": "Georeferenced STAC Import",
                            "data_asset_href": "https://example.com/data/geo.tif",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 32621,
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        dataset_id = data["results"][0]["dataset_id"]

        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200
        raster = detail.json()["raster"]
        # A projected UTM CRS, not geographic — proves crs_wkt round-tripped
        # far enough for PROJ to classify it, not just landed as a string.
        assert raster["crs_is_geographic"] is False
        # A probe that established no transform leaves these NULL rather
        # than guessing — see the docstring above.
        assert raster["res_x"] is None
        assert raster["res_y"] is None

        row = (
            await test_db_session.execute(
                text(
                    "SELECT ra.crs_wkt FROM catalog.raster_assets ra"
                    " JOIN catalog.datasets d ON d.id = ra.dataset_id"
                    " WHERE d.id = :did"
                ).bindparams(did=uuid.UUID(dataset_id))
            )
        ).one()
        assert row.crs_wkt == crs_wkt

    async def test_import_records_the_probed_resolution_and_rotation(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        test_db_session,
    ):
        """fix(#1375): remote raster rows showed "Resolution: — x —" and
        exported no ``gsd``, because #1334 had no source for a resolution it
        could trust. ``fetch_cog_info`` now reads the affine off
        ``/cog/stac``; this asks that the numbers reach the row and the API,
        including the rotation flag, which a remote row could previously
        only report as the column's default ``false``.

        The values are a rotated raster's on purpose: it is the case the
        envelope-division shortcut would have got wrong. 10.0 is the pixel
        size of the same 30°-rotated fixture ``test_cog_info.py`` probes —
        its affine's element 0 is 8.66, and the difference between those two
        numbers is the #1375 review finding.
        """
        with patch(
            "app.modules.catalog.sources.stac_router.fetch_cog_info",
            new=AsyncMock(
                return_value={
                    "band_count": 1,
                    "dtype": "uint16",
                    "width": 2658,
                    "height": 2667,
                    "nodata": None,
                    "band_info": None,
                    "crs_wkt": None,
                    "res_x": 10.0,
                    "res_y": 10.0,
                    "is_rotated": True,
                }
            ),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": f"test-item-{uuid.uuid4().hex[:8]}",
                            "collection": "dem-collection",
                            "title": "Rotated STAC Import",
                            "data_asset_href": "https://example.com/data/rot.tif",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 32621,
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200
        dataset_id = resp.json()["results"][0]["dataset_id"]

        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200
        raster = detail.json()["raster"]
        assert raster["res_x"] == pytest.approx(10.0)
        assert raster["res_y"] == pytest.approx(10.0)

        row = (
            await test_db_session.execute(
                text(
                    "SELECT ra.is_rotated FROM catalog.raster_assets ra"
                    " WHERE ra.dataset_id = :did"
                ).bindparams(did=uuid.UUID(dataset_id))
            )
        ).one()
        assert row.is_rotated is True

    async def test_import_prefers_the_probed_epsg_over_a_stale_item_declaration(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        test_db_session,
    ):
        """fix(#1334 review): the item declares one EPSG (4326, stale or
        simply wrong) while the probe's own CRS says another (32621) — the
        raster row and the dataset's srid mirror the probe, not the item, so
        RasterAsset.to_stac_properties() cannot publish a proj:code and a
        proj:wkt2 that name different projections.
        """
        crs_wkt = (
            'PROJCS["WGS 84 / UTM zone 21N",GEOGCS["WGS 84",'
            'DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
            'PROJECTION["Transverse_Mercator"],'
            'PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",-57],'
            'PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],'
            'PARAMETER["false_northing",0],'
            'UNIT["metre",1],AXIS["Easting",EAST],AXIS["Northing",NORTH],'
            'AUTHORITY["EPSG","32621"]]'
        )
        with patch(
            "app.modules.catalog.sources.stac_router.fetch_cog_info",
            new=AsyncMock(
                return_value={
                    "band_count": 1,
                    "dtype": "uint16",
                    "width": 2658,
                    "height": 2667,
                    "nodata": None,
                    "band_info": None,
                    "crs_wkt": crs_wkt,
                    "epsg": 32621,
                }
            ),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": f"test-item-{uuid.uuid4().hex[:8]}",
                            "collection": "dem-collection",
                            "title": "Stale item EPSG",
                            "data_asset_href": "https://example.com/data/stale.tif",
                            "bbox": [-1, -1, 1, 1],
                            # Deliberately wrong/stale — the item claims 4326
                            # while the file the probe actually opened is
                            # 32621.
                            "epsg": 4326,
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        dataset_id = data["results"][0]["dataset_id"]

        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200
        body = detail.json()
        assert body["raster"]["epsg"] == 32621
        assert body["srid"] == 32621

    async def test_import_antimeridian_bbox_stores_two_rings(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
        test_db_session,
    ):
        """fix(#884): RFC 7946 §5.2 mandates west > east for a crossing bbox, and
        the old code fed [170, -20, -170, -15] straight into
        POLYGON((w s, e s, e n, w n, w s)). That ring is valid but spans longitude
        -170..170: 1700 deg² on the wrong side of the world instead of the
        intended 100, missing the Fiji data it was supposed to describe while
        matching everything else in the -20..-15 latitude band.

        Every other STAC fixture in this file is low-lon; this is the only
        crossing one.
        """
        from geoalchemy2 import WKTElement

        from app.core.geo import extent_to_bbox

        item_id = f"antimeridian-{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": item_id,
                        "collection": "fiji-collection",
                        "title": "Fiji Seam Crosser",
                        "data_asset_href": (f"https://example.com/data/{item_id}.tif"),
                        # west > east: the spec encoding of a crossing bbox.
                        "bbox": [170, -20, -170, -15],
                        "epsg": 4326,
                        "keywords": [],
                    }
                ],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["created"] == 1
        dataset_id = resp.json()["results"][0]["dataset_id"]

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(r.spatial_extent) AS gtype,"
                    " ST_NumGeometries(r.spatial_extent) AS parts,"
                    " ST_IsValid(r.spatial_extent) AS valid,"
                    " ST_XMin(r.spatial_extent) AS xmin,"
                    " ST_XMax(r.spatial_extent) AS xmax,"
                    " ST_AsText(r.spatial_extent) AS extent_wkt,"
                    " ST_Area(r.spatial_extent) AS area,"
                    " ST_Intersects("
                    "   r.spatial_extent, ST_MakeEnvelope(177, -19, 179, -16, 4326)"
                    " ) AS hits_fiji,"
                    " ST_Intersects("
                    "   r.spatial_extent, ST_MakeEnvelope(-1, -19, 1, -16, 4326)"
                    " ) AS hits_south_atlantic,"
                    " ST_Intersects("
                    "   r.spatial_extent, ST_MakeEnvelope(1.5, 46.5, 2.5, 47.5, 4326)"
                    " ) AS hits_france"
                    " FROM catalog.records r"
                    " JOIN catalog.datasets d ON d.record_id = r.id"
                    " WHERE d.id = :did"
                ).bindparams(did=uuid.UUID(dataset_id))
            )
        ).one()

        # Split at the seam into one part per hemisphere, each planar-valid.
        assert row.gtype == "MULTIPOLYGON"
        assert row.parts == 2
        assert row.valid is True
        # Every vertex stays inside the WGS84 domain.
        assert row.xmin == -180.0
        assert row.xmax == 180.0
        # 10° west of the seam plus 10° east over a 5° band, not the old 1700.
        assert row.area == pytest.approx(100.0)

        # The served bbox is the spec form the item arrived in — a round trip,
        # not a globe-spanning -180..180.
        assert extent_to_bbox(WKTElement(row.extent_wkt, srid=4326)) == [
            170.0,
            -20.0,
            -170.0,
            -15.0,
        ]

        # The two assertions that discriminate old from new: the extent now covers
        # the data it describes, and no longer covers the same latitude band on the
        # far side of the world. (hits_france was False under the old ring too —
        # latitude 47 fell outside the band — so it is only a sanity check.)
        assert row.hits_fiji is True
        assert row.hits_south_atlantic is False
        assert row.hits_france is False

        # fix(#1004): the dataset payload's own extent_bbox is the RFC 7946 §5.2
        # spec form too. It was monotonic under #892, when DatasetMap drew an
        # unguarded planar ring; #903 added the seam guards, and the span form
        # then flattened this extent to the globe-spanning pair that made those
        # guards unreachable.
        detail = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
        assert detail.status_code == 200
        assert detail.json()["extent_bbox"] == [170.0, -20.0, -170.0, -15.0]

    async def test_import_duplicate_skipped(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        """fix(#1286): also the never-refreshed-dataset regression test.

        The first import writes ``origin_uri`` and ``origin_ref.asset_href``
        together and nothing touches the binding afterward, so the second
        import must be caught by the primary origin_ref-keyed branch alone.
        """
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

    async def test_import_catches_an_unbackfilled_dataset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_stac_ssrf,
    ):
        """fix(#1286): a row migration 0036 could not backfill is still caught.

        Neither ``origin_uri`` nor ``origin_ref`` is set — the shape of a row
        that predates #1218 — so the guard can only catch it through the
        ``source_url`` fallback branch.
        """
        from tests.factories import get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        href = f"https://example.com/data/unbackfilled-{uuid.uuid4().hex[:8]}.tif"
        await _create_stac_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=href,
            name="Unbackfilled STAC Row",
        )

        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": f"unbackfilled-test-{uuid.uuid4().hex[:8]}",
                        "title": "Should Be Skipped",
                        "data_asset_href": href,
                        "keywords": [],
                    }
                ],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.json()["skipped"] == 1
        assert resp.json()["results"][0]["status"] == "skipped"

    async def test_import_catches_a_respelled_origin_uri(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_stac_ssrf,
    ):
        """fix(#1286): a respelled origin_uri can no longer open the hole.

        ``origin_ref.asset_href`` names the canonical asset; ``origin_uri``
        is deliberately a different spelling of the same asset (as a
        hypothetical future writer might produce). An origin_uri-keyed guard
        would miss this row; the origin_ref-keyed guard must not.
        """
        from tests.factories import get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        href = f"https://example.com/data/respelled-{uuid.uuid4().hex[:8]}.tif"
        await _create_stac_dataset(
            test_db_session,
            created_by=admin_id,
            source_url=href,
            name="Respelled STAC Pointer",
            # The respelling: origin_uri drifted to a query-string variant of
            # the same asset that origin_ref.asset_href still names exactly.
            origin_uri=f"{href}?rebuilt=true",
            origin_ref={"kind": "stac", "asset_href": href},
        )

        resp = await client.post(
            "/services/stac/import",
            json={
                "url": "https://stac.example.com/v1",
                "items": [
                    {
                        "id": f"respelled-test-{uuid.uuid4().hex[:8]}",
                        "title": "Should Be Skipped",
                        "data_asset_href": href,
                        "keywords": [],
                    }
                ],
                "visibility": "private",
            },
            headers=admin_auth_header,
        )
        assert resp.json()["skipped"] == 1
        assert resp.json()["results"][0]["status"] == "skipped"

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
        from app.platform.security import SSRFError

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
        import json as _json

        import httpx

        from app.modules.catalog.sources.adapters.stac import connect_stac_api

        # fix(#1770 round 41 P1): a real client over a MockTransport, not a
        # fully-mocked one -- `connect_stac_api` now reads via `client.stream`,
        # which an `AsyncMock` cannot fake the async-context-manager protocol
        # of. A content-yielding async generator is what a real transport's
        # response looks like from the client's side (a plain `json=...`
        # response is read at construction, so streaming it raises
        # `StreamConsumed`).
        raw = _json.dumps(STAC_LANDING).encode()

        async def _chunks():
            yield raw

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_chunks())

        real_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=real_client,
        ):
            result = await connect_stac_api("https://stac.example.com/v1")

        assert result is not None
        assert result["id"] == "test-catalog"
        assert result["stac_version"] == "1.0.0"

    async def test_connect_stac_api_not_stac(self):
        import json as _json

        import httpx

        from app.modules.catalog.sources.adapters.stac import connect_stac_api

        raw = _json.dumps({"type": "html", "content": "not stac"}).encode()

        async def _chunks():
            yield raw

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_chunks())

        real_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=real_client,
        ):
            result = await connect_stac_api("https://not-stac.example.com")

        assert result is None

    async def test_connect_stac_api_http_error(self):
        import httpx

        from app.modules.catalog.sources.adapters.stac import connect_stac_api

        def handle(request: httpx.Request) -> httpx.Response:
            raise httpx.TransportError("Connection refused")

        real_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))

        with patch(
            "app.modules.catalog.sources.adapters.stac._make_client",
            return_value=real_client,
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
        assert result["items"][1]["epsg"] == 4326
        assert (
            result["items"][0]["data_asset_href"]
            == "https://example.com/data/item-001.tif"
        )
        assert result["items"][1]["thumbnail_href"] is None


class TestStacImportContactSemantics:
    async def test_any_titiler_failure_stamps_nothing(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_stac_ssrf,
    ):
        """fix(#1271 review): a Titiler non-200 is NOT proof the origin was
        attempted — the extension allowlist rejects some assets before any
        upstream fetch, and the shapes cannot be told apart without parsing
        Titiler's error bodies. Only proven contact (info in hand) stamps;
        the probe settles everything else."""
        with patch(
            "app.modules.catalog.sources.stac_router.fetch_cog_info",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": f"test-item-{uuid.uuid4().hex[:8]}",
                            "collection": "dem-collection",
                            "title": "Upstream-Error STAC Import",
                            "data_asset_href": "https://example.com/data/u.tif",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 4326,
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1

        detail = await client.get(
            f"/datasets/{data['results'][0]['dataset_id']}",
            headers=admin_auth_header,
        )
        assert detail.status_code == 200
        assert detail.json()["last_checked_at"] is None
        assert detail.json()["source_health"] == "unknown"
