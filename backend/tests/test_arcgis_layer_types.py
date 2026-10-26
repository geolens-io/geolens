"""ArcGIS sub-layer types: the probe reports them and the preview refuses
the ones that hold no rows (Group, Raster, Annotation)."""

import asyncio
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


def _stream_raw(raw: bytes) -> httpx.Response:
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


def _service(layers_handler) -> httpx.AsyncClient:
    """A mock service: the root document and count queries answer normally and
    ``/layers`` is answered by *layers_handler*."""

    def handle(request: httpx.Request) -> httpx.Response:
        tail = request.url.path.rsplit("/", 1)[-1]
        if tail == "layers":
            return layers_handler(request)
        return _stream({"count": 3} if tail == "query" else _ATTACH_ROOT)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


_ATTACH_ROOT = {
    "layers": [
        {"id": 0, "name": "A"},
        {"id": 1, "name": "B", "hasAttachments": True},
        {"id": 2, "name": "C"},
    ],
    "tables": [{"id": 4, "name": "T"}],
}


async def _attachment_flags(layers_handler) -> dict:
    from app.modules.catalog.sources.probe import _enrich_arcgis_layers

    async with _service(layers_handler) as client:
        result = await probe_arcgis_service(_BASE, client)
        assert result is not None
        enriched = await _enrich_arcgis_layers(_BASE, result, client, None)
    response = _build_arcgis_response(result, enriched, _BASE)
    return {layer.layer_id: layer.has_attachments for layer in response.layers}


