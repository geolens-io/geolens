"""ArcGIS Online's OGC API Features service, as GeoLens reads it.

The fixtures under ``fixtures/esri_ogc/`` are responses captured from an
ArcGIS Online hosted layer published as an OGC feature service, with the
organization id redacted. The doubles below answer the way that service did:
HTTP 400 for a landing, conformance or collections request whose Accept leads
with ``application/geo+json``, error envelopes in HTTP 200 bodies, and a page
chain that ends on a page without links whose ``numberMatched`` counts from
its own offset.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import secrets
import zlib
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.modules.catalog.sources.adapters.ogcapi import probe_ogcapi
from app.platform import security
from app.platform.security import make_safe_client
from app.platform.service_endpoints import (
    EndpointCheckFailedError,
    assert_endpoints_stay_on_origin,
    read_bounded_body,
)
from app.platform.service_items import (
    EMPTY_PAGE_CODE,
    SERVICE_AUTH_REFUSED_CODE,
    SERVICE_ERROR_CODE,
    ItemFetchFailedError,
    materialise_oapif_items,
)

pytestmark = pytest.mark.anyio

_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "esri_ogc"
_CAPTURED_ORIGIN = "https://services8.arcgis.com/<redacted>"
_ORIGIN = "https://services.arcgis.example/ORG"
_SERVICE = f"{_ORIGIN}/arcgis/rest/services/glTrial2Ogc/OGCFeatureServer"
_ITEMS_PATH = (
    "/ORG/arcgis/rest/services/glTrial2Ogc/OGCFeatureServer/collections/0/items"
)
# The CRS list ArcGIS Online inlines in its collections documents, which makes
# each about 1.85 MB. The capture keeps one entry; the doubles restore the size.
_ESRI_CRS_COUNT = 40_305


def _fixture(name: str) -> dict:
    text = (_FIXTURES / name).read_text().replace(_CAPTURED_ORIGIN, _ORIGIN)
    return json.loads(text)


def _with_esri_crs_list(document: dict) -> dict:
    crs = [
        f"http://www.opengis.net/def/crs/EPSG/0/{code}"
        for code in range(_ESRI_CRS_COUNT)
    ]
    return {**document, "crs": crs}


def _collections() -> dict:
    return _with_esri_crs_list(_fixture("collections.json"))


def _collection() -> dict:
    return _with_esri_crs_list(_fixture("collections.json")["collections"][0])


def _page(name: str, *, next_offset: int | None = None) -> dict:
    page = _fixture(name)
    if next_offset is not None:
        (link,) = [lnk for lnk in page["links"] if lnk["rel"] == "next"]
        link["href"] = f"{_SERVICE}/collections/0/items?offset={next_offset}&limit=4"
    return page


def _streamed(status: int, body: bytes, content_type: str) -> httpx.Response:
    async def _chunks():
        for start in range(0, len(body), 4096):
            yield body[start : start + 4096]

    return httpx.Response(
        status, headers={"Content-Type": content_type}, content=_chunks()
    )


def _json(document: dict) -> httpx.Response:
    return _streamed(200, json.dumps(document).encode(), "application/json")


def _esri(items_by_offset: dict[int, dict] | None = None, *, collection=None):
    """A handler answering as the captured service did. The collection
    document is the one description it serves for a GeoJSON Accept."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rstrip("/")
        if path == _ITEMS_PATH:
            offset = int(request.url.params.get("offset", 0))
            return _json((items_by_offset or {})[offset])
        if path.endswith("/collections/0"):
            return _json(collection if collection is not None else _collection())
        if "application/geo+json" in request.headers.get("Accept", ""):
            return _streamed(400, b"Bad Request", "text/html")
        if path.endswith("/OGCFeatureServer"):
            return _json(_fixture("landing.json"))
        if path.endswith("/conformance"):
            return _json(_fixture("conformance.json"))
        if path.endswith("/collections"):
            return _json(_collections())
        return _streamed(404, b"Not Found", "text/html")

    return handle


def _serve(monkeypatch, handler) -> list[httpx.Request]:
    recorded: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    monkeypatch.setattr(
        security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
    )
    for module in (
        "app.platform.service_endpoints",
        "app.modules.catalog.sources.adapters.ogcapi",
    ):
        monkeypatch.setattr(f"{module}.validate_url_for_ssrf", AsyncMock())
    return recorded


