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
    CommitRequest,
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

    # ING-07 / P2-09: optional strict_cog opt-in. Default False preserves
    # backward compatibility with every existing raster commit call site.
    def test_raster_strict_cog_default_false(self) -> None:
        r = RasterCommitRequest(title="DEM")
        assert r.strict_cog is False

    def test_raster_strict_cog_can_opt_in(self) -> None:
        r = RasterCommitRequest(title="DEM", strict_cog=True)
        assert r.strict_cog is True

    def test_raster_strict_cog_omitted_validates(self) -> None:
        r = RasterCommitRequest.model_validate({"title": "DEM"})
        assert r.strict_cog is False


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
            "strict_cog",
        }

    def test_service_fields(self) -> None:
        assert set(ServiceCommitRequest.model_fields) == {
            "title",
            "summary",
            "visibility",
            "temporal_start",
            "temporal_end",
            "token",
            # feat(#1746 B2b): the structured spelling of the same credential.
            "auth",
        }


def _constraints(field_schema: dict) -> dict:
    """A field's published constraints — everything but its prose and default."""
    return {
        key: value
        for key, value in field_schema.items()
        if key not in ("title", "default", "description")
    }


class TestTheFlatUnionPublishesWhatTheSubclassesEnforce:
    """``CommitRequest`` is the only schema a caller of the commit route reads."""

    @pytest.mark.parametrize(
        "subclass",
        [VectorCommitRequest, RasterCommitRequest, ServiceCommitRequest],
        ids=lambda model: model.__name__,
    )
    def test_a_shared_field_publishes_the_constraint_it_is_judged_by(
        self, subclass: type
    ) -> None:
        flat = CommitRequest.model_json_schema()["properties"]
        for name, published in subclass.model_json_schema()["properties"].items():
            if name not in flat:
                continue
            assert _constraints(flat[name]) == _constraints(published), name

    def test_the_union_omits_only_strict_cog(self) -> None:
        """A subclass field absent from the union cannot be set by a caller:
        the handler re-validates the subclass from this model's dump."""
        omitted = {
            name
            for model in (
                VectorCommitRequest,
                RasterCommitRequest,
                ServiceCommitRequest,
            )
            for name in model.model_fields
            if name not in CommitRequest.model_fields
        }
        assert omitted == {"strict_cog"}