class TestProbeReportsAttachments:
    async def test_reads_the_flag_from_all_layers_and_tables(self) -> None:
        body = {
            "layers": [
                {"id": 0, "hasAttachments": True},
                {"id": 2, "hasAttachments": False},
                {"id": 99, "hasAttachments": True},
                {"id": 1, "hasAttachments": "yes"},
            ],
            "tables": [{"id": 4, "hasAttachments": True}],
        }
        flags = await _attachment_flags(lambda request: _stream(body))
        # 1 keeps its root value; 99 matches no probed layer.
        assert flags == {0: True, 1: True, 2: False, 4: True}

    async def test_a_root_entry_that_states_it_survives_a_silent_layers_doc(
        self,
    ) -> None:
        flags = await _attachment_flags(lambda request: _stream({"layers": []}))
        assert flags == {0: None, 1: True, 2: None, 4: None}

    @pytest.mark.parametrize(
        "handler",
        [
            lambda request: httpx.Response(500),
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
            lambda request: _stream_raw(b"<html>nope</html>"),
            lambda request: _stream({"error": {"code": 400, "message": "bad"}}),
            lambda request: _stream([{"id": 0, "hasAttachments": True}]),
            lambda request: _stream({"layers": [{"hasAttachments": True}, "x", None]}),
        ],
        ids=[
            "http_error",
            "timeout",
            "non_json",
            "error_envelope",
            "non_dict",
            "malformed",
        ],
    )
    async def test_a_failed_read_keeps_the_root_values(self, handler) -> None:
        flags = await _attachment_flags(handler)
        assert flags == {0: None, 1: True, 2: None, 4: None}

    async def test_a_read_past_the_deadline_is_abandoned(self) -> None:
        from app.modules.catalog.sources.adapters import arcgis_attachments

        class _Slow(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                await asyncio.sleep(5)

        async with httpx.AsyncClient(transport=_Slow()) as client:
            with patch.object(arcgis_attachments, "DEFAULT_CHECK_TIMEOUT", 0.05):
                flags = await arcgis_attachments.fetch_arcgis_attachment_flags(
                    _BASE, client
                )
        assert flags == {}


class TestProbeReportsRelationships:
    async def _relationships(self, body: dict) -> dict:
        from app.modules.catalog.sources.probe import _enrich_arcgis_layers

        async with _service(lambda request: _stream(body)) as client:
            result = await probe_arcgis_service(_BASE, client)
            assert result is not None
            enriched = await _enrich_arcgis_layers(_BASE, result, client, None)
        response = _build_arcgis_response(result, enriched, _BASE)
        return {
            layer.layer_id: [r.model_dump() for r in layer.relationships]
            for layer in response.layers
        }

    async def test_reads_relationship_classes_from_all_layers_and_tables(self) -> None:
        body = {
            "layers": [
                {
                    "id": 0,
                    "relationships": [
                        {
                            "id": 0,
                            "name": "Sites_Visits",
                            "relatedTableId": 4,
                            "cardinality": "esriRelCardinalityOneToMany",
                            "role": "esriRelRoleOrigin",
                        },
                        {"id": 1, "relatedTableId": True},
                        "junk",
                    ],
                },
                {"id": 1, "relationships": "none"},
            ],
            "tables": [
                {
                    "id": 4,
                    "relationships": [
                        {
                            "id": 0,
                            "name": "Sites_Visits",
                            "relatedTableId": 0,
                            "cardinality": "esriRelCardinalityOneToMany",
                            "role": "esriRelRoleDestination",
                        }
                    ],
                }
            ],
        }

        found = await self._relationships(body)

        assert found[0] == [
            {
                "id": 0,
                "name": "Sites_Visits",
                "related_layer_id": 4,
                "cardinality": "OneToMany",
                "role": "Origin",
            }
        ]
        assert found[4][0]["role"] == "Destination"
        assert found[1] == found[2] == []


class TestPreviewRefusesLayersWithoutRows:
    @pytest.mark.parametrize(
        "layer_type",
        [
            "Group Layer",
            "Raster Layer",
            "Annotation Layer",
            "Topology Layer",
            "Utility Network Layer",
        ],
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


class TestReuploadPreviewAnswersTheRefusal:
    async def _preview(self, client, headers, session, meta: dict):
        from app.modules.catalog.datasets.api import router_reupload
        from tests.factories import create_dataset, get_user_id

        admin_id = await get_user_id(session, "admin")
        dataset = await create_dataset(
            session, created_by=admin_id, name="Reupload layer type"
        )
        real = router_reupload.fetch_arcgis_layer_meta

        async def fetch(base, layer_id, http, token=None):
            async with _client({"0": meta}) as mocked:
                return await real(base, layer_id, mocked, token)

        reported = {
            "srid": 4326,
            "geometry_type": "Point",
            "layer_name": "0",
            "feature_count": 1,
            "columns": [],
            "sample_rows": [],
        }
        with (
            patch.object(router_reupload, "validate_url_for_ssrf", AsyncMock()),
            patch.object(router_reupload, "fetch_arcgis_layer_meta", fetch),
            patch.object(
                router_reupload,
                "run_service_preview",
                AsyncMock(return_value=reported),
            ),
        ):
            return await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json={
                    "url": _BASE,
                    "service_type": "ArcGIS MapServer",
                    "layer_name": "0",
                    "layer_id": 0,
                },
                headers=headers,
            )

    @pytest.mark.parametrize(
        "layer_type", ["Group Layer", "Raster Layer", "Annotation Layer"]
    )
    async def test_a_layer_without_rows_gets_the_coded_422(
        self, client, admin_auth_header, test_db_session, layer_type
    ) -> None:
        resp = await self._preview(
            client,
            admin_auth_header,
            test_db_session,
            {"currentVersion": 10.91, "name": "X", "type": layer_type},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "unsupported_layer_type"

    async def test_a_feature_layer_still_previews(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        resp = await self._preview(
            client,
            admin_auth_header,
            test_db_session,
            {"currentVersion": 10.91, "name": "X", "type": "Feature Layer"},
        )
        assert resp.status_code == 200, resp.text


class TestReuploadPreviewGuardsTheMetadataFetch:
    _body = {
        "url": _BASE,
        "service_type": "ArcGIS MapServer",
        "layer_name": "0",
        "layer_id": 0,
    }

    async def _dataset(self, session, owner_id=None):
        from tests.factories import create_dataset, get_user_id

        created_by = owner_id or await get_user_id(session, "admin")
        return await create_dataset(session, created_by=created_by, name="Guarded")

    async def test_a_refused_redirect_is_a_fixed_400_and_skips_the_preview(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        from app.modules.catalog.datasets.api import router_reupload
        from app.platform.security import SSRFResolutionError

        dataset = await self._dataset(test_db_session)
        preview = AsyncMock()
        with (
            patch.object(router_reupload, "validate_url_for_ssrf", AsyncMock()),
            patch.object(
                router_reupload,
                "fetch_arcgis_layer_meta",
                AsyncMock(side_effect=SSRFResolutionError("internal.example.net")),
            ),
            patch.object(router_reupload, "run_service_preview", preview),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json=self._body,
                headers=admin_auth_header,
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "redirect target refused by SSRF policy"
        preview.assert_not_awaited()

    async def test_a_non_owner_never_reaches_the_fetch(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        from app.modules.catalog.datasets.api import router_reupload
        from tests.test_reupload_idor import (
            _create_private_dataset,
            _create_test_user_with_role,
        )

        _, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        other_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(test_db_session, created_by=owner_id)
        fetch = AsyncMock()
        with patch.object(router_reupload, "fetch_arcgis_layer_meta", fetch):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json=self._body,
                headers=other_headers,
            )
        assert resp.status_code in (403, 404)
        fetch.assert_not_awaited()

    async def test_a_refused_url_never_reaches_the_fetch(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        from app.modules.catalog.datasets.api import router_reupload

        dataset = await self._dataset(test_db_session)
        fetch = AsyncMock()
        with patch.object(router_reupload, "fetch_arcgis_layer_meta", fetch):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json={
                    **self._body,
                    "url": "http://127.0.0.1/arcgis/rest/services/W/MapServer",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 400
        fetch.assert_not_awaited()

    async def test_the_request_token_reaches_the_fetch(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        from app.modules.catalog.datasets.api import router_reupload

        dataset = await self._dataset(test_db_session)
        fetch = AsyncMock(return_value={})
        reported = {
            "srid": 4326,
            "geometry_type": "Point",
            "layer_name": "0",
            "feature_count": 1,
            "columns": [],
            "sample_rows": [],
        }
        with (
            patch.object(router_reupload, "validate_url_for_ssrf", AsyncMock()),
            patch.object(router_reupload, "fetch_arcgis_layer_meta", fetch),
            patch.object(
                router_reupload,
                "run_service_preview",
                AsyncMock(return_value=reported),
            ),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json={**self._body, "token": "tok-123"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        assert fetch.await_args.args[3] == "tok-123"


class TestAServerWithAnOddTypeValue:
    @pytest.mark.parametrize("odd", [["Group Layer"], {"name": "Group Layer"}, 7])
    async def test_a_non_string_type_is_treated_as_unknown(self, odd) -> None:
        root = {"layers": [{"id": 0, "name": "X", "type": odd}], "tables": []}
        async with _client(
            {"MapServer": root, "0": {"name": "X", "type": odd}}
        ) as client:
            result = await probe_arcgis_service(_BASE, client)
            assert result is not None
            response = _build_arcgis_response(result, result["layers"], _BASE)
            assert response.layers[0].source_layer_type is None
            assert response.layers[0].importable is True

            preview = await fetch_arcgis_layer_preview(_BASE, 0, client)
        assert preview["layer_name"] == "X"


class TestCompositeLayersAreCaughtByTheirSublayers:
    async def test_an_unlisted_composite_type_is_refused_and_flagged(self) -> None:
        trace = {
            "currentVersion": 11.3,
            "name": "Trace",
            "type": "Trace Network Layer",
            "subLayers": [{"id": 1, "name": "Pipes"}],
        }
        async with _client({"0": trace}) as client:
            with pytest.raises(HTTPException) as caught:
                await fetch_arcgis_layer_preview(_BASE, 0, client)
        assert caught.value.detail["code"] == "unsupported_layer_type"

        root = {
            "layers": [
                {
                    "id": 0,
                    "name": "Trace",
                    "type": "Trace Network Layer",
                    "subLayerIds": [1],
                },
                {"id": 1, "name": "Pipes", "type": "Feature Layer", "parentLayerId": 0},
            ]
        }
        async with _client({"MapServer": root}) as client:
            result = await probe_arcgis_service(_BASE, client)
        assert result is not None
        flags = {layer["id"]: layer["importable"] for layer in result["layers"]}
        assert flags == {0: False, 1: True}
