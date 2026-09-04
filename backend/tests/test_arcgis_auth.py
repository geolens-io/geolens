"""Tests for ArcGIS auth fixes: no Bearer header, JSON error detection, objectIdField."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.modules.catalog.sources.adapters.arcgis import (
    ArcGISTokenError,
    build_arcgis_count_query_url,
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
async def test_arcgis_probe_sends_the_token_as_an_authorization_header():
    """feat(C2): the token is a header, and the URL carries no credential.

    This test used to assert the exact opposite -- ``token=mytoken`` in the
    URL and no ``Authorization`` header at all -- because that was the only
    transport ArcGIS was believed to accept here. Measured live on 2026-09-04
    against a referer-bound token on services6.arcgis.com, ``Authorization:
    Bearer`` returns the same count as ``?token=``, so the credential moved
    out of the URL: out of httpx's ``HTTP Request: GET ...`` INFO line, out of
    proxy access logs, and out of the text an origin quotes back in an error.
    """
    recorded: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return _streaming_json_response(
            {
                "currentVersion": 11.3,
                "layers": [
                    {"id": 0, "name": "test", "geometryType": "esriGeometryPoint"}
                ],
            }
        )

    async with _mock_transport_client(handle) as client:
        await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer", client, token="mytoken"
        )

    assert len(recorded) == 1
    assert "token" not in str(recorded[0].url)
    assert recorded[0].headers["Authorization"] == "Bearer mytoken"


@pytest.mark.asyncio
async def test_arcgis_probe_falls_back_to_an_encoded_query_token_on_499():
    """fix(#1746 codex r7) and feat(C2): the pre-10.5.1 fallback still encodes.

    A token with URL-reserved characters must be percent-encoded when it does
    travel in a query string: a raw ``#`` truncates the URL at a fragment
    boundary and a raw ``&`` starts a bogus new query parameter, either of
    which leaks the tail of the token into the actual request AND lets it
    escape the log redactor's URL match.

    Reaching that path now takes a server that answers 499 "Token Required"
    to the header form, which is exactly what an ArcGIS Server older than
    10.5.1 does -- it never reads the header, so it sees no token at all.
    """
    recorded: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if "token=" not in str(request.url):
            return _streaming_json_response(
                {"error": {"code": 499, "message": "Token Required"}}
            )
        return _streaming_json_response({"currentVersion": "10.4", "layers": []})

    async with _mock_transport_client(handle) as client:
        await probe_arcgis_service(
            "https://services.arcgis.com/svc/FeatureServer",
            client,
            token="AA'#&ULTRASECRET",
        )

    assert len(recorded) == 2
    # The first attempt is the header form and carries nothing in the URL.
    assert "token" not in str(recorded[0].url)
    url_called = str(recorded[1].url)
    assert "token=AA%27%23%26ULTRASECRET" in url_called
    assert "Authorization" not in recorded[1].headers
    assert "'" not in url_called
    assert "#" not in url_called
    assert "&ULTRA" not in url_called


@pytest.mark.asyncio
async def test_enrich_arcgis_feature_counts_uses_the_header_and_the_one_builder():
    """fix(#1755 item 14) and feat(C2).

    Two things at once, because the fold is what made the second possible.
    The per-layer count query is composed by ``build_arcgis_count_query_url``
    now rather than by a third hand-rolled concatenation, and the token it
    would have concatenated is an ``Authorization`` header, so the URL this
    site issues is byte-identical to the one the health probe issues.

    fix(#1770 round 44 P1): this read goes through `bounded_probe_read`
    (`client.stream`), so `AsyncMock(spec=httpx.AsyncClient)` -- which cannot
    fake the async-context-manager protocol `.stream()` returns -- is
    replaced with a real client over `MockTransport`, per this file's own
    `_mock_transport_client` helper.
    """
    recorded: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return _streaming_json_response({"count": 5})

    async with _mock_transport_client(handle) as client:
        enriched = await enrich_arcgis_feature_counts(
            "https://services.arcgis.com/svc/FeatureServer",
            [{"id": 0, "name": "layer0"}],
            client,
            token="AA'#&ULTRASECRET",
            current_version="11.3",
        )

    assert enriched[0]["feature_count"] == 5
    assert str(recorded[0].url) == build_arcgis_count_query_url(
        "https://services.arcgis.com/svc/FeatureServer/0"
    )
    assert "token" not in str(recorded[0].url)
    assert recorded[0].headers["Authorization"] == "Bearer AA'#&ULTRASECRET"


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
    """Chunking must require ArcGIS supportsPagination, not just maxRecordCount.

    fix(#1770 round 44 P1): this read now goes through `bounded_probe_read`
    (`client.stream`), so `AsyncMock(spec=httpx.AsyncClient)` -- which cannot
    fake the async-context-manager protocol `.stream()` returns -- is
    replaced with a real client over `MockTransport`. Two sequential calls in
    this one test need two different bodies, so the handler serves from a
    mutable one-item box rather than `AsyncMock`'s `return_value`.
    """
    next_body = [
        {
            "maxRecordCount": 1000,
            "advancedQueryCapabilities": {"supportsPagination": False},
        }
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        return _streaming_json_response(next_body[0])

    async with _mock_transport_client(handle) as client:
        (
            max_record_count,
            supports_pagination,
            object_id_field,
        ) = await fetch_arcgis_pagination_info(
            "https://services.arcgis.com/svc/FeatureServer",
            0,
            client,
        )

        assert max_record_count == 1000
        assert supports_pagination is False
        assert object_id_field is None

        next_body[0] = {
            "maxRecordCount": 1000,
            "advancedQueryCapabilities": {"supportsPagination": True},
            "objectIdField": "FID",
        }

        (
            max_record_count,
            supports_pagination,
            object_id_field,
        ) = await fetch_arcgis_pagination_info(
            "https://services.arcgis.com/svc/FeatureServer",
            0,
            client,
        )

    assert max_record_count == 1000
    assert supports_pagination is True
    assert object_id_field == "FID"


@pytest.mark.asyncio
async def test_fetch_arcgis_pagination_info_uses_oid_field_fallback():
    """Layer metadata can identify the stable order field via field type.

    fix(#1770 round 44 P1): see the sibling test above for why this is a
    real MockTransport client now rather than an `AsyncMock`.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        return _streaming_json_response(
            {
                "maxRecordCount": 1000,
                "advancedQueryCapabilities": {"supportsPagination": True},
                "fields": [
                    {"name": "NAME", "type": "esriFieldTypeString"},
                    {"name": "OBJECTID_1", "type": "esriFieldTypeOID"},
                ],
            }
        )

    async with _mock_transport_client(handle) as client:
        (
            max_record_count,
            supports_pagination,
            object_id_field,
        ) = await fetch_arcgis_pagination_info(
            "https://services.arcgis.com/svc/FeatureServer",
            0,
            client,
        )

    assert max_record_count == 1000
    assert supports_pagination is True
    assert object_id_field == "OBJECTID_1"


class TestArcGISReadsAreBounded:
    """fix(#1770 round 44 P1, `adapters/arcgis.py:291,353,386,441,485`).

    `enrich_arcgis_feature_counts`/`fetch_arcgis_feature_count`/
    `fetch_arcgis_pagination_info`/`fetch_arcgis_layer_preview` (two sites)
    all carry the request-scoped ArcGIS ``token=`` in the URL and used a
    plain `client.get`. Round 41's own docstring justified leaving these out
    of `bounded_probe_read`'s reach on the theory that
    `assert_endpoints_stay_on_origin` had already vetted the target -- wrong
    for ArcGIS specifically, since that function returns immediately for any
    `service_format` outside `HEADER_AUTH_SERVICE_FORMATS`, which ArcGIS is
    deliberately not a member of (its token travels in the URL, never a
    header). No bound of any kind ran for these five reads before this
    round. All five now read through `bounded_probe_read` under
    `DEFAULT_CHECK_TIMEOUT`, matching the four service-type probes.
    """

    pytestmark = pytest.mark.asyncio

    async def test_enrich_arcgis_feature_counts_stops_at_the_byte_cap(self) -> None:
        from app.platform.service_endpoints import MAX_DOCUMENT_BYTES

        chunk_size = 1024 * 1024
        chunks_yielded = 0

        async def _chunks():
            nonlocal chunks_yielded
            total = (MAX_DOCUMENT_BYTES // chunk_size) + 50
            for _ in range(total):
                chunks_yielded += 1
                yield b"a" * chunk_size

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            result = await enrich_arcgis_feature_counts(
                "https://services.arcgis.com/svc/FeatureServer",
                [{"id": 0, "name": "layer0"}],
                client,
                token="tok",
            )

        assert result == [{"id": 0, "name": "layer0", "feature_count": None}]
        assert chunks_yielded <= (MAX_DOCUMENT_BYTES // chunk_size) + 2, chunks_yielded

    async def test_fetch_arcgis_feature_count_stops_at_the_byte_cap(self) -> None:
        from app.modules.catalog.sources.adapters.arcgis import (
            EndpointCheckFailedError,
            fetch_arcgis_feature_count,
        )
        from app.platform.service_endpoints import MAX_DOCUMENT_BYTES

        chunk_size = 1024 * 1024
        chunks_yielded = 0

        async def _chunks():
            nonlocal chunks_yielded
            total = (MAX_DOCUMENT_BYTES // chunk_size) + 50
            for _ in range(total):
                chunks_yielded += 1
                yield b"a" * chunk_size

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            with pytest.raises(EndpointCheckFailedError):
                await fetch_arcgis_feature_count(
                    "https://services.arcgis.com/svc/FeatureServer", 0, client
                )

        assert chunks_yielded <= (MAX_DOCUMENT_BYTES // chunk_size) + 2, chunks_yielded

    async def test_fetch_arcgis_pagination_info_stops_at_the_byte_cap(self) -> None:
        from app.platform.service_endpoints import MAX_DOCUMENT_BYTES

        chunk_size = 1024 * 1024
        chunks_yielded = 0

        async def _chunks():
            nonlocal chunks_yielded
            total = (MAX_DOCUMENT_BYTES // chunk_size) + 50
            for _ in range(total):
                chunks_yielded += 1
                yield b"a" * chunk_size

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            result = await fetch_arcgis_pagination_info(
                "https://services.arcgis.com/svc/FeatureServer", 0, client
            )

        assert result == (None, False, None)
        assert chunks_yielded <= (MAX_DOCUMENT_BYTES // chunk_size) + 2, chunks_yielded

    async def test_fetch_arcgis_layer_preview_metadata_stops_at_the_byte_cap(
        self,
    ) -> None:
        from app.modules.catalog.sources.adapters.arcgis import (
            EndpointCheckFailedError,
            fetch_arcgis_layer_preview,
        )
        from app.platform.service_endpoints import MAX_DOCUMENT_BYTES

        chunk_size = 1024 * 1024
        chunks_yielded = 0

        async def _chunks():
            nonlocal chunks_yielded
            total = (MAX_DOCUMENT_BYTES // chunk_size) + 50
            for _ in range(total):
                chunks_yielded += 1
                yield b"a" * chunk_size

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            with pytest.raises(EndpointCheckFailedError):
                await fetch_arcgis_layer_preview(
                    "https://services.arcgis.com/svc/FeatureServer", 0, client
                )

        assert chunks_yielded <= (MAX_DOCUMENT_BYTES // chunk_size) + 2, chunks_yielded

    async def test_fetch_arcgis_layer_preview_sample_query_degrades_at_the_byte_cap(
        self,
    ) -> None:
        """The metadata call succeeds; the sample-row call is the one that
        exceeds the cap and degrades, matching this function's own
        best-effort local except clause rather than raising.

        Also counts chunks yielded for the sample query specifically, so
        this discriminates the fix from the old code: both degrade to the
        same result (the old `client.get`'s eventual `JSONDecodeError` on
        the un-parseable filler is caught by the same `except ValueError`
        the new `EndpointCheckFailedError` is), but only the fix stops
        reading anywhere near the cap rather than buffering the whole body
        first.
        """
        from app.modules.catalog.sources.adapters.arcgis import (
            fetch_arcgis_layer_preview,
        )
        from app.platform.service_endpoints import MAX_DOCUMENT_BYTES

        meta = {
            "name": "Parcels",
            "geometryType": "esriGeometryPolygon",
            "extent": {"spatialReference": {"wkid": 3857}},
            "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        }
        chunk_size = 1024 * 1024
        calls = 0
        sample_chunks_yielded = 0

        async def _oversized_chunks():
            nonlocal sample_chunks_yielded
            total = (MAX_DOCUMENT_BYTES // chunk_size) + 50
            for _ in range(total):
                sample_chunks_yielded += 1
                yield b"a" * chunk_size

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            # 1st call: metadata (succeeds). 2nd: the sample query -- the one
            # under test, oversized. 3rd: fetch_arcgis_layer_preview's own
            # unconditional feature-count read, which must stay isolated
            # from the chunk count above or it silently doubles it.
            if calls == 1:
                return _streaming_json_response(meta)
            if calls == 2:
                return httpx.Response(200, content=_oversized_chunks())
            return _streaming_json_response({"count": 5})

        async with _mock_transport_client(handle) as client:
            result = await fetch_arcgis_layer_preview(
                "https://services.arcgis.com/svc/FeatureServer", 0, client
            )

        assert result["layer_name"] == "Parcels"
        assert result["sample_rows"] == []
        assert result["feature_count"] == 5
        assert sample_chunks_yielded <= (MAX_DOCUMENT_BYTES // chunk_size) + 2, (
            sample_chunks_yielded
        )


_NON_DICT_ARCGIS_BODIES = ("5", "[]", '"x"', "null")


class TestArcGISNonDictResponsesDoNotCrash:
    """fix(#1770 round 45 P2, `adapters/arcgis.py:317,397,516,564`).

    Round 44's non-dict guard was added only to `probe_arcgis_service`'s
    service-root response. The four reads round 44 converted to
    `bounded_probe_read` in the same file -- `_fetch_count`,
    `fetch_arcgis_feature_count`, and `fetch_arcgis_layer_preview`'s
    metadata and sample-row reads -- still do `"error" in data` /
    `data.get(...)` straight after `json.loads`, with no `isinstance`
    guard. A layer endpoint answering `200 5` raises `TypeError` on
    `"error" in data`; `200 []` raises `AttributeError` on `.get(...)`.
    `_fetch_count`'s own except lists `ValueError`/`KeyError` only,
    `fetch_arcgis_feature_count` has no local `except` at all, and neither
    the preview caller's own body nor the router's ArcGIS except clause
    catches `TypeError`/`AttributeError`, so a probe (`enrich_arcgis_
    feature_counts` under `asyncio.gather`) or a preview returned a bare
    500 instead of a degraded result.

    fix(#1770 round 49 P3, `adapters/arcgis.py:462`): the whole-diff audit
    caught the fifth sibling this round missed --
    `fetch_arcgis_pagination_info`, same shape (`"error" in data` with no
    local `except`), same class, same fix.
    """

    pytestmark = pytest.mark.asyncio

    @pytest.mark.parametrize("body", _NON_DICT_ARCGIS_BODIES)
    async def test_fetch_count_site(self, body: str) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            async def _chunks():
                yield body.encode()

            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            result = await enrich_arcgis_feature_counts(
                "https://services.arcgis.com/svc/FeatureServer",
                [{"id": 0, "name": "layer0"}],
                client,
            )

        assert result == [{"id": 0, "name": "layer0", "feature_count": None}]

    @pytest.mark.parametrize("body", _NON_DICT_ARCGIS_BODIES)
    async def test_fetch_arcgis_feature_count_site(self, body: str) -> None:
        from app.modules.catalog.sources.adapters.arcgis import (
            fetch_arcgis_feature_count,
        )

        def handle(request: httpx.Request) -> httpx.Response:
            async def _chunks():
                yield body.encode()

            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            result = await fetch_arcgis_feature_count(
                "https://services.arcgis.com/svc/FeatureServer", 0, client
            )

        assert result is None

    @pytest.mark.parametrize("body", _NON_DICT_ARCGIS_BODIES)
    async def test_fetch_arcgis_pagination_info_site(self, body: str) -> None:
        from app.modules.catalog.sources.adapters.arcgis import (
            fetch_arcgis_pagination_info,
        )

        def handle(request: httpx.Request) -> httpx.Response:
            async def _chunks():
                yield body.encode()

            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            result = await fetch_arcgis_pagination_info(
                "https://services.arcgis.com/svc/FeatureServer", 0, client
            )

        assert result == (None, False, None)

    @pytest.mark.parametrize("body", _NON_DICT_ARCGIS_BODIES)
    async def test_fetch_arcgis_layer_preview_metadata_site(self, body: str) -> None:
        from app.modules.catalog.sources.adapters.arcgis import (
            fetch_arcgis_layer_preview,
        )

        def handle(request: httpx.Request) -> httpx.Response:
            async def _chunks():
                yield body.encode()

            return httpx.Response(200, content=_chunks())

        async with _mock_transport_client(handle) as client:
            with pytest.raises(ValueError, match="not an object"):
                await fetch_arcgis_layer_preview(
                    "https://services.arcgis.com/svc/FeatureServer", 0, client
                )

    @pytest.mark.parametrize("body", _NON_DICT_ARCGIS_BODIES)
    async def test_fetch_arcgis_layer_preview_sample_rows_site(self, body: str) -> None:
        from app.modules.catalog.sources.adapters.arcgis import (
            fetch_arcgis_layer_preview,
        )

        meta = {
            "name": "Parcels",
            "geometryType": "esriGeometryPolygon",
            "extent": {"spatialReference": {"wkid": 3857}},
            "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        }
        calls = 0

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            # 1st call: metadata (succeeds). 2nd: the sample query, the
            # non-dict body under test. 3rd: the unconditional feature-count
            # read, which must succeed normally so this test isolates the
            # sample-rows site specifically.
            if calls == 1:
                return _streaming_json_response(meta)
            if calls == 2:

                async def _chunks():
                    yield body.encode()

                return httpx.Response(200, content=_chunks())
            return _streaming_json_response({"count": 5})

        async with _mock_transport_client(handle) as client:
            result = await fetch_arcgis_layer_preview(
                "https://services.arcgis.com/svc/FeatureServer", 0, client
            )

        assert result["layer_name"] == "Parcels"
        assert result["sample_rows"] == []
        assert result["feature_count"] == 5
