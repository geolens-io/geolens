"""Tests for ArcGIS auth fixes: no Bearer header, JSON error detection, objectIdField."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.modules.catalog.sources.adapters.arcgis import (
    ArcGISTokenError,
    enrich_arcgis_feature_counts,
    fetch_arcgis_pagination_info,
    probe_arcgis_service,
)
from app.modules.catalog.sources.preview import build_gdal_source


def _make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response with the given JSON data."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.request = MagicMock(spec=httpx.Request)
    return resp


def _streaming_json_response(data: dict) -> httpx.Response:
    """A response whose body supports the streaming read `probe_arcgis_
    service` now uses (fix(#1770 round 41 P1)).

    `httpx.Response(200, json=...)` materialises the body at construction, so
    `client.stream(...)`'s `aiter_raw()` over one raises `StreamConsumed` --
    a real transport never hands back a pre-read response. A content-yielding
    async generator is what a real transport's response looks like from the
    client's side.
    """
    import json as _json

    raw = _json.dumps(data).encode()

    async def _chunks():
        yield raw

    return httpx.Response(200, content=_chunks())


def _mock_transport_client(handle) -> httpx.AsyncClient:
    """A real client over a MockTransport, for the functions that now read
    via `client.stream` rather than `client.get` -- `AsyncMock(spec=...)`
    cannot fake the async-context-manager protocol `.stream()` returns.
    """
    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.mark.asyncio
async def test_arcgis_probe_no_bearer_header():
    """Verify the ArcGIS probe sends token only as query param, not as Authorization header."""
    recorded: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return _streaming_json_response(
            {"layers": [{"id": 0, "name": "test", "geometryType": "esriGeometryPoint"}]}
        )

    async with _mock_transport_client(handle) as client:
        await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer", client, token="mytoken"
        )

    # The URL should include the token as a query parameter
    assert len(recorded) == 1
    assert "token=mytoken" in str(recorded[0].url)

    # No Authorization header should have been sent
    assert "Authorization" not in recorded[0].headers


@pytest.mark.asyncio
async def test_arcgis_probe_encodes_url_reserved_characters_in_token():
    """fix(#1746 codex r7): a token with URL-reserved characters must be encoded.

    probe_arcgis_service() concatenates the token into the query string by
    hand (unlike the sibling call sites that pass it through httpx's
    ``params=``, which encodes automatically). The token validators only
    reject whitespace/control characters, so ``'``, ``#``, and ``&`` all
    pass through and were kept literal here -- a raw ``#`` truncates the
    URL at a fragment boundary and a raw ``&`` starts a bogus new query
    parameter, either of which leaks the tail of the token into the actual
    request AND lets it escape the log redactor's URL match.
    """
    recorded: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return _streaming_json_response({"layers": []})

    async with _mock_transport_client(handle) as client:
        await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer",
            client,
            token="AA'#&ULTRASECRET",
        )

    url_called = str(recorded[0].url)
    assert "token=AA%27%23%26ULTRASECRET" in url_called
    assert "'" not in url_called
    assert "#" not in url_called
    assert "&ULTRA" not in url_called


@pytest.mark.asyncio
async def test_enrich_arcgis_feature_counts_encodes_url_reserved_characters_in_token():
    """fix(#1746 codex r7): the second raw string-concatenation site.

    Same issue and same fix as the probe above, in
    ``enrich_arcgis_feature_counts()``'s per-layer count query.
    """
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = _make_mock_response({"count": 5})
    mock_client.get.return_value = mock_response

    await enrich_arcgis_feature_counts(
        "https://services.arcgis.com/svc/FeatureServer",
        [{"id": 0, "name": "layer0"}],
        mock_client,
        token="AA'#&ULTRASECRET",
    )

    url_called = mock_client.get.call_args[0][0]
    assert "token=AA%27%23%26ULTRASECRET" in url_called
    assert "'" not in url_called
    assert "#" not in url_called
    assert "&ULTRA" not in url_called


@pytest.mark.asyncio
async def test_arcgis_error_498_raises():
    """ArcGIS JSON error with code 498 (invalid token) should raise ArcGISTokenError."""

    def handle(request: httpx.Request) -> httpx.Response:
        return _streaming_json_response(
            {"error": {"code": 498, "message": "Invalid token."}}
        )

    with pytest.raises(ArcGISTokenError, match="498"):
        async with _mock_transport_client(handle) as client:
            await probe_arcgis_service(
                "https://services.arcgis.com/svc/FeatureServer",
                client,
                token="badtoken",
            )


@pytest.mark.asyncio
async def test_arcgis_error_499_raises():
    """ArcGIS JSON error with code 499 (token required) should raise ArcGISTokenError."""

    def handle(request: httpx.Request) -> httpx.Response:
        return _streaming_json_response(
            {"error": {"code": 499, "message": "Token required."}}
        )

    with pytest.raises(ArcGISTokenError, match="499"):
        async with _mock_transport_client(handle) as client:
            await probe_arcgis_service(
                "https://services.arcgis.com/svc/FeatureServer", client
            )


@pytest.mark.asyncio
async def test_arcgis_object_id_field_extraction():
    """objectIdField should be read from layer metadata, falling back to service level then OBJECTID."""

    def handle(request: httpx.Request) -> httpx.Response:
        # Layer-level objectIdField takes priority
        return _streaming_json_response(
            {
                "objectIdField": "SERVICE_OID",
                "layers": [
                    {
                        "id": 0,
                        "name": "layer_with_oid",
                        "geometryType": "esriGeometryPoint",
                        "objectIdField": "FID",
                    },
                    {
                        "id": 1,
                        "name": "layer_without_oid",
                        "geometryType": "esriGeometryPolygon",
                    },
                ],
            }
        )

    async with _mock_transport_client(handle) as client:
        result = await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer", client
        )
    assert result is not None
    layers = result["layers"]

    # Layer 0 has its own objectIdField
    assert layers[0]["object_id_field"] == "FID"
    # Layer 1 falls back to service-level objectIdField
    assert layers[1]["object_id_field"] == "SERVICE_OID"


@pytest.mark.asyncio
async def test_arcgis_object_id_field_default():
    """When no objectIdField in metadata, default to OBJECTID."""

    def handle(request: httpx.Request) -> httpx.Response:
        return _streaming_json_response(
            {
                "layers": [
                    {"id": 0, "name": "no_oid", "geometryType": "esriGeometryPoint"}
                ]
            }
        )

    async with _mock_transport_client(handle) as client:
        result = await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer", client
        )
    assert result is not None
    assert result["layers"][0]["object_id_field"] == "OBJECTID"


def test_build_gdal_source_custom_oid():
    """build_gdal_source should use the custom OID field in orderByFields."""
    source, layer_name = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.arcgis.com/svc/FeatureServer",
        "my_layer",
        layer_id=0,
        order_field="FID",
    )
    assert "orderByFields=FID+ASC" in source
    assert "orderByFields=OBJECTID" not in source


def test_build_gdal_source_default_oid():
    """build_gdal_source defaults to OBJECTID when order_field not specified."""
    source, _ = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.arcgis.com/svc/FeatureServer",
        "my_layer",
        layer_id=0,
    )
    assert "orderByFields=OBJECTID+ASC" in source


def test_build_gdal_source_encodes_arcgis_service_paths_with_spaces():
    """ArcGIS service paths with spaces should be encoded before GDAL sees them."""
    source, layer_name = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.arcgis.com/abc/arcgis/rest/services/NJHC Endorsed Plans/FeatureServer",
        "Plans",
        layer_id=0,
        token="abc 123",
        order_field=None,
        result_limit=5,
    )

    assert layer_name == ""
    assert "NJHC%20Endorsed%20Plans" in source
    assert "where=1%3D1" in source
    assert "resultRecordCount=5" in source
    assert "token=abc+123" in source
    assert " " not in source


def test_build_gdal_source_arcgis_result_offset():
    """ArcGIS import chunking should encode resultOffset for paged queries."""
    source, layer_name = build_gdal_source(
        "ArcGIS FeatureServer",
        "https://services.arcgis.com/svc/FeatureServer",
        "my_layer",
        layer_id=0,
        order_field="FID",
        result_limit=2000,
        result_offset=4000,
    )

    assert layer_name == ""
    assert "orderByFields=FID+ASC" in source
    assert "resultRecordCount=2000" in source
    assert "resultOffset=4000" in source


@pytest.mark.asyncio
async def test_fetch_arcgis_pagination_info_requires_explicit_support():
    """Chunking must require ArcGIS supportsPagination, not just maxRecordCount."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = _make_mock_response(
        {
            "maxRecordCount": 1000,
            "advancedQueryCapabilities": {"supportsPagination": False},
        }
    )

    (
        max_record_count,
        supports_pagination,
        object_id_field,
    ) = await fetch_arcgis_pagination_info(
        "https://services.arcgis.com/svc/FeatureServer",
        0,
        mock_client,
    )

    assert max_record_count == 1000
    assert supports_pagination is False
    assert object_id_field is None

    mock_client.get.return_value = _make_mock_response(
        {
            "maxRecordCount": 1000,
            "advancedQueryCapabilities": {"supportsPagination": True},
            "objectIdField": "FID",
        }
    )

    (
        max_record_count,
        supports_pagination,
        object_id_field,
    ) = await fetch_arcgis_pagination_info(
        "https://services.arcgis.com/svc/FeatureServer",
        0,
        mock_client,
    )

    assert max_record_count == 1000
    assert supports_pagination is True
    assert object_id_field == "FID"


@pytest.mark.asyncio
async def test_fetch_arcgis_pagination_info_uses_oid_field_fallback():
    """Layer metadata can identify the stable order field via field type."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = _make_mock_response(
        {
            "maxRecordCount": 1000,
            "advancedQueryCapabilities": {"supportsPagination": True},
            "fields": [
                {"name": "NAME", "type": "esriFieldTypeString"},
                {"name": "OBJECTID_1", "type": "esriFieldTypeOID"},
            ],
        }
    )

    (
        max_record_count,
        supports_pagination,
        object_id_field,
    ) = await fetch_arcgis_pagination_info(
        "https://services.arcgis.com/svc/FeatureServer",
        0,
        mock_client,
    )

    assert max_record_count == 1000
    assert supports_pagination is True
    assert object_id_field == "OBJECTID_1"
