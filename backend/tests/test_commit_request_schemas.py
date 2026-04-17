"""Unit tests for the CommitRequest subclass split (Phase 220, INGEST-K6-01).

These tests validate the pydantic models in isolation — no database, no
FastAPI, no fixtures. Fast (< 1 second total). They prove:
  - Required-field validation still fires on the subclasses
  - Kitchen-sink bodies are silently coerced into the subclass view
  - Field distribution matches D-04 in CONTEXT.md
"""

import pytest
from pydantic import ValidationError

from app.processing.ingest.schemas import (
    BaseCommitRequest,
    RasterCommitRequest,
    ServiceCommitRequest,
    VectorCommitRequest,
)


class TestVectorCommitRequest:
    def test_valid_minimal(self) -> None:
        """Vector commit with only the required title field succeeds."""
        v = VectorCommitRequest(title="Roads")
        assert v.title == "Roads"
        assert v.x_column is None
        assert v.srid_override is None

    def test_valid_kitchen_sink(self) -> None:
        """Vector commit with every vector-applicable field populated succeeds."""
        v = VectorCommitRequest(
            title="Roads",
            summary="Street centerlines",
            visibility="internal",
            temporal_start="2025-01-01",
            temporal_end="2025-12-31",
            srid_override=4326,
            layer_name="roads_layer",
            x_column="lon",
            y_column="lat",
            geom_column=None,
        )
        assert v.layer_name == "roads_layer"
        assert v.srid_override == 4326

    def test_irrelevant_raster_fields_silently_ignored(self) -> None:
        """Raster-only fields in a vector body are dropped, not error."""
        v = VectorCommitRequest.model_validate(
            {
                "title": "Roads",
                "compression": "LZW",
                "resampling": "bilinear",
                "nodata_override": -9999,
                "x_column": "lon",
            }
        )
        dumped = v.model_dump()
        assert "compression" not in dumped
        assert "resampling" not in dumped
        assert "nodata_override" not in dumped
        assert dumped["x_column"] == "lon"

    def test_irrelevant_service_fields_silently_ignored(self) -> None:
        """Service-only token field is dropped, not error."""
        v = VectorCommitRequest.model_validate({"title": "Roads", "token": "secret"})
        assert "token" not in v.model_dump()

    def test_missing_title_raises(self) -> None:
        """Title is required; missing it raises a clean ValidationError."""
        with pytest.raises(ValidationError) as exc:
            VectorCommitRequest.model_validate({"summary": "no title here"})
        errors = exc.value.errors()
        assert any(
            err["type"] == "missing" and err["loc"] == ("title",) for err in errors
        )

    def test_title_max_length(self) -> None:
        """Title >500 chars raises."""
        with pytest.raises(ValidationError):
            VectorCommitRequest(title="x" * 501)


class TestRasterCommitRequest:
    def test_valid_minimal(self) -> None:
        r = RasterCommitRequest(title="DEM")
        assert r.title == "DEM"
        assert r.compression is None

    def test_valid_with_raster_knobs(self) -> None:
        r = RasterCommitRequest(
            title="DEM",
            srid_override=3857,
            compression="LZW",
            resampling="nearest",
            nodata_override=-9999,
        )
        assert r.compression == "LZW"
        assert r.srid_override == 3857

    def test_vector_fields_silently_ignored(self) -> None:
        r = RasterCommitRequest.model_validate(
            {"title": "DEM", "x_column": "lon", "layer_name": "irrelevant"}
        )
        dumped = r.model_dump()
        assert "x_column" not in dumped
        assert "layer_name" not in dumped

    def test_missing_title_raises(self) -> None:
        with pytest.raises(ValidationError):
            RasterCommitRequest.model_validate({"compression": "LZW"})


class TestServiceCommitRequest:
    def test_valid_minimal(self) -> None:
        s = ServiceCommitRequest(title="ArcGIS Layer")
        assert s.title == "ArcGIS Layer"
        assert s.token is None

    def test_valid_with_token(self) -> None:
        s = ServiceCommitRequest(title="Private WFS", token="bearer-abc")
        assert s.token == "bearer-abc"

    def test_spatial_fields_silently_ignored(self) -> None:
        s = ServiceCommitRequest.model_validate(
            {
                "title": "WFS",
                "compression": "LZW",
                "x_column": "lon",
                "srid_override": 4326,
            }
        )
        dumped = s.model_dump()
        assert "compression" not in dumped
        assert "x_column" not in dumped
        assert "srid_override" not in dumped

    def test_missing_title_raises(self) -> None:
        with pytest.raises(ValidationError):
            ServiceCommitRequest.model_validate({"token": "x"})


class TestFieldDistribution:
    """Lock field distribution to D-04 in CONTEXT.md. If this test breaks,
    the field distribution changed and CONTEXT.md/D-04 must be updated first."""

    def test_base_fields(self) -> None:
        assert set(BaseCommitRequest.model_fields) == {
            "title",
            "summary",
            "visibility",
            "temporal_start",
            "temporal_end",
        }

    def test_vector_fields(self) -> None:
        assert set(VectorCommitRequest.model_fields) == {
            "title",
            "summary",
            "visibility",
            "temporal_start",
            "temporal_end",
            "srid_override",
            "layer_name",
            "x_column",
            "y_column",
            "geom_column",
        }

    def test_raster_fields(self) -> None:
        assert set(RasterCommitRequest.model_fields) == {
            "title",
            "summary",
            "visibility",
            "temporal_start",
            "temporal_end",
            "srid_override",
            "compression",
            "resampling",
            "nodata_override",
        }

    def test_service_fields(self) -> None:
        assert set(ServiceCommitRequest.model_fields) == {
            "title",
            "summary",
            "visibility",
            "temporal_start",
            "temporal_end",
            "token",
        }
