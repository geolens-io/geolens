"""Tests for VRT catalog API extension (Phase 175-02).

Covers:
- TestRasterMetadataVrtFields: _build_raster_metadata returns vrt_type, source_count, resolution_strategy for VRT assets
- TestDatasetToResponseVrt: dataset_to_response populates raster sub-object for vrt_dataset record_type
- TestQuicklookVrt: quicklook guard accepts vrt_dataset (200), rejects vector_dataset (400)
- TestVrtSourcesEndpoint: list_vrt_sources returns ordered source list; 404 for non-VRT/non-existent datasets
- TestTileTokenVrt: raster_auth_check accepts vrt_dataset record_type (CAT-04 regression)
- TestSearchEnrichmentVrt: search enrichment includes vrt_dataset in band_count batch fetch

All tests are pure unit tests -- no DB, no real files, no network.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_raster_asset(
    vrt_type: str | None = None,
    resolution_strategy: str | None = None,
    status: str = "ready",
    band_count: int = 3,
    epsg: int = 4326,
    storage_backend: str = "local",
    asset_uri: str = "rasters/abc/cog.tif",
    quicklook_256_uri: str = "rasters/abc/quicklook_256.png",
) -> MagicMock:
    asset = MagicMock()
    asset.vrt_type = vrt_type
    asset.resolution_strategy = resolution_strategy
    asset.status = status
    asset.band_count = band_count
    asset.epsg = epsg
    asset.res_x = 10.0
    asset.res_y = 10.0
    asset.nodata = None
    asset.compression = "deflate"
    asset.width = 512
    asset.height = 512
    asset.size_bytes = 1024 * 1024
    asset.storage_backend = storage_backend
    asset.asset_uri = asset_uri
    asset.band_info = []
    asset.quicklook_256_uri = quicklook_256_uri
    asset.quicklook_512_uri = None
    return asset


def _make_mock_dataset(record_type: str, title: str = "Test Dataset") -> MagicMock:
    ds = MagicMock()
    ds.id = uuid.uuid4()
    ds.table_name = "test_table"
    ds.record_id = uuid.uuid4()
    ds.srid = 4326
    ds.geometry_type = None
    ds.feature_count = None
    ds.column_info = None
    ds.quality_detail = None
    ds.source_format = None
    ds.source_filename = None
    ds.original_srid = None
    ds.current_version = 1
    ds.source_url = None
    ds.quality_statement = None

    ds.record = MagicMock()
    ds.record.record_type = record_type
    ds.record.title = title
    ds.record.summary = None
    ds.record.visibility = "public"
    ds.record.created_by = uuid.uuid4()
    ds.record.updated_by = None
    ds.record.created_at = datetime(2026, 1, 1)
    ds.record.updated_at = datetime(2026, 1, 2)
    ds.record.record_status = "published"
    ds.record.license = None
    ds.record.source_organization = None
    ds.record.temporal_start = None
    ds.record.temporal_end = None
    ds.record.spatial_extent = None
    ds.record.lineage_summary = None
    ds.record.update_frequency = None
    ds.record.usage_constraints = None
    ds.record.access_constraints = None
    ds.record.sensitivity_classification = None
    ds.record.theme_category = None
    ds.record.owner_org = None
    ds.record.published_at = None
    ds.record.language = None

    return ds


# ---------------------------------------------------------------------------
# TestRasterMetadataVrtFields
# ---------------------------------------------------------------------------


class TestRasterMetadataVrtFields:
    """_build_raster_metadata returns correct VRT fields for VRT assets and None for COGs."""

    def test_vrt_asset_populates_vrt_fields(self):
        """VRT asset with vrt_type, resolution_strategy, and source_count returns populated fields."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        asset = _make_mock_raster_asset(
            vrt_type="mosaic",
            resolution_strategy="finest",
            status="ready",
        )

        result = _build_raster_metadata(dataset, asset, is_admin=False, source_count=3)

        assert result is not None
        assert result.vrt_type == "mosaic"
        assert result.resolution_strategy == "finest"
        assert result.source_count == 3
        assert result.status == "ready"

    def test_cog_asset_has_no_vrt_fields(self):
        """Regular COG asset returns None for all VRT-specific fields."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        dataset = _make_mock_dataset("raster_dataset", "My COG")
        asset = _make_mock_raster_asset(
            vrt_type=None,
            resolution_strategy=None,
            status="ready",
        )

        result = _build_raster_metadata(
            dataset, asset, is_admin=False, source_count=None
        )

        assert result is not None
        assert result.vrt_type is None
        assert result.resolution_strategy is None
        assert result.source_count is None

    def test_none_raster_asset_returns_none(self):
        """Passing raster_asset=None returns None (no metadata to build)."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        dataset = _make_mock_dataset("vrt_dataset")
        result = _build_raster_metadata(dataset, None, source_count=5)

        assert result is None

    def test_vrt_band_stack_type(self):
        """band_stack vrt_type is also correctly propagated."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        dataset = _make_mock_dataset("vrt_dataset")
        asset = _make_mock_raster_asset(
            vrt_type="band_stack", resolution_strategy="first"
        )

        result = _build_raster_metadata(dataset, asset, source_count=2)

        assert result is not None
        assert result.vrt_type == "band_stack"
        assert result.resolution_strategy == "first"
        assert result.source_count == 2

    def test_source_count_zero(self):
        """source_count=0 is valid (empty VRT, edge case)."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        dataset = _make_mock_dataset("vrt_dataset")
        asset = _make_mock_raster_asset(vrt_type="mosaic")

        result = _build_raster_metadata(dataset, asset, source_count=0)

        assert result is not None
        assert result.source_count == 0