def _credential_line() -> str:
    return f"Authorization: Bearer {secrets.token_urlsafe(24)}"


async def _materialise(tmp_path):
    return await materialise_oapif_items(
        _SERVICE, "0", credential_line=_credential_line(), staging_dir=tmp_path
    )


def _object_ids(path: str) -> list[int]:
    document = json.loads(pathlib.Path(path).read_text())
    return [f["properties"]["OBJECTID"] for f in document["features"]]


class TestDescriptionDocumentsAskForJson:
    async def test_the_probe_detects_the_service(self, monkeypatch) -> None:
        _serve(monkeypatch, _esri())
        credential = ServiceCredential(
            method=CredentialMethod.BEARER,
            service_format="ogcapi_features",
            token=secrets.token_urlsafe(24),
        )

        async with make_safe_client(timeout=5) as client:
            result = await probe_ogcapi(_SERVICE, client, credential)

        assert result is not None
        assert result["service_type"] == "OGC API Features"
        assert [layer["name"] for layer in result["layers"]] == ["0"]

    async def test_the_endpoint_check_reads_the_landing_page(self, monkeypatch) -> None:
        recorded = _serve(monkeypatch, _esri())

        await assert_endpoints_stay_on_origin(
            _SERVICE,
            service_format="ogcapi_features",
            credential_line=_credential_line(),
            deadline=None,
        )

        assert {r.url.path.rsplit("/", 1)[-1] for r in recorded} == {
            "OGCFeatureServer",
            "collections",
        }


class TestTheArcGISPageChainEnds:
    """The last page carries no links, and its ``numberMatched`` counts from
    its own offset rather than across the query."""

    async def test_a_chain_ending_on_a_short_page(self, monkeypatch, tmp_path) -> None:
        _serve(
            monkeypatch,
            _esri(
                {
                    0: _page("items-page-with-next.json", next_offset=4),
                    4: _fixture("items-last-partial-page.json"),
                }
            ),
        )

        extract = await _materialise(tmp_path)

        assert extract.features == 5
        assert extract.total == 5
        assert len(_object_ids(extract.path)) == 5

    async def test_a_chain_ending_on_an_empty_page_after_a_full_one(
        self, monkeypatch, tmp_path
    ) -> None:
        _serve(
            monkeypatch,
            _esri(
                {
                    0: _page("items-page-with-next.json", next_offset=4),
                    4: _page("items-page-with-next.json", next_offset=8),
                    8: _fixture("items-empty-after-full-page.json"),
                }
            ),
        )

        extract = await _materialise(tmp_path)

        assert extract.features == 8
        assert extract.total == 8

    async def test_a_later_page_without_links_or_a_count_is_still_refused(
        self, monkeypatch, tmp_path
    ) -> None:
        cut_off = _fixture("items-last-partial-page.json")
        del cut_off["numberMatched"]
        _serve(
            monkeypatch,
            _esri({0: _page("items-page-with-next.json", next_offset=4), 4: cut_off}),
        )

        with pytest.raises(ItemFetchFailedError):
            await _materialise(tmp_path)
        assert list(tmp_path.iterdir()) == []

    async def test_a_whole_query_count_that_disagrees_is_still_refused(
        self, monkeypatch, tmp_path
    ) -> None:
        first = _page("items-page-with-next.json", next_offset=4)
        first["numberMatched"] = 9
        _serve(
            monkeypatch,
            _esri({0: first, 4: _fixture("items-last-partial-page.json")}),
        )

        with pytest.raises(ItemFetchFailedError):
            await _materialise(tmp_path)


class TestErrorEnvelopesAreReportedAsErrors:
    """ArcGIS answers token and parameter errors with HTTP 200 and a JSON
    ``error`` object instead of the document asked for."""

    async def test_a_token_error_on_the_collection_document(
        self, monkeypatch, tmp_path
    ) -> None:
        _serve(monkeypatch, _esri(collection=_fixture("error-token-required.json")))

        with pytest.raises(EndpointCheckFailedError) as caught:
            await _materialise(tmp_path)

        assert caught.value.code == SERVICE_AUTH_REFUSED_CODE
        assert "499" in caught.value.policy
        assert "Token Required" not in str(caught.value)

    async def test_a_parameter_error_on_an_items_page(
        self, monkeypatch, tmp_path
    ) -> None:
        _serve(monkeypatch, _esri({0: _fixture("error-invalid-parameter.json")}))

        with pytest.raises(EndpointCheckFailedError) as caught:
            await _materialise(tmp_path)

        assert caught.value.code == SERVICE_ERROR_CODE
        assert "400" in caught.value.policy
        assert list(tmp_path.iterdir()) == []


