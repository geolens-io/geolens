"""ArcGIS sub-layer types: the probe reports them and the preview refuses
the ones that hold no rows (Group, Raster, Annotation)."""

import json as _json

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.modules.catalog.sources.adapters.arcgis import (
    fetch_arcgis_layer_preview,
    probe_arcgis_service,
)
from app.modules.catalog.sources.probe import _build_arcgis_response

_BASE = "https://example.com/arcgis/rest/services/Water/MapServer"

_ROOT = {
    "currentVersion": 10.91,
    "layers": [
        {
            "id": 0,
            "name": "Detailed",
            "parentLayerId": -1,
            "subLayerIds": [1],
            "type": "Group Layer",
        },
        {
            "id": 1,
            "name": "Hydrants",
            "parentLayerId": 0,
            "subLayerIds": None,
            "type": "Feature Layer",
            "geometryType": "esriGeometryPoint",
        },
        {"id": 2, "name": "Imagery", "parentLayerId": -1, "type": "Raster Layer"},
        {"id": 3, "name": "Labels", "parentLayerId": -1, "type": "Annotation Layer"},
    ],
    "tables": [{"id": 4, "name": "Inspections"}],
}


def _stream(data: dict) -> httpx.Response:
    raw = _json.dumps(data).encode()

    async def _chunks():
        yield raw

    return httpx.Response(200, content=_chunks())


def _client(by_path: dict[str, dict]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        return _stream(by_path.get(request.url.path.rsplit("/", 1)[-1], {}))

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


class TestProbeReportsSubLayerTypes:
    async def test_each_layer_carries_its_type_and_parent(self) -> None:
        async with _client({"MapServer": _ROOT}) as client:
            result = await probe_arcgis_service(_BASE, client)

        assert result is not None
        by_id = {layer["id"]: layer for layer in result["layers"]}
        assert by_id[0]["arcgis_type"] == "Group Layer"
        assert by_id[0]["parent_layer_id"] is None
        assert by_id[1]["arcgis_type"] == "Feature Layer"
        assert by_id[1]["parent_layer_id"] == 0
        assert by_id[2]["arcgis_type"] == "Raster Layer"
        assert by_id[4]["arcgis_type"] == "Table"
        assert by_id[4]["type"] == "table"

    async def test_the_probe_response_marks_unsupported_layers(self) -> None:
        async with _client({"MapServer": _ROOT}) as client:
            result = await probe_arcgis_service(_BASE, client)
        assert result is not None

        response = _build_arcgis_response(result, result["layers"], _BASE)
        importable = {layer.layer_id: layer.importable for layer in response.layers}
        assert importable == {0: False, 1: True, 2: False, 3: False, 4: True}
        hydrants = next(layer for layer in response.layers if layer.layer_id == 1)
        assert hydrants.source_layer_type == "Feature Layer"
        assert hydrants.parent_layer_id == 0


class TestPreviewRefusesLayersWithoutRows:
    @pytest.mark.parametrize(
        "layer_type", ["Group Layer", "Raster Layer", "Annotation Layer"]
    )
    async def test_refuses_with_a_coded_422(self, layer_type: str) -> None:
        meta = {"currentVersion": 10.91, "id": 0, "name": "X", "type": layer_type}
        async with _client({"0": meta}) as client:
            with pytest.raises(HTTPException) as caught:
                await fetch_arcgis_layer_preview(_BASE, 0, client)

        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == "unsupported_layer_type"
        assert caught.value.detail["layer_type"] == layer_type

    async def test_a_feature_layer_still_previews(self) -> None:
        meta = {
            "currentVersion": 10.91,
            "name": "Hydrants",
            "type": "Feature Layer",
            "geometryType": "esriGeometryPoint",
            "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        }
        async with _client({"0": meta, "query": {"features": []}}) as client:
            preview = await fetch_arcgis_layer_preview(_BASE, 0, client)
        assert preview["layer_name"] == "Hydrants"

    async def test_a_server_that_omits_the_type_still_previews(self) -> None:
        meta = {"name": "Old", "geometryType": "esriGeometryPoint", "fields": []}
        async with _client({"0": meta, "query": {"features": []}}) as client:
            preview = await fetch_arcgis_layer_preview(_BASE, 0, client)
        assert preview["layer_name"] == "Old"


class TestPreviewEndpointAnswersTheRefusal:
    async def test_the_route_returns_the_coded_422(
        self, client: httpx.AsyncClient, admin_auth_header: dict
    ) -> None:
        group = {"currentVersion": 10.91, "name": "Detailed", "type": "Group Layer"}
        real = fetch_arcgis_layer_preview

        async def fetch(base, layer_id, http, **kwargs):
            async with _client({"0": group}) as mocked:
                return await real(base, layer_id, mocked, **kwargs)

        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
                side_effect=fetch,
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": _BASE,
                    "service_type": "ArcGIS MapServer",
                    "layer_name": "Detailed",
                    "layer_id": 0,
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "unsupported_layer_type"
