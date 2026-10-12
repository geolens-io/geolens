"""The ArcGIS probe bounds its count queries and degrades on malformed service documents."""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from app.modules.catalog.sources import probe as probe_module
from app.modules.catalog.sources.adapters import arcgis
from app.modules.catalog.sources.adapters.arcgis import (
    enrich_arcgis_feature_counts,
    probe_arcgis_service,
)

pytestmark = pytest.mark.asyncio

_BASE = "https://services.example.com/arcgis/rest/services/X/FeatureServer"
_LAYER_PATH = re.compile(r"/FeatureServer/(\d+)/query$")


def _stream(data: object) -> httpx.Response:
    raw = json.dumps(data).encode()

    async def _chunks():
        yield raw

    return httpx.Response(200, content=_chunks())


def _layers(count: int) -> list[dict]:
    return [{"id": i, "name": f"layer_{i}"} for i in range(count)]


def _layer_id(request: httpx.Request) -> int:
    match = _LAYER_PATH.search(request.url.path)
    assert match is not None, request.url
    return int(match.group(1))


async def test_only_the_first_hundred_layers_are_counted() -> None:
    """Layers past the limit keep no count and are never queried."""
    queried: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        queried.append(_layer_id(request))
        return _stream({"count": 7})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        enriched = await enrich_arcgis_feature_counts(_BASE, _layers(150), client)

    assert sorted(queried) == list(range(100))
    assert [layer["feature_count"] for layer in enriched] == [7] * 100 + [None] * 50
    assert [layer["id"] for layer in enriched] == list(range(150))


async def test_stalled_counts_end_at_one_deadline_and_keep_finished_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counts that never answer stop at the shared deadline; finished ones survive."""
    monkeypatch.setattr(arcgis, "_COUNT_ENRICHMENT_DEADLINE", 0.2)

    async def handle(request: httpx.Request) -> httpx.Response:
        if _layer_id(request) < 2:
            return _stream({"count": 3})
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        async with asyncio.timeout(5):
            enriched = await enrich_arcgis_feature_counts(_BASE, _layers(500), client)

    counts = [layer["feature_count"] for layer in enriched]
    assert counts[:2] == [3, 3]
    assert counts[2:] == [None] * 498


async def test_a_non_integer_count_reads_as_unknown() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return _stream({"count": "many"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        [layer] = await enrich_arcgis_feature_counts(_BASE, _layers(1), client)

    assert layer["feature_count"] is None


@pytest.mark.parametrize(
    "document",
    [
        {
            "layers": [
                {"id": 0, "name": "Parcels", "title": 5, "geometryType": ["x"]},
                {"name": "no id"},
                {"id": 2},
                {"id": True, "name": "bool id"},
                {"id": 3, "name": 4},
                "junk",
                None,
            ],
            "tables": [{"id": 9, "name": "Owners", "title": {"x": 1}}, []],
            "objectIdField": ["OBJECTID"],
        },
        {"layers": {"0": "Parcels"}, "tables": "Owners"},
    ],
    ids=["malformed-entries", "malformed-lists"],
)
async def test_a_malformed_service_document_degrades_to_its_usable_layers(
    document: dict,
) -> None:
    """Malformed entries are skipped and the probe answers with what remains."""

    def handle(request: httpx.Request) -> httpx.Response:
        return _stream(document)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await probe_arcgis_service(_BASE, client)

    assert result is not None
    response = probe_module._build_arcgis_response(result, result["layers"], _BASE)
    expected = (
        [("Parcels", None, None), ("Owners", None, None)]
        if document["layers"] != {"0": "Parcels"}
        else []
    )
    assert [
        (layer.name, layer.title, layer.geometry_type) for layer in response.layers
    ] == expected


@pytest.mark.parametrize(
    "envelope", ["denied", {"code": [498], "message": {"m": 1}}, None]
)
async def test_a_malformed_error_envelope_reads_as_not_arcgis(envelope: object) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return _stream({"error": envelope})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await probe_arcgis_service(_BASE, client) is None