def _encoded(body: bytes, encoding: str, *, chunk: int = 4096) -> httpx.Response:
    async def _chunks():
        for start in range(0, len(body), chunk):
            yield body[start : start + chunk]

    return httpx.Response(
        200,
        headers={"Content-Type": "application/json", "Content-Encoding": encoding},
        content=_chunks(),
    )


def _repeat_aware(page: dict):
    """ArcGIS Online's items endpoint: a gzip request gets the page, an
    identity request gets it once and an empty 200 after that."""
    served: set[str] = set()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/") != _ITEMS_PATH:
            return _esri()(request)
        if "gzip" in request.headers.get("Accept-Encoding", ""):
            return _encoded(gzip.compress(json.dumps(page).encode()), "gzip")
        if str(request.url) in served:
            return _streamed(200, b"", "application/json")
        served.add(str(request.url))
        return _json(page)

    return handle


class TestItemsPagesAcceptGzip:
    """Items pages may arrive gzip-encoded, inflated under the page budget."""

    async def test_a_page_read_twice_is_read_both_times(
        self, monkeypatch, tmp_path
    ) -> None:
        _serve(monkeypatch, _repeat_aware(_fixture("items-last-partial-page.json")))

        first = await _materialise(tmp_path)
        second = await _materialise(tmp_path)

        assert (first.features, second.features) == (1, 1)

    async def test_a_gzip_bomb_is_refused_at_the_cap(self, monkeypatch) -> None:
        budget = 1024 * 1024
        bomb = gzip.compress(b" " * (64 * budget))
        inflated: list[int] = []
        real = zlib.decompressobj

        class _Counting:
            def __init__(self, *args) -> None:
                self._inner = real(*args)

            def decompress(self, data, max_length=0):
                piece = self._inner.decompress(data, max_length)
                inflated.append(len(piece))
                return piece

            def __getattr__(self, name):
                return getattr(self._inner, name)

        monkeypatch.setattr(zlib, "decompressobj", _Counting)

        with pytest.raises(EndpointCheckFailedError):
            await read_bounded_body(_encoded(bomb, "gzip"), budget, gzip=True)

        assert sum(inflated) <= budget + 1

    @pytest.mark.parametrize(
        "body",
        [
            gzip.compress(b'{"type": "FeatureCollection"}')[:-6],
            gzip.compress(b'{"type": "FeatureCollection"}') + b"trailing",
            b"\x1f\x8b\x08\x00not a gzip stream",
        ],
        ids=["truncated", "trailing-garbage", "corrupt"],
    )
    async def test_an_unreadable_gzip_body_is_refused(self, body) -> None:
        with pytest.raises(EndpointCheckFailedError):
            await read_bounded_body(_encoded(body, "gzip"), 1024 * 1024, gzip=True)

    @pytest.mark.parametrize("encoding", ["x-gzip", "deflate", "br", "zstd"])
    async def test_another_encoding_is_refused(self, encoding) -> None:
        body = gzip.compress(b'{"type": "FeatureCollection", "features": []}')

        with pytest.raises(EndpointCheckFailedError):
            await read_bounded_body(_encoded(body, encoding), 1024 * 1024, gzip=True)

    async def test_gzip_is_refused_where_it_was_not_asked_for(self) -> None:
        body = gzip.compress(b'{"links": []}')

        with pytest.raises(EndpointCheckFailedError):
            await read_bounded_body(_encoded(body, "gzip"), 1024 * 1024)


class TestAnEmptyPageSaysSo:
    @pytest.mark.parametrize("encoding", ["identity", "gzip"])
    async def test_a_zero_byte_page(self, monkeypatch, tmp_path, encoding) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.rstrip("/") == _ITEMS_PATH:
                return _encoded(b"", encoding)
            return _esri()(request)

        _serve(monkeypatch, handle)

        with pytest.raises(EndpointCheckFailedError) as caught:
            await _materialise(tmp_path)

        assert caught.value.code == EMPTY_PAGE_CODE
        assert "Retry in a few minutes" in str(caught.value)