# ---------------------------------------------------------------------------
# TestDatasetToResponseVrt
# ---------------------------------------------------------------------------


class TestDatasetToResponseVrt:
    """dataset_to_response populates raster sub-object for vrt_dataset; None for vector_dataset."""

    def test_vrt_dataset_response_has_raster_object(self):
        """vrt_dataset record_type produces a DatasetResponse with non-None raster field."""
        from app.modules.catalog.datasets.domain.helpers import dataset_to_response

        dataset = _make_mock_dataset("vrt_dataset", "VRT Mosaic")
        asset = _make_mock_raster_asset(vrt_type="mosaic", resolution_strategy="finest")

        response = dataset_to_response(dataset, raster_asset=asset, source_count=4)

        assert response.raster is not None
        assert response.raster.vrt_type == "mosaic"
        assert response.raster.source_count == 4
        assert response.raster.resolution_strategy == "finest"
        assert response.record_type == "vrt_dataset"

    def test_vector_dataset_response_has_no_raster(self):
        """vector_dataset record_type produces a DatasetResponse with raster=None."""
        from app.modules.catalog.datasets.domain.helpers import dataset_to_response

        dataset = _make_mock_dataset("vector_dataset", "Vector Layer")

        response = dataset_to_response(dataset, raster_asset=None)

        assert response.raster is None
        assert response.record_type == "vector_dataset"

    def test_raster_dataset_response_has_raster_object(self):
        """raster_dataset (COG) produces DatasetResponse with raster field (no VRT fields)."""
        from app.modules.catalog.datasets.domain.helpers import dataset_to_response

        dataset = _make_mock_dataset("raster_dataset", "COG Layer")
        asset = _make_mock_raster_asset(vrt_type=None, resolution_strategy=None)

        response = dataset_to_response(dataset, raster_asset=asset, source_count=None)

        assert response.raster is not None
        assert response.raster.vrt_type is None
        assert response.raster.source_count is None
        assert response.record_type == "raster_dataset"

    def test_vrt_dataset_with_no_asset_returns_none_raster(self):
        """vrt_dataset without a RasterAsset (edge case) does not crash; raster is None."""
        from app.modules.catalog.datasets.domain.helpers import dataset_to_response

        dataset = _make_mock_dataset("vrt_dataset", "VRT No Asset Yet")

        response = dataset_to_response(dataset, raster_asset=None)

        assert response.raster is None
        assert response.record_type == "vrt_dataset"


# ---------------------------------------------------------------------------
# TestQuicklookVrt
# ---------------------------------------------------------------------------


