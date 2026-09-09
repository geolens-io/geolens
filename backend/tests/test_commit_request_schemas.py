"""Unit tests for the CommitRequest subclass split (Phase 220, INGEST-K6-01).

These tests validate the pydantic models in isolation — no database, no
FastAPI, no fixtures. Fast (< 1 second total). They prove:
  - Required-field validation still fires on the subclasses
  - Kitchen-sink bodies are silently coerced into the subclass view
  - Field distribution matches D-04 in CONTEXT.md
"""

import inspect
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.processing.ingest.schemas import (
    BaseCommitRequest,
    CommitRequest,
    RasterCommitRequest,
    ServiceCommitRequest,
    VectorCommitRequest,
)
from app.processing.ingest.tasks_common import resolve_service_type


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


# fix(#1961): the four options `check_and_prepare_cog` treats as custom, in the
# spelling a commit body uses for each.
_REWRITING_OPTIONS = {
    "compression": "LZW",
    "resampling": "bilinear",
    "nodata_override": -9999,
    "srid_override": 3857,
}
_CONVERTER_ARGUMENT_TO_FIELD = {
    "compression": "compression",
    "resampling": "resampling",
    "nodata": "nodata_override",
    "assign_crs": "srid_override",
}


class TestStrictCogRefusesOptionsThatForceARewrite:
    """The subclass the handler re-validates a raster job's body against."""

    @pytest.mark.parametrize(
        "field, value",
        [
            *_REWRITING_OPTIONS.items(),
            # The converter compares the string, so a lowercase spelling of
            # the default is a custom option to it and rewrites.
            ("compression", "deflate"),
            ("nodata_override", 0.0),
        ],
    )
    def test_one_rewriting_option_is_refused_by_name(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            RasterCommitRequest(title="DEM", strict_cog=True, **{field: value})
        message = str(exc.value)
        assert "strict_cog" in message
        assert field in message

    def test_every_offending_field_is_named_at_once(self) -> None:
        with pytest.raises(ValidationError) as exc:
            RasterCommitRequest(title="DEM", strict_cog=True, **_REWRITING_OPTIONS)
        message = str(exc.value)
        for field in _REWRITING_OPTIONS:
            assert field in message, field

    def test_the_default_compression_stated_explicitly_is_accepted(self) -> None:
        assert RasterCommitRequest(
            title="DEM", strict_cog=True, compression="DEFLATE"
        ).strict_cog

    def test_strict_alone_is_accepted(self) -> None:
        assert RasterCommitRequest(title="DEM", strict_cog=True).strict_cog

    def test_the_same_options_are_accepted_without_strict(self) -> None:
        assert (
            RasterCommitRequest(title="DEM", **_REWRITING_OPTIONS).strict_cog is False
        )

    @pytest.mark.parametrize(
        "model",
        [CommitRequest, VectorCommitRequest, ServiceCommitRequest],
        ids=lambda model: model.__name__,
    )
    def test_a_body_for_another_subclass_keeps_ignoring_the_flag(
        self, model: type
    ) -> None:
        """The flat wire model and the other subclasses drop what does not
        apply to them, so a kitchen-sink body still commits."""
        accepted = model.model_validate(
            {"title": "Roads", "strict_cog": True, **_REWRITING_OPTIONS}
        )
        assert accepted.title == "Roads"


def test_the_refused_set_is_the_converters_own_predicate() -> None:
    """A fifth argument added to `has_custom_opts` would otherwise pass the
    validator and be converted behind a caller's back."""
    cog = Path(inspect.getfile(CommitRequest)).parents[1] / "raster" / "cog.py"
    predicate = re.search(r"has_custom_opts = \((.*?)\n    \)", cog.read_text(), re.S)
    assert predicate, "check_and_prepare_cog's predicate is no longer readable"
    arguments = set(re.findall(r"^\s*(?:or )?(\w+)", predicate.group(1), re.M))
    assert arguments <= set(_CONVERTER_ARGUMENT_TO_FIELD), arguments
    assert {_CONVERTER_ARGUMENT_TO_FIELD[name] for name in arguments} == set(
        _REWRITING_OPTIONS
    )


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

    def test_the_token_description_states_the_bound_it_declares(self) -> None:
        """Both SDK generators drop `maxLength`, so the bound reaches a caller
        of either one only through the prose."""
        token = CommitRequest.model_json_schema()["properties"]["token"]
        bound = next(b["maxLength"] for b in token["anyOf"] if "maxLength" in b)
        assert f"{bound} characters" in token["description"]

    def test_the_token_description_names_every_service_family_it_reaches(
        self,
    ) -> None:
        """`resolve_service_type` is the accepted set; a family missing from the
        description is one an SDK caller would import anonymously."""
        accepted = re.findall(
            r'startswith\("([^"]+)"\)', inspect.getsource(resolve_service_type)
        )
        assert accepted, "the accepted prefixes are no longer readable there"
        description = CommitRequest.model_json_schema()["properties"]["token"][
            "description"
        ]
        for prefix in accepted:
            assert prefix in description, prefix

    def test_the_union_omits_no_subclass_field(self) -> None:
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
        assert omitted == set()

    def test_the_union_declares_its_fields_in_the_published_order(self) -> None:
        """The generated Python SDK gives each field a positional slot in this
        order, so a field inserted rather than appended moves a caller's
        argument. Same rule as TestAuthIsDeclaredLast in the #1746 suite."""
        assert list(CommitRequest.model_fields) == [
            "title",
            "summary",
            "visibility",
            "srid_override",
            "token",
            "temporal_start",
            "temporal_end",
            "compression",
            "resampling",
            "nodata_override",
            "layer_name",
            "x_column",
            "y_column",
            "geom_column",
            "auth",
            "strict_cog",
        ]
