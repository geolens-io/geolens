"""Unit tests for _assert_compatible_record_type on the service-URL preview path.

Pins the IA-P1-02 fix (Phase 1065 plan 03): `reupload_service_preview` now
surfaces vector→raster and any→VRT swaps as HTTP 400 before pipeline execution,
mirroring the multipart and presigned paths.

Requirement: IA-P1-02
Phase: 1065-03
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.catalog.datasets.api.router_reupload import (
    _assert_compatible_record_type,
)


def _ds(record_type: str):
    """Build a minimal stand-in for `Dataset` with a `record` attribute."""
    return SimpleNamespace(record=SimpleNamespace(record_type=record_type))


class TestServiceTypeGuard:
    """Service-URL path (filename=None, service_type provided)."""

    def test_vrt_dataset_rejected_via_service(self):
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(
                _ds("vrt_dataset"), None, service_type="WFS 2.0.0"
            )
        assert exc.value.status_code == 400
        assert "VRT" in exc.value.detail or "vrt" in exc.value.detail.lower()

    def test_raster_dataset_rejected_for_wfs(self):
        """All supported service types are vector — reject for raster_dataset."""
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(
                _ds("raster_dataset"), None, service_type="WFS 2.0.0"
            )
        assert exc.value.status_code == 400
        assert "raster" in exc.value.detail.lower()
        assert "vector" in exc.value.detail.lower()

    def test_raster_dataset_rejected_for_arcgis(self):
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(
                _ds("raster_dataset"), None, service_type="ArcGIS FeatureServer"
            )
        assert exc.value.status_code == 400
        assert "raster" in exc.value.detail.lower()

    def test_raster_dataset_rejected_for_ogc_api(self):
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(
                _ds("raster_dataset"), None, service_type="OGC API - Features"
            )
        assert exc.value.status_code == 400
        assert "raster" in exc.value.detail.lower()

    def test_vector_dataset_accepted_for_wfs(self):
        """Vector-record + vector-service is the happy path — no raise."""
        _assert_compatible_record_type(
            _ds("vector_dataset"), None, service_type="WFS 2.0.0"
        )

    def test_table_accepted_for_arcgis(self):
        """`table` record type accepts vector services (CSV-like uploads)."""
        _assert_compatible_record_type(
            _ds("table"), None, service_type="ArcGIS FeatureServer"
        )


class TestFilePathStillWorks:
    """Make sure the new keyword-only argument doesn't break existing callers
    that pass only (dataset, filename)."""

    def test_vector_accepts_geojson(self):
        _assert_compatible_record_type(_ds("vector_dataset"), "places.geojson")

    def test_vector_rejects_tif(self):
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(_ds("vector_dataset"), "landcover.tif")
        assert exc.value.status_code == 400

    def test_raster_accepts_tif(self):
        _assert_compatible_record_type(_ds("raster_dataset"), "landcover.tif")

    def test_raster_rejects_geojson(self):
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(_ds("raster_dataset"), "places.geojson")
        assert exc.value.status_code == 400

    def test_vrt_rejected_regardless_of_filename(self):
        with pytest.raises(HTTPException) as exc:
            _assert_compatible_record_type(_ds("vrt_dataset"), "anything.tif")
        assert exc.value.status_code == 400
