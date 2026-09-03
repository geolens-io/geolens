"""fix(#1778): POST /maps/import needs the layer cap its sibling doors carry.

Codebase audit 2026-08-30 (8dc529f17): `MapStyleImportRequest.layers` was the
one layer-carrying schema in the module with no `max_length`. Every sibling
writes `max_length=_MAX_LAYERS_PER_MAP`. A 5000-layer body was accepted, and
the router then loops `add_layer` per layer, each of which opens with its own
un-memoized dataset-metadata SELECT.

The second consequence outlasts the first: `apply_layer_diff` raises once
`existing - removed + added` passes the cap, so a map imported over it could
not be saved from the builder at all. Every ordinary edit answered 400 until
the owner bulk-deleted the excess.

The summary's warning list was unbounded for the same reason: one warning per
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
from app.modules.catalog.maps.style_json import parse_maplibre_style_import

# Spelled out rather than imported so this module still collects against a
# build that has no warning bound at all, and the assertions report instead of
# an ImportError.
_MAX_IMPORT_WARNINGS = 100


def _layers(count: int) -> list[dict]:
    return [{"id": f"l{i}", "type": "fill", "source": "s"} for i in range(count)]


class TestLayerCap:
    def test_a_body_at_the_cap_is_accepted(self) -> None:
        body = MapStyleImportRequest(
            version=8, sources={}, layers=_layers(_MAX_LAYERS_PER_MAP)
        )

        assert len(body.layers) == _MAX_LAYERS_PER_MAP

    def test_one_layer_past_the_cap_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            MapStyleImportRequest(
                version=8, sources={}, layers=_layers(_MAX_LAYERS_PER_MAP + 1)
            )

    def test_a_five_thousand_layer_body_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            MapStyleImportRequest(version=8, sources={}, layers=_layers(5000))

    def test_the_cap_matches_the_sibling_doors(self) -> None:
        """The import door and the save path must agree, or a map imported at
        the higher number cannot be edited afterwards."""
        from app.modules.catalog.maps.schemas import MapUpdate

        field = MapStyleImportRequest.model_fields["layers"]
        limits = [getattr(m, "max_length", None) for m in field.metadata]
        sibling = MapUpdate.model_fields["layers"]
        sibling_limits = [getattr(m, "max_length", None) for m in sibling.metadata]

        assert _MAX_LAYERS_PER_MAP in limits
        assert _MAX_LAYERS_PER_MAP in sibling_limits


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