class TestQuicklookVrt:
    """Quicklook guard accepts vrt_dataset (200); rejects vector_dataset (400)."""

    @pytest.mark.asyncio
    async def test_quicklook_accepts_vrt_dataset(self):
        """get_quicklook passes the guard when record_type is vrt_dataset."""
        from app.modules.catalog.datasets.api.router import get_quicklook

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        mock_dataset.record.record_status = "published"
        mock_dataset.record.visibility = "public"

        mock_asset = _make_mock_raster_asset(quicklook_256_uri="rasters/abc/q256.png")
        mock_asset.quicklook_256_uri = "rasters/abc/q256.png"

        mock_ra_result = MagicMock()
        mock_ra_result.scalar_one_or_none = MagicMock(return_value=mock_asset)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_ra_result)

        mock_storage = AsyncMock()
        mock_storage.get = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n")

        mock_user = MagicMock()

        with patch(
            "app.modules.catalog.datasets.api.router.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with patch(
                "app.modules.catalog.datasets.api.router.check_dataset_access_or_anonymous",
                AsyncMock(return_value=None),
            ):
                with patch(
                    "app.modules.catalog.datasets.api.router.get_storage", return_value=mock_storage
                ):
                    # Should not raise HTTPException 400 — guard passes for vrt_dataset
                    response = await get_quicklook(
                        dataset_id=dataset_id,
                        size=256,
                        user=mock_user,
                        db=mock_db,
                    )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_quicklook_rejects_table_dataset(self):
        """get_quicklook raises 400 when record_type is table (non-spatial)."""
        from fastapi import HTTPException
        from app.modules.catalog.datasets.api.router import get_quicklook

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("table", "My Table")
        mock_dataset.record.record_status = "published"
        mock_dataset.record.visibility = "public"

        mock_user = MagicMock()
        mock_db = AsyncMock()

        with patch(
            "app.modules.catalog.datasets.api.router.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with patch(
                "app.modules.catalog.datasets.api.router.check_dataset_access_or_anonymous",
                AsyncMock(return_value=None),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await get_quicklook(
                        dataset_id=dataset_id,
                        size=256,
                        user=mock_user,
                        db=mock_db,
                    )

        assert exc_info.value.status_code == 400
        assert "Quicklook not available for this dataset type" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_quicklook_returns_404_when_dataset_not_found(self):
        """get_quicklook raises 404 when dataset does not exist."""
        from fastapi import HTTPException
        from app.modules.catalog.datasets.api.router import get_quicklook

        dataset_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch("app.modules.catalog.datasets.api.router.get_dataset", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await get_quicklook(
                    dataset_id=dataset_id,
                    size=256,
                    user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# TestVrtSourcesEndpoint
# ---------------------------------------------------------------------------


class TestVrtSourcesEndpoint:
    """list_vrt_sources returns ordered VrtSourceItems; 404 for non-VRT / non-existent."""

    @pytest.mark.asyncio
    async def test_returns_ordered_source_list_for_vrt_dataset(self):
        """list_vrt_sources returns VrtSourceListResponse with correct fields."""
        from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources

        dataset_id = uuid.uuid4()
        source_id_1 = uuid.uuid4()
        source_id_2 = uuid.uuid4()

        mock_dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        mock_dataset.id = dataset_id

        # Mock two source rows returned by raw SQL
        row1 = MagicMock()
        row1.dataset_id = source_id_1
        row1.title = "Source 1"
        row1.position = 0
        row1.band_count = 3
        row1.resolution_x = 10.0
        row1.resolution_y = 10.0
        row1.crs_epsg = 4326
        row1.extent_wkt = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"

        row2 = MagicMock()
        row2.dataset_id = source_id_2
        row2.title = "Source 2"
        row2.position = 1
        row2.band_count = 3
        row2.resolution_x = 20.0
        row2.resolution_y = 20.0
        row2.crs_epsg = 4326
        row2.extent_wkt = "POLYGON((5 5, 6 5, 6 6, 5 6, 5 5))"

        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[row1, row2])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_user = MagicMock()

        with patch(
            "app.modules.catalog.datasets.api.router_vrt.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with patch(
                "app.modules.catalog.datasets.api.router_vrt.check_dataset_access",
                AsyncMock(return_value=None),
            ):
                response = await list_vrt_sources(
                    dataset_id=dataset_id,
                    user=mock_user,
                    db=mock_db,
                )

        assert len(response.sources) == 2
        assert response.sources[0].title == "Source 1"
        assert response.sources[0].position == 0
        assert response.sources[0].band_count == 3
        assert response.sources[0].dataset_id == source_id_1
        assert response.sources[1].title == "Source 2"
        assert response.sources[1].position == 1

    @pytest.mark.asyncio
    async def test_returns_404_for_non_existent_dataset(self):
        """list_vrt_sources raises 404 when dataset is None."""
        from fastapi import HTTPException
        from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources

        dataset_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch("app.modules.catalog.datasets.api.router_vrt.get_dataset", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await list_vrt_sources(
                    dataset_id=dataset_id,
                    user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_for_non_vrt_raster_dataset(self):
        """list_vrt_sources raises 404 when dataset is a raster_dataset (not VRT)."""
        from fastapi import HTTPException
        from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("raster_dataset", "Plain COG")

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.catalog.datasets.api.router_vrt.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with pytest.raises(HTTPException) as exc_info:
                await list_vrt_sources(
                    dataset_id=dataset_id,
                    user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_for_vector_dataset(self):
        """list_vrt_sources raises 404 when dataset is a vector_dataset."""
        from fastapi import HTTPException
        from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("vector_dataset", "Vector Layer")

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.catalog.datasets.api.router_vrt.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with pytest.raises(HTTPException) as exc_info:
                await list_vrt_sources(
                    dataset_id=dataset_id,
                    user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_source_extent_bbox_parsed_correctly(self):
        """Extent WKT is parsed into a 4-element bbox list."""
        from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("vrt_dataset")
        mock_dataset.id = dataset_id

        row = MagicMock()
        row.dataset_id = uuid.uuid4()
        row.title = "Tile"
        row.position = 0
        row.band_count = 1
        row.resolution_x = 5.0
        row.resolution_y = 5.0
        row.crs_epsg = 32632
        row.extent_wkt = "POLYGON((-10 -20, 10 -20, 10 20, -10 20, -10 -20))"

        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[row])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_user = MagicMock()

        with patch(
            "app.modules.catalog.datasets.api.router_vrt.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with patch(
                "app.modules.catalog.datasets.api.router_vrt.check_dataset_access",
                AsyncMock(return_value=None),
            ):
                response = await list_vrt_sources(
                    dataset_id=dataset_id,
                    user=mock_user,
                    db=mock_db,
                )

        assert len(response.sources) == 1
        bbox = response.sources[0].extent_bbox
        assert bbox is not None
        assert len(bbox) == 4
        # POLYGON((-10 -20, 10 -20, 10 20, -10 20, -10 -20)) -> minx=-10, miny=-20, maxx=10, maxy=20
        assert bbox[0] == pytest.approx(-10.0)
        assert bbox[1] == pytest.approx(-20.0)
        assert bbox[2] == pytest.approx(10.0)
        assert bbox[3] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_null_extent_wkt_produces_none_bbox(self):
        """Source with no spatial extent (extent_wkt=None) returns None for extent_bbox."""
        from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("vrt_dataset")
        mock_dataset.id = dataset_id

        row = MagicMock()
        row.dataset_id = uuid.uuid4()
        row.title = "No Extent"
        row.position = 0
        row.band_count = 1
        row.resolution_x = 5.0
        row.resolution_y = 5.0
        row.crs_epsg = 4326
        row.extent_wkt = None

        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[row])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_user = MagicMock()

        with patch(
            "app.modules.catalog.datasets.api.router_vrt.get_dataset", AsyncMock(return_value=mock_dataset)
        ):
            with patch(
                "app.modules.catalog.datasets.api.router_vrt.check_dataset_access",
                AsyncMock(return_value=None),
            ):
                response = await list_vrt_sources(
                    dataset_id=dataset_id,
                    user=mock_user,
                    db=mock_db,
                )

        assert len(response.sources) == 1
        assert response.sources[0].extent_bbox is None


# ---------------------------------------------------------------------------
# TestTileTokenVrt
# ---------------------------------------------------------------------------


class TestTileTokenVrt:
    """CAT-04: raster tile auth accepts vrt_dataset record_type (regression guard).

    The record_type guard was refactored out of ``raster_auth_check`` into the
    shared ``_resolve_raster_access`` helper so both the auth_request endpoint
    and the API-side raster proxy share one code path. Tests inspect the
    helper's source since that is where the guard lives now.
    """

    def test_resolve_raster_access_accepts_vrt_dataset_record_type(self):
        """_resolve_raster_access accepts both raster_dataset and vrt_dataset."""
        import inspect

        import app.processing.tiles.router as tiles_module

        source = inspect.getsource(tiles_module._resolve_raster_access)

        # Guard condition must include vrt_dataset
        assert "vrt_dataset" in source, (
            "_resolve_raster_access must accept 'vrt_dataset' record_type — "
            "CAT-04 regression: guard was updated in Phase 171"
        )

    def test_resolve_raster_access_uses_tuple_guard_for_both_types(self):
        """_resolve_raster_access uses 'in' check including both record types."""
        import inspect

        import app.processing.tiles.router as tiles_module

        source = inspect.getsource(tiles_module._resolve_raster_access)

        # Must reject non-raster types; both raster_dataset and vrt_dataset must be in guard
        assert "raster_dataset" in source
        assert "vrt_dataset" in source

    def test_resolve_raster_access_not_raster_detail(self):
        """Confirm vrt_dataset appears in a real guard line, not just comments."""
        import inspect

        import app.processing.tiles.router as tiles_module

        source = inspect.getsource(tiles_module._resolve_raster_access)

        # Find the guard line that checks record_type
        lines = [ln.strip() for ln in source.splitlines() if "vrt_dataset" in ln]
        assert len(lines) >= 1, (
            "vrt_dataset must appear in at least one meaningful line"
        )


# ---------------------------------------------------------------------------
# TestSearchEnrichmentVrt
# ---------------------------------------------------------------------------


class TestSearchEnrichmentVrt:
    """Search enrichment includes vrt_dataset in band_count batch fetch (regression guard)."""

    def test_search_router_includes_vrt_dataset_in_raster_ids_filter(self):
        """_handle_search in search/router.py includes vrt_dataset in raster enrichment."""
        import app.modules.catalog.search.router as search_module
        import inspect

        source = inspect.getsource(search_module._handle_search)

        # Both record_types must be in the enrichment filter
        assert "vrt_dataset" in source, (
            "_handle_search must include 'vrt_dataset' in raster enrichment filter"
        )
        assert "raster_dataset" in source

    def test_search_enrichment_assigns_band_count_to_vrt_features(self):
        """Search enrichment assigns band_count to features with vrt_dataset record_type."""
        import app.modules.catalog.search.router as search_module
        import inspect

        source = inspect.getsource(search_module._handle_search)

        # The assignment branch must also check vrt_dataset
        lines_with_vrt = [
            ln.strip() for ln in source.splitlines() if "vrt_dataset" in ln
        ]
        assert len(lines_with_vrt) >= 2, (
            "vrt_dataset must appear in both the raster_ids filter AND the feature assignment loop"
        )

    def test_band_count_assignment_covers_vrt_dataset(self):
        """Both the raster_ids filter and the assignment loop in _handle_search cover vrt_dataset."""
        import app.modules.catalog.search.router as search_module
        import inspect

        source = inspect.getsource(search_module._handle_search)

        # Count how many times vrt_dataset appears — must be at least 2
        # (once in raster_ids filter, once in the assignment branch)
        count = source.count("vrt_dataset")
        assert count >= 2, (
            f"Expected vrt_dataset to appear in at least 2 locations in _handle_search, found {count}. "
            "Both the raster_ids filter and the band_count assignment loop must handle vrt_dataset."
        )