class _Spawned:
    returncode = 0

    def __init__(self, stdout: bytes) -> None:
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""

    async def wait(self):
        return self.returncode


def _spawn_reading_the_source(monkeypatch, *, stdout: bytes = b"") -> list[dict]:
    """Stand in for GDAL, recording what each spawn was pointed at and what
    that file held while it ran."""
    seen: list[dict] = []

    async def _fake(*argv, env=None, **kwargs):
        local = [a for a in argv if pathlib.Path(str(a)).is_file()]
        seen.append(
            {
                "argv": argv,
                "features": [
                    json.loads(pathlib.Path(a).read_text())["features"] for a in local
                ],
            }
        )
        return _Spawned(stdout)

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake)
    return seen


def _three_esri_pages() -> dict[int, dict]:
    return {
        0: _page("items-page-with-next.json", next_offset=4),
        4: _page("items-page-with-next.json", next_offset=8),
        8: _fixture("items-last-partial-page.json"),
    }


class TestAnArcGISCollectionIsReadByTheWalkWithoutACredential:
    """GDAL keeps only the last page of an ArcGIS OGC API collection, so the
    import, the refresh (the same call) and the preview read it page by page
    here, credential or not."""

    @pytest.fixture(autouse=True)
    def _staging_dir(self, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))

    async def test_the_import_gets_every_page(self, monkeypatch) -> None:
        from app.processing.ingest.ogr import run_ogr2ogr_service

        recorded = _serve(monkeypatch, _esri(_three_esri_pages()))
        seen = _spawn_reading_the_source(monkeypatch)

        await run_ogr2ogr_service(
            f"OAPIF:{_SERVICE}",
            "0",
            "target_table",
            "PG:dbname=x",
            "ogcapi_features",
            schema="data",
        )

        (spawn,) = seen
        assert not any(str(a).startswith("OAPIF:") for a in spawn["argv"])
        assert [len(f) for f in spawn["features"]] == [9]
        assert not any("Authorization" in r.headers for r in recorded)

    async def test_other_ogc_api_servers_keep_gdal(self, monkeypatch) -> None:
        from app.processing.ingest.ogr import run_ogr2ogr_service

        recorded = _serve(monkeypatch, _esri())
        seen = _spawn_reading_the_source(monkeypatch)

        await run_ogr2ogr_service(
            "OAPIF:https://ogc.example.test/features",
            "0",
            "target_table",
            "PG:dbname=x",
            "ogcapi_features",
            schema="data",
        )

        assert "OAPIF:https://ogc.example.test/features" in seen[0]["argv"]
        assert recorded == []

    async def test_the_preview_reads_the_walk(self, monkeypatch) -> None:
        from app.modules.catalog.sources.preview import run_service_preview

        _serve(monkeypatch, _esri(_three_esri_pages()))
        seen = _spawn_reading_the_source(monkeypatch, stdout=b"{}")

        await run_service_preview(f"OAPIF:{_SERVICE}", "0")

        (spawn,) = seen
        assert not any(str(a).startswith("OAPIF:") for a in spawn["argv"])
        assert spawn["features"] and spawn["features"][0]


_ARCGIS_WFS = (
    "https://dservices.arcgis.example/ORG/arcgis/services/glTrial2Ogc/WFSServer"
)
_OTHER_WFS = "https://geoserver.example.test/geoserver/wfs"


def _paging_off(argv) -> bool:
    flat = [str(a) for a in argv]
    return any(
        flat[i : i + 3] == ["--config", "OGR_WFS_PAGING_ALLOWED", "OFF"]
        for i in range(len(flat))
    )


