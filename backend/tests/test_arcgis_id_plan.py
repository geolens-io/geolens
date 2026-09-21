"""Bounded ArcGIS object-ID planning and deterministic GDAL fetch tests."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.modules.catalog.sources.adapters.arcgis import (
    ARCGIS_ID_PLAN_MAX_IDS,
    ArcGISIDPlanError,
    build_arcgis_id_query_url,
    fetch_arcgis_id_plan,
)
from app.modules.catalog.sources.preview import build_gdal_source


class _JSONStream(httpx.AsyncByteStream):
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    async def __aiter__(self):
        yield self._body


def _client(payload: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, stream=_JSONStream(payload), request=request
            )
        )
    )


@pytest.mark.anyio
async def test_id_plan_is_sorted_digestible_and_preserves_64_bit_sparse_ids() -> None:
    payload = {
        "objectIdFieldName": "OBJECTID",
        "objectIds": [9_223_372_036_854_775_807, 3, 0, 991],
        "editMoment": 1_725_000_000_000,
    }
    async with _client(payload) as client:
        plan = await fetch_arcgis_id_plan(
            "https://services.example.com/FeatureServer", 7, client
        )

    assert plan.oid_field == "OBJECTID"
    assert plan.ids == (0, 3, 991, 9_223_372_036_854_775_807)
    assert plan.count == 4
    assert len(plan.digest) == 64
    assert plan.source_marker == 1_725_000_000_000


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload, message",
    [
        ({"objectIdFieldName": "OBJECTID", "objectIds": [1, 1]}, "duplicate"),
        ({"objectIdFieldName": "OBJECTID", "objectIds": [None]}, "non-integer"),
        ({"objectIdFieldName": "OBJECTID", "objectIds": [True]}, "non-integer"),
        ({"objectIdFieldName": "OBJECTID", "objectIds": [-1]}, "invalid integer"),
        (
            {"objectIdFieldName": "OBJECTID", "objectIds": [1 << 63]},
            "invalid integer",
        ),
        ({"objectIdFieldName": "OBJECTID", "objectIds": ["7"]}, "non-integer"),
        (
            {
                "objectIdFieldName": "OBJECTID",
                "objectIds": [1],
                "exceededTransferLimit": True,
            },
            "truncated",
        ),
        ({"objectIdFieldName": "OBJECTID"}, "omitted objectIds"),
        ({"objectIds": [1]}, "omitted its OID field"),
    ],
)
async def test_id_plan_rejects_invalid_or_ambiguous_source_responses(
    payload: dict, message: str
) -> None:
    async with _client(payload) as client:
        with pytest.raises(ArcGISIDPlanError, match=message):
            await fetch_arcgis_id_plan(
                "https://services.example.com/FeatureServer", 7, client
            )


@pytest.mark.anyio
async def test_id_plan_rejects_cardinality_bound_and_oid_field_change() -> None:
    oversized = {
        "objectIdFieldName": "OBJECTID",
        "objectIds": list(range(ARCGIS_ID_PLAN_MAX_IDS + 1)),
    }
    async with _client(oversized) as client:
        with pytest.raises(ArcGISIDPlanError, match="plan limit"):
            await fetch_arcgis_id_plan(
                "https://services.example.com/FeatureServer", 7, client
            )

    async with _client({"objectIdFieldName": "new_oid", "objectIds": [1]}) as client:
        with pytest.raises(ArcGISIDPlanError, match="field changed"):
            await fetch_arcgis_id_plan(
                "https://services.example.com/FeatureServer",
                7,
                client,
                expected_oid_field="OBJECTID",
            )


def test_id_plan_query_and_gdal_fetch_use_exact_ids_without_offset_paging() -> None:
    plan_url = build_arcgis_id_query_url(
        "https://services.example.com/FeatureServer/7?ignored=x"
    )
    assert parse_qs(urlparse(plan_url).query) == {
        "where": ["1=1"],
        "returnIdsOnly": ["true"],
        "returnGeometry": ["false"],
        "f": ["json"],
    }

    source, layer = build_gdal_source(
        "ArcGIS:FeatureServer",
        "https://services.example.com/FeatureServer",
        "roads",
        7,
        object_ids=(3, 991, 9_223_372_036_854_775_807),
        order_field=None,
    )
    assert layer == ""
    query = parse_qs(urlparse(source.removeprefix("GeoJSON:")).query)
    assert source.startswith("GeoJSON:")
    assert query["objectIds"] == ["3,991,9223372036854775807"]
    assert query["f"] == ["geojson"]
    assert "resultOffset" not in query
    assert "resultRecordCount" not in query

    regular_source, _ = build_gdal_source(
        "ArcGIS:FeatureServer",
        "https://services.example.com/FeatureServer",
        "roads",
        7,
        object_ids=(3, 991),
    )
    assert regular_source.startswith("ESRIJSON:")
    regular_query = parse_qs(urlparse(regular_source.removeprefix("ESRIJSON:")).query)
    assert regular_query["f"] == ["json"]


@pytest.mark.parametrize(
    "ids",
    [(), tuple(range(1_001)), (True,), ("1",), (-1,)],
)
def test_gdal_exact_id_fetch_rejects_invalid_or_unbounded_chunks(
    ids: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError):
        build_gdal_source(
            "ArcGIS:FeatureServer",
            "https://services.example.com/FeatureServer",
            "roads",
            7,
            object_ids=ids,  # type: ignore[arg-type]
        )
