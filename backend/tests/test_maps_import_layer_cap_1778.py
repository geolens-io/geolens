"""fix(#1778): POST /maps/import needs the layer cap its sibling doors carry.

Codebase audit 2026-08-30 (8dc529f17): `MapStyleImportRequest.layers` was the
one layer-carrying schema in the module with no bound at all. A 5000-layer body
was accepted, and the router then loops `add_layer` per layer, each of which
opens with its own un-memoized dataset-metadata SELECT.

The second consequence outlasts the first: `apply_layer_diff` raises once
`existing - removed + added` passes `_MAX_LAYERS_PER_MAP`, so a map imported
over it could not be saved from the builder at all. Every ordinary edit
answered 400 until the owner bulk-deleted the excess.

Round 1 review: the raw `layers` array is NOT the logical layer count. A GeoLens
export emits companions beside every primary, so `_MAX_LAYERS_PER_MAP` on the
raw array refused valid exports of about 50 polygons upward. The two bounds are
separate now: a resource bound on the document at the schema, and the per-map
limit on the logical layers that survive companion classification.

The summary's warning list was unbounded for its own reason: one warning per
unmatched source, and `sources` carries no count bound of its own.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalog.maps.schemas import (
    _MAX_LAYERS_PER_MAP,
    MapStyleImportRequest,
    MapStyleImportSummary,
    MapStyleImportWarning,
)
from app.modules.catalog.maps.style_json import (
    build_maplibre_style,
    parse_maplibre_style_import,
)

from tests.test_maps_style_json import _layer, _map

# The two bounds this module pins, spelled out rather than imported, so it still
# collects against a build that has neither and the assertions report instead of
# an ImportError. Each is checked against the module it mirrors below.
_MAX_IMPORT_WARNINGS = 100
_MAX_STYLE_DOCUMENT_LAYERS = 4 * _MAX_LAYERS_PER_MAP + 200


def _layer_limit_error() -> type[Exception]:
    from app.modules.catalog.maps.style_import import MapStyleImportLayerLimitError

    return MapStyleImportLayerLimitError


def _layers(count: int) -> list[dict]:
    return [{"id": f"l{i}", "type": "fill", "source": "s"} for i in range(count)]


def _geolens_export(polygon_count: int) -> dict:
    """A real GeoLens export of `polygon_count` labelled polygon layers.

    Every one emits an outline companion and a label companion, so the document
    carries three style layers per logical layer.
    """
    return build_maplibre_style(
        _map(),
        [
            _layer(
                dataset_geometry_type="POLYGON",
                paint={"fill-color": "#94a3b8"},
                label_config={"column": "name"},
                filter=None,
                style_config=None,
            )
            for _ in range(polygon_count)
        ],
    )


class TestRawDocumentBound:
    def test_the_spelled_out_bound_matches_the_module(self) -> None:
        from app.modules.catalog.maps import schemas

        assert schemas._MAX_STYLE_DOCUMENT_LAYERS == _MAX_STYLE_DOCUMENT_LAYERS

    def test_a_document_at_the_raw_bound_is_accepted(self) -> None:
        body = MapStyleImportRequest(
            version=8, sources={}, layers=_layers(_MAX_STYLE_DOCUMENT_LAYERS)
        )

        assert len(body.layers) == _MAX_STYLE_DOCUMENT_LAYERS

    def test_one_style_layer_past_the_raw_bound_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            MapStyleImportRequest(
                version=8, sources={}, layers=_layers(_MAX_STYLE_DOCUMENT_LAYERS + 1)
            )

    def test_a_five_thousand_layer_body_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            MapStyleImportRequest(version=8, sources={}, layers=_layers(5000))

    def test_the_raw_bound_is_derived_from_the_companion_fan_out(self) -> None:
        """One logical layer emits at most four style layers, measured below."""
        assert _MAX_STYLE_DOCUMENT_LAYERS >= 4 * _MAX_LAYERS_PER_MAP

    def test_four_is_the_worst_case_fan_out_for_one_logical_layer(self) -> None:
        """A 3D labelled polygon: primary, outline, extrusion, label."""
        style = build_maplibre_style(
            _map(),
            [
                _layer(
                    dataset_geometry_type="POLYGON",
                    paint={"fill-color": "#94a3b8"},
                    label_config={"column": "name"},
                    filter=None,
                    style_config={
                        "builder": {"extrusion_enabled": True, "height_column": "h"}
                    },
                    is_3d=True,
                )
            ],
        )

        assert len(style["layers"]) == 4


class TestLogicalLayerLimit:
    def test_a_companion_heavy_export_over_the_raw_200_still_imports(self) -> None:
        """The reported case: 101 polygons is 303 style layers and 101 logical
        ones, comfortably inside the per-map limit."""
        style = _geolens_export(101)
        assert len(style["layers"]) > _MAX_LAYERS_PER_MAP

        body = MapStyleImportRequest(**style)
        imported = parse_maplibre_style_import(body.model_dump(exclude_none=True))

        assert imported.summary.layers_imported == 101
        assert len(imported.layers) == 101

    def test_one_logical_layer_past_the_limit_is_refused(self) -> None:
        style = _geolens_export(_MAX_LAYERS_PER_MAP + 1)

        with pytest.raises(_layer_limit_error()) as exc:
            parse_maplibre_style_import(style)

        assert str(_MAX_LAYERS_PER_MAP) in str(exc.value)
        assert str(_MAX_LAYERS_PER_MAP + 1) in str(exc.value)

    def test_the_limit_matches_the_save_path(self) -> None:
        """The import door and the save path must refuse at the same number, or
        a map imported at the higher one cannot be edited afterwards."""
        from app.modules.catalog.maps.schemas import MapUpdate

        sibling = MapUpdate.model_fields["layers"]
        sibling_limits = [getattr(m, "max_length", None) for m in sibling.metadata]

        assert _MAX_LAYERS_PER_MAP in sibling_limits

    def test_the_error_is_a_value_error(self) -> None:
        """The import route's existing broad except ValueError still catches it,
        so a build that has not yet added the 422 arm degrades to a 400."""
        assert issubclass(_layer_limit_error(), ValueError)


class TestWarningCap:
    def test_the_spelled_out_bound_matches_the_module(self) -> None:
        from app.modules.catalog.maps import schemas

        assert schemas._MAX_IMPORT_WARNINGS == _MAX_IMPORT_WARNINGS

    def test_the_reported_list_stops_and_the_rest_are_counted(self) -> None:
        summary = MapStyleImportSummary()

        for index in range(_MAX_IMPORT_WARNINGS + 25):
            summary.add_warning(
                MapStyleImportWarning(code="unsupported_source", message=str(index))
            )

        assert len(summary.warnings) == _MAX_IMPORT_WARNINGS
        assert summary.warnings_truncated == 25

    def test_a_document_full_of_unmatched_sources_stays_bounded(self) -> None:
        style = {
            "version": 8,
            "sources": {f"s{i}": {"type": "vector"} for i in range(500)},
            "layers": [],
        }

        imported = parse_maplibre_style_import(style)

        assert imported.summary.sources_unsupported == 500
        assert len(imported.summary.warnings) == _MAX_IMPORT_WARNINGS
        assert imported.summary.warnings_truncated == 500 - _MAX_IMPORT_WARNINGS

    def test_an_ordinary_import_reports_no_truncation(self) -> None:
        style = {
            "version": 8,
            "sources": {
                "s": {
                    "type": "vector",
                    "metadata": {"geolens": {"dataset_id": str(uuid.uuid4())}},
                }
            },
            "layers": [{"id": "l", "type": "fill", "source": "s"}],
        }

        imported = parse_maplibre_style_import(style)

        assert imported.summary.warnings == []
        assert imported.summary.warnings_truncated == 0


class TestImportRouteStatusCodes:
    """The route's two error arms, pinned in order.

    ``MapStyleImportLayerLimitError`` subclasses ``ValueError``, so an arm added
    below the generic one would never run and the limit would report as a 400.
    The parser is stubbed because reaching the real limit needs 201 accessible
    datasets, which says nothing about the mapping under test.
    """

    async def test_the_layer_limit_answers_422(
        self, client, admin_auth_header: dict, monkeypatch
    ) -> None:
        error_type = _layer_limit_error()

        def _over_limit(_style):
            raise error_type(
                f"Style imports at most {_MAX_LAYERS_PER_MAP} layers per map; "
                f"this document resolves to {_MAX_LAYERS_PER_MAP + 1}"
            )

        monkeypatch.setattr(
            "app.modules.catalog.maps.router.parse_maplibre_style_import",
            _over_limit,
        )

        resp = await client.post(
            "/maps/import",
            json={"version": 8, "sources": {}, "layers": []},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text
        assert str(_MAX_LAYERS_PER_MAP) in resp.json()["detail"]

    async def test_a_malformed_document_still_answers_400(
        self, client, admin_auth_header: dict
    ) -> None:
        resp = await client.post(
            "/maps/import",
            json={"version": 7, "sources": {}, "layers": []},
            headers=admin_auth_header,
        )

        assert resp.status_code == 400, resp.text

    async def test_a_raw_document_over_the_bound_is_refused_at_the_schema(
        self, client, admin_auth_header: dict
    ) -> None:
        resp = await client.post(
            "/maps/import",
            json={
                "version": 8,
                "sources": {},
                "layers": _layers(_MAX_STYLE_DOCUMENT_LAYERS + 1),
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text