class TestArcGISWFSIsReadUnpagedAndCounted:
    """ArcGIS WFS reads COUNT as an end index, so GDAL's second page comes
    back empty. Its imports run unpaged and are checked against the
    ``resultType=hits`` total."""

    @pytest.fixture
    def hits(self, monkeypatch):
        fetch = AsyncMock(return_value=None)
        monkeypatch.setattr("app.processing.ingest.ogr.fetch_arcgis_wfs_hits", fetch)
        return fetch

    @pytest.fixture
    def rows(self, monkeypatch):
        count = AsyncMock(return_value=0)
        monkeypatch.setattr("app.processing.ingest.ogr._staged_row_count", count)
        return count

    async def _import(self, url: str) -> None:
        from app.processing.ingest.ogr import run_ogr2ogr_service

        await run_ogr2ogr_service(
            f"WFS:{url}", "glTrial2Ogc:pts", "t", "PG:dbname=x", "wfs", schema="data"
        )

    @pytest.mark.parametrize(("url", "off"), [(_ARCGIS_WFS, True), (_OTHER_WFS, False)])
    async def test_paging_is_off_for_arcgis_only(
        self, monkeypatch, hits, rows, url, off
    ) -> None:
        seen = _spawn_reading_the_source(monkeypatch)

        await self._import(url)

        assert _paging_off(seen[0]["argv"]) is off
        assert hits.await_count == int(off)

    @pytest.mark.parametrize(("url", "off"), [(_ARCGIS_WFS, True), (_OTHER_WFS, False)])
    async def test_the_preview_reads_unpaged_for_arcgis_only(
        self, monkeypatch, url, off
    ) -> None:
        from app.modules.catalog.sources.preview import run_service_preview

        seen = _spawn_reading_the_source(monkeypatch, stdout=b"{}")

        await run_service_preview(f"WFS:{url}", "glTrial2Ogc:pts")

        assert _paging_off(seen[0]["argv"]) is off

    async def test_fewer_features_than_the_total_fails_the_import(
        self, monkeypatch, hits, rows
    ) -> None:
        from app.processing.ingest.ogr import IngestionError

        _spawn_reading_the_source(monkeypatch)
        hits.return_value, rows.return_value = 3000, 1000

        with pytest.raises(IngestionError, match="returned 1000 of 3000 features"):
            await self._import(_ARCGIS_WFS)

    async def test_the_whole_layer_passes(self, monkeypatch, hits, rows) -> None:
        _spawn_reading_the_source(monkeypatch)
        hits.return_value, rows.return_value = 25, 25

        await self._import(_ARCGIS_WFS)

    async def test_no_total_is_no_check(self, monkeypatch, hits, rows) -> None:
        _spawn_reading_the_source(monkeypatch)
        rows.return_value = 1

        await self._import(_ARCGIS_WFS)

        rows.assert_not_awaited()


class TestTheHitsRead:
    def _serve_hits(self, monkeypatch, body: bytes) -> list[httpx.Request]:
        monkeypatch.setattr(
            "app.platform.arcgis_wfs.validate_url_for_ssrf", AsyncMock()
        )
        return _serve(monkeypatch, lambda r: _streamed(200, body, "application/xml"))

    async def test_the_total_comes_from_number_matched(self, monkeypatch) -> None:
        from app.platform.arcgis_wfs import fetch_arcgis_wfs_hits

        recorded = self._serve_hits(
            monkeypatch, (_FIXTURES / "wfs-hits.xml").read_bytes()
        )
        line = _credential_line()

        total = await fetch_arcgis_wfs_hits(
            f"{_ARCGIS_WFS}?token=abc", "glTrial2Ogc:pts", credential_line=line
        )

        assert total == 25
        (request,) = recorded
        assert request.url.params["RESULTTYPE"] == "hits"
        assert request.url.params["TYPENAMES"] == "glTrial2Ogc:pts"
        assert request.url.params["token"] == "abc"
        assert request.headers["Authorization"] == line.partition(": ")[2]

    @pytest.mark.parametrize(
        "body",
        [
            b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"/>',
            b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" numberMatched="unknown"/>',
            b"<not xml",
        ],
        ids=["absent", "unknown", "unparsable"],
    )
    async def test_no_count_is_none(self, monkeypatch, body) -> None:
        from app.platform.arcgis_wfs import fetch_arcgis_wfs_hits

        self._serve_hits(monkeypatch, body)

        assert (
            await fetch_arcgis_wfs_hits(
                _ARCGIS_WFS, "glTrial2Ogc:pts", credential_line=None
            )
            is None
        )


class TestARefreshRefusedForItsTokenIsACredentialFailure:
    def test_the_run_is_recorded_as_credential_expired(self) -> None:
        from app.platform.service_items import ServiceErrorResponseError
        from app.processing.ingest.tasks_reupload import _service_refresh_error_code

        assert _service_refresh_error_code(ServiceErrorResponseError(498)) == (
            "credential_expired"
        )
        assert _service_refresh_error_code(ServiceErrorResponseError(400)) == (
            "service_refresh_failed"
        )
