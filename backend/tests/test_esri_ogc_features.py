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
import re
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


class TestOnlyAnArcGISChainCountsItsOwnRemainder:
    async def test_another_server_ending_that_way_is_refused(
        self, monkeypatch, tmp_path
    ) -> None:
        """Before this rule, a later page with no links was a truncated
        response on every server; it still is anywhere but ArcGIS."""
        other = "https://ogc.example.test/features"
        first = _fixture("items-page-with-next.json")
        (link,) = [lnk for lnk in first["links"] if lnk["rel"] == "next"]
        link["href"] = f"{other}/collections/0/items?offset=4&limit=4"
        last = _fixture("items-last-partial-page.json")

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/items"):
                offset = int(request.url.params.get("offset", 0))
                return _json(first if offset == 0 else last)
            return _json({"id": "0", "links": []})

        _serve(monkeypatch, handle)

        with pytest.raises(ItemFetchFailedError):
            await materialise_oapif_items(
                other, "0", credential_line=_credential_line(), staging_dir=tmp_path
            )
        assert list(tmp_path.iterdir()) == []


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


def _padded_gzip(data: bytes, padding: int) -> bytes:
    """A gzip member whose header comment adds ``padding`` wire bytes that
    inflate to nothing, so its wire size exceeds what it decodes to."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    deflated = compressor.compress(data) + compressor.flush()
    header = b"\x1f\x8b\x08\x10\x00\x00\x00\x00\x00\xff" + b"c" * padding + b"\x00"
    trailer = (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little") + (
        len(data) & 0xFFFFFFFF
    ).to_bytes(4, "little")
    return header + deflated + trailer


class TestTheWireIsCappedApartFromTheDecodedBody:
    async def test_a_page_over_the_budget_on_the_wire_is_refused(self) -> None:
        body = _padded_gzip(b'{"type": "FeatureCollection", "features": []}', 4096)
        assert gzip.decompress(body)

        with pytest.raises(EndpointCheckFailedError):
            await read_bounded_body(_encoded(body, "gzip"), 1024, gzip=True)

    @pytest.mark.parametrize("encoding", ["identity", "gzip"])
    async def test_a_declared_length_over_the_budget_is_refused_unread(
        self, encoding
    ) -> None:
        read: list[int] = []

        async def _chunks():
            read.append(1)
            yield b"{}"

        response = httpx.Response(
            200,
            headers={"Content-Encoding": encoding, "Content-Length": "2048"},
            content=_chunks(),
        )

        with pytest.raises(EndpointCheckFailedError):
            await read_bounded_body(response, 1024, gzip=True)

        assert read == []

    async def test_the_chain_is_held_to_the_cap_on_the_wire(
        self, monkeypatch, tmp_path
    ) -> None:
        """Each page decodes well inside the collection cap, but the bytes
        sent for them do not."""
        from app.platform import service_items

        monkeypatch.setattr(service_items, "MAX_BYTES", 6000)
        pages = {
            0: _page("items-page-with-next.json", next_offset=4),
            4: _fixture("items-last-partial-page.json"),
        }

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.rstrip("/") == _ITEMS_PATH:
                page = pages[int(request.url.params.get("offset", 0))]
                return _encoded(_padded_gzip(json.dumps(page).encode(), 3000), "gzip")
            return _esri(collection={"id": "0", "links": []})(request)

        _serve(monkeypatch, handle)

        with pytest.raises(ItemFetchFailedError):
            await _materialise(tmp_path)


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
    """Some ArcGIS WFS services read COUNT as an end index, so GDAL's second
    page comes back empty. Those imports run unpaged, and every ArcGIS WFS
    import is checked against the ``resultType=hits`` total."""

    @pytest.fixture
    def hits(self, monkeypatch):
        fetch = AsyncMock(return_value=None)
        monkeypatch.setattr("app.processing.ingest.ogr.fetch_arcgis_wfs_hits", fetch)
        return fetch

    @pytest.fixture(autouse=True)
    def version(self, monkeypatch):
        settle = AsyncMock(return_value="2.0.0")
        monkeypatch.setattr("app.processing.ingest.ogr.arcgis_wfs_version", settle)
        return settle

    @pytest.fixture
    def pages(self, monkeypatch):
        probe = AsyncMock(return_value=False)
        monkeypatch.setattr(
            "app.processing.ingest.ogr.arcgis_wfs_pages_by_count", probe
        )
        return probe

    @pytest.fixture
    def rows(self, monkeypatch):
        count = AsyncMock(return_value=0)
        monkeypatch.setattr("app.processing.ingest.ogr.staged_row_count", count)
        return count

    async def _import(self, url: str) -> None:
        from app.processing.ingest.ogr import run_ogr2ogr_service

        await run_ogr2ogr_service(
            f"WFS:{url}", "glTrial2Ogc:pts", "t", "PG:dbname=x", "wfs", schema="data"
        )

    @pytest.mark.parametrize(("pages_by_count", "off"), [(False, True), (True, False)])
    async def test_paging_follows_the_probe(
        self, monkeypatch, hits, pages, rows, pages_by_count, off
    ) -> None:
        seen = _spawn_reading_the_source(monkeypatch)
        pages.return_value = pages_by_count
        hits.return_value, rows.return_value = 25, 25

        await self._import(_ARCGIS_WFS)

        assert _paging_off(seen[0]["argv"]) is off
        assert hits.await_count == 1

    async def test_another_wfs_is_read_as_before(
        self, monkeypatch, hits, pages, rows, version
    ) -> None:
        seen = _spawn_reading_the_source(monkeypatch)

        await self._import(_OTHER_WFS)

        assert not _paging_off(seen[0]["argv"])
        assert (hits.await_count, pages.await_count) == (0, 0)
        version.assert_not_awaited()

    async def test_fewer_features_than_the_total_fails_the_import(
        self, monkeypatch, hits, pages, rows
    ) -> None:
        from app.processing.ingest.ogr import IngestionError

        _spawn_reading_the_source(monkeypatch)
        hits.return_value, rows.return_value = 3000, 1000

        with pytest.raises(IngestionError, match="returned 1000 of 3000 features"):
            await self._import(_ARCGIS_WFS)

    async def test_more_features_than_the_total_fails_the_import(
        self, monkeypatch, hits, pages, rows
    ) -> None:
        from app.processing.ingest.ogr import IngestionError

        _spawn_reading_the_source(monkeypatch)
        hits.return_value, rows.return_value = 1429, 2429

        with pytest.raises(IngestionError, match="repeated features"):
            await self._import(_ARCGIS_WFS)

    async def test_the_whole_layer_passes(self, monkeypatch, hits, pages, rows) -> None:
        _spawn_reading_the_source(monkeypatch)
        hits.return_value, rows.return_value = 25, 25

        await self._import(_ARCGIS_WFS)

    async def test_no_total_fails_before_anything_is_imported(
        self, monkeypatch, hits, pages, rows
    ) -> None:
        from app.processing.ingest.ogr import IngestionError

        seen = _spawn_reading_the_source(monkeypatch)
        rows.return_value = 1000

        with pytest.raises(IngestionError, match="Couldn't count the features"):
            await self._import(_ARCGIS_WFS)

        assert seen == []
        rows.assert_not_awaited()

    async def test_a_namespaced_mismatch_is_not_retried_into_a_pass(
        self, monkeypatch, hits, pages, rows
    ) -> None:
        from app.processing.ingest.ogr import WfsCountMismatchError
        from app.processing.ingest.tasks_common import (
            _run_service_import_with_wfs_fallback,
        )

        _spawn_reading_the_source(monkeypatch)
        # The unqualified retry's hits read fails, the case that let a known
        # truncation through.
        hits.side_effect = [3000, None]
        rows.return_value = 1000

        async def _import(layer: str) -> None:
            from app.processing.ingest.ogr import run_ogr2ogr_service

            await run_ogr2ogr_service(
                f"WFS:{_ARCGIS_WFS}", layer, "t", "PG:dbname=x", "wfs", schema="data"
            )

        with pytest.raises(WfsCountMismatchError, match="returned 1000 of 3000"):
            await _run_service_import_with_wfs_fallback(_import, "glTrial2Ogc:pts")

        assert hits.await_count == 1


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
    """A refresh reads an ArcGIS collection through the walk, and a refused
    token there is recorded as the run's credential failure."""

    @pytest.fixture(autouse=True)
    def _staging_dir(self, tmp_path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))

    async def _refresh_fetch(self, monkeypatch, refusal, *, token: bool) -> Exception:
        from app.processing.ingest.ogr import run_ogr2ogr_service

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.rstrip("/") == _ITEMS_PATH:
                return refusal()
            return _esri()(request)

        _serve(monkeypatch, handle)
        _spawn_reading_the_source(monkeypatch)
        with pytest.raises(Exception) as caught:
            await run_ogr2ogr_service(
                f"OAPIF:{_SERVICE}",
                "0",
                "t",
                "PG:dbname=x",
                "ogcapi_features",
                token=_credential_line() if token else None,
                schema="data",
            )
        return caught.value

    @pytest.mark.parametrize(
        "refusal",
        [
            lambda: _streamed(401, b"", "text/plain"),
            lambda: _streamed(403, b"", "text/plain"),
            lambda: _json(_fixture("error-token-required.json")),
        ],
        ids=["401", "403", "499-envelope"],
    )
    async def test_a_refused_token_is_credential_expired(
        self, monkeypatch, refusal
    ) -> None:
        from app.processing.ingest.tasks_reupload import _service_refresh_error_code

        exc = await self._refresh_fetch(monkeypatch, refusal, token=True)

        assert _service_refresh_error_code(exc) == "credential_expired"

    async def test_an_anonymous_401_is_not_a_refused_credential(
        self, monkeypatch
    ) -> None:
        from app.processing.ingest.tasks_reupload import _service_refresh_error_code

        exc = await self._refresh_fetch(
            monkeypatch, lambda: _streamed(401, b"", "text/plain"), token=False
        )

        assert _service_refresh_error_code(exc) == "service_refresh_failed"

    def test_the_run_is_recorded_as_credential_expired(self) -> None:
        from app.platform.service_items import ServiceErrorResponseError
        from app.processing.ingest.tasks_reupload import _service_refresh_error_code

        assert _service_refresh_error_code(ServiceErrorResponseError(498)) == (
            "credential_expired"
        )
        assert _service_refresh_error_code(ServiceErrorResponseError(400)) == (
            "service_refresh_failed"
        )


_GML = b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0">%s</wfs:FeatureCollection>'
_MEMBER = b"<wfs:member><pts/></wfs:member>"


class TestThePagingProbe:
    """``STARTINDEX=1&COUNT=1`` returns one feature where COUNT is a page
    size and none where it is an end index."""

    def _serve_probe(self, monkeypatch, response: httpx.Response):
        monkeypatch.setattr(
            "app.platform.arcgis_wfs.validate_url_for_ssrf", AsyncMock()
        )
        return _serve(monkeypatch, lambda r: response)

    async def _probe(self) -> bool:
        from app.platform.arcgis_wfs import arcgis_wfs_pages_by_count

        return await arcgis_wfs_pages_by_count(
            _ARCGIS_WFS, "glTrial2Ogc:pts", credential_line=_credential_line()
        )

    async def test_one_feature_means_count_is_a_page_size(self, monkeypatch) -> None:
        recorded = self._serve_probe(
            monkeypatch, _streamed(200, _GML % _MEMBER, "application/xml")
        )

        assert await self._probe() is True
        (request,) = recorded
        assert (request.url.params["STARTINDEX"], request.url.params["COUNT"]) == (
            "1",
            "1",
        )
        assert request.headers["Accept-Encoding"] == "identity"

    @pytest.mark.parametrize(
        "response",
        [
            _streamed(200, _GML % b"", "application/xml"),
            _streamed(200, _GML % (_MEMBER * 3), "application/xml"),
            _streamed(500, b"oops", "text/plain"),
            _streamed(200, b"<not xml", "application/xml"),
        ],
        ids=["end-index", "count-ignored", "error", "unparsable"],
    )
    async def test_anything_else_turns_paging_off(self, monkeypatch, response) -> None:
        self._serve_probe(monkeypatch, response)

        assert await self._probe() is False


class TestTheStagedCountIsReadAfterTheGrant:
    """A multi_tenant SELECT runs as the tenant reader, which can't read the
    table ogr2ogr just created until it is granted. Both staged counts, the
    ArcGIS WFS check and the FeatureServer page guard, grant first."""

    def _record(self, monkeypatch, count: int) -> list[str]:
        statements: list[str] = []

        class _Result:
            def scalar_one(self) -> int:
                return count

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def execute(self, statement, *args, **kwargs):
                statements.append(" ".join(str(statement).split()))
                return _Result()

            async def commit(self) -> None:
                statements.append("COMMIT")

        monkeypatch.setattr("app.core.db.async_session", _Session)
        monkeypatch.setattr(
            "app.processing.ingest.tasks_common._current_tenant_role",
            lambda: "tenant_reader_x",
        )
        return statements

    @staticmethod
    def _granted_then_counted(statements: list[str]) -> None:
        assert statements[0] == 'GRANT SELECT ON "data"."staged_t" TO tenant_reader_x'
        assert statements[1].startswith("SELECT COUNT(*)")
        assert statements[2] == "COMMIT"

    async def test_the_wfs_count(self, monkeypatch) -> None:
        from app.processing.ingest import ogr

        statements = self._record(monkeypatch, 25)

        assert await ogr.staged_row_count("staged_t", "data") == 25

        self._granted_then_counted(statements)

    async def test_the_featureserver_page_guard(self, monkeypatch) -> None:
        from app.processing.ingest import ogr
        from app.processing.ingest.tasks_common import (
            run_paged_arcgis_service_fetch,
        )

        statements = self._record(monkeypatch, 2)
        monkeypatch.setattr(ogr, "run_ogr2ogr_service", AsyncMock())

        await run_paged_arcgis_service_fetch(
            service_type_raw="ArcGIS FeatureServer",
            service_type="arcgis_featureserver",
            source_url="https://services.arcgis.example/ORG/arcgis/rest/services/x/FeatureServer",
            layer_name="x",
            layer_id=0,
            token=None,
            staging_table="staged_t",
            db_conn_str="PG:dbname=x",
            schema="data",
            feature_count=2,
            page_size=2,
            order_field="OBJECTID",
        )

        self._granted_then_counted(statements)


class TestOneClassifierNamesTheArcGISServices:
    @pytest.mark.parametrize(
        ("url", "kind"),
        [
            (_ARCGIS_WFS, "wfs"),
            (f"{_ARCGIS_WFS}/", "wfs"),
            (f"{_ARCGIS_WFS}//", "wfs"),
            (_ARCGIS_WFS.replace("WFSServer", "WFS%53erver"), "wfs"),
            (_ARCGIS_WFS.replace("WFSServer", "wfsSERVER"), "wfs"),
            (f"{_ARCGIS_WFS}?service=WFS&typeName=ns:pts", "wfs"),
            (f"{_ARCGIS_WFS}/extra", None),
            ("https://host/arcgis/services/x/WFSServerX", None),
            (_SERVICE, "oapif"),
            (f"{_SERVICE}/", "oapif"),
            (f"{_SERVICE}/collections/0", "oapif"),
            (f"{_SERVICE}//collections//0?f=json", "oapif"),
            (_SERVICE.replace("OGCFeatureServer", "OGC%46eatureServer"), "oapif"),
            (_SERVICE.replace("OGCFeatureServer", "OGCFeatureServerX"), None),
            (_OTHER_WFS, None),
            ("https://ogc.example.test/features?x=OGCFeatureServer", None),
            (None, None),
            ("", None),
        ],
    )
    def test_the_kind(self, url, kind) -> None:
        from app.platform.esri_services import esri_service_kind

        assert esri_service_kind(url) == kind

    def test_no_other_module_names_the_services(self) -> None:
        """Any other match on these names would be a second classifier, and
        two classifiers disagree on some URL. Mentions count too: a comment
        is where a copy of the rule starts."""
        app = pathlib.Path(__file__).parents[1] / "app"
        allowed = {app / "platform" / "esri_services.py"}
        offenders = [
            str(path.relative_to(app))
            for path in app.rglob("*.py")
            if path not in allowed
            and re.search(r"wfsserver|ogcfeatureserver", path.read_text(), re.I)
        ]
        assert offenders == []
        assert re.search(
            r"wfsserver", (app / "platform" / "esri_services.py").read_text()
        )


_CAPS_11 = (
    b'<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs" version="1.1.0"/>'
)
_HITS_11 = (
    b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs" '
    b'numberOfFeatures="25"/>'
)


class TestTheWFSReadsSpeakTheEndpointsVersion:
    def _serve(self, monkeypatch, handler):
        monkeypatch.setattr(
            "app.platform.arcgis_wfs.validate_url_for_ssrf", AsyncMock()
        )
        return _serve(monkeypatch, handler)

    async def test_a_1_1_only_endpoint_is_counted_in_1_1(self, monkeypatch) -> None:
        from app.platform.arcgis_wfs import arcgis_wfs_version, fetch_arcgis_wfs_hits

        def handle(request: httpx.Request) -> httpx.Response:
            params = request.url.params
            if params.get("REQUEST") == "GetCapabilities":
                return _streamed(200, _CAPS_11, "application/xml")
            if params.get("VERSION") == "1.1.0" and params.get("TYPENAME"):
                return _streamed(200, _HITS_11, "application/xml")
            return _streamed(400, b"unsupported version", "text/plain")

        recorded = self._serve(monkeypatch, handle)

        version = await arcgis_wfs_version(_ARCGIS_WFS, credential_line=None)
        total = await fetch_arcgis_wfs_hits(
            _ARCGIS_WFS, "glTrial2Ogc:pts", credential_line=None, version=version
        )

        assert (version, total) == ("1.1.0", 25)
        assert "VERSION" not in recorded[0].url.params

    async def test_the_urls_own_version_is_kept(self, monkeypatch) -> None:
        from app.platform.arcgis_wfs import arcgis_wfs_version

        recorded = self._serve(monkeypatch, lambda r: _streamed(500, b"", "text/plain"))

        assert (
            await arcgis_wfs_version(
                f"{_ARCGIS_WFS}?service=WFS&version=1.1.0", credential_line=None
            )
            == "1.1.0"
        )
        assert recorded == []

    async def test_a_1_1_endpoint_is_not_probed_for_paging(self, monkeypatch) -> None:
        from app.platform.arcgis_wfs import arcgis_wfs_pages_by_count

        recorded = self._serve(monkeypatch, lambda r: _streamed(500, b"", "text/plain"))

        assert not await arcgis_wfs_pages_by_count(
            _ARCGIS_WFS, "glTrial2Ogc:pts", credential_line=None, version="1.1.0"
        )
        assert recorded == []


class TestTheWFSReadsAreBoundedLikeTheImport:
    async def test_a_private_target_is_refused_unsent(self, monkeypatch) -> None:
        from app.platform.arcgis_wfs import fetch_arcgis_wfs_hits

        recorded = _serve(monkeypatch, lambda r: _streamed(200, _HITS_11, "text/xml"))
        fired: list[int] = []

        total = await fetch_arcgis_wfs_hits(
            "http://127.0.0.1/arcgis/services/x/WFSServer",
            "x:pts",
            credential_line=None,
            on_first_request=lambda: fired.append(1),
        )

        assert total is None
        assert recorded == []
        assert fired == []

    async def test_a_token_in_the_query_holds_the_read_to_its_origin(
        self, monkeypatch
    ) -> None:
        from app.platform.arcgis_wfs import fetch_arcgis_wfs_hits

        monkeypatch.setattr(
            "app.platform.arcgis_wfs.validate_url_for_ssrf", AsyncMock()
        )
        monkeypatch.setattr("app.platform.security.validate_url_for_ssrf", AsyncMock())
        hits = (_FIXTURES / "wfs-hits.xml").read_bytes()

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.host == "elsewhere.example":
                return _streamed(200, hits, "application/xml")
            return httpx.Response(
                302, headers={"Location": "https://elsewhere.example/WFSServer"}
            )

        recorded = _serve(monkeypatch, handle)

        total = await fetch_arcgis_wfs_hits(
            f"{_ARCGIS_WFS}?token=abc", "glTrial2Ogc:pts", credential_line=None
        )

        assert total is None
        assert {r.url.host for r in recorded} == {httpx.URL(_ARCGIS_WFS).host}

    @pytest.mark.parametrize("value", ["\u00b2", "\u0662\u0665", "25.0", "-1"])
    async def test_a_total_that_is_not_ascii_digits_is_no_total(
        self, monkeypatch, value
    ) -> None:
        from app.platform.arcgis_wfs import fetch_arcgis_wfs_hits

        monkeypatch.setattr(
            "app.platform.arcgis_wfs.validate_url_for_ssrf", AsyncMock()
        )
        body = (
            '<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
            f'numberMatched="{value}"/>'
        ).encode()
        _serve(monkeypatch, lambda r: _streamed(200, body, "application/xml"))

        assert (
            await fetch_arcgis_wfs_hits(
                _ARCGIS_WFS, "glTrial2Ogc:pts", credential_line=None
            )
            is None
        )


class TestAFailedRevalidationIsNoContact:
    async def test_the_import_records_no_contact(self, monkeypatch) -> None:
        """The contact callback dates `last_checked_at`; a read refused
        before it is sent reached nothing."""
        from app.platform.security import SSRFError
        from app.processing.ingest.ogr import IngestionError, run_ogr2ogr_service

        monkeypatch.setattr(
            "app.platform.arcgis_wfs.validate_url_for_ssrf",
            AsyncMock(side_effect=SSRFError("private address")),
        )
        recorded = _serve(monkeypatch, lambda r: _streamed(200, b"", "text/xml"))
        seen = _spawn_reading_the_source(monkeypatch)
        contacted: list[int] = []

        with pytest.raises(IngestionError, match="Couldn't count"):
            await run_ogr2ogr_service(
                f"WFS:{_ARCGIS_WFS}",
                "glTrial2Ogc:pts",
                "t",
                "PG:dbname=x",
                "wfs",
                schema="data",
                on_spawn=lambda: contacted.append(1),
            )

        assert (contacted, recorded, seen) == ([], [], [])


class TestAnErrorMemberBesideFeaturesIsNotAnEnvelope:
    async def test_the_page_is_read(self, monkeypatch, tmp_path) -> None:
        page = _fixture("items-last-partial-page.json")
        page["error"] = {"code": 400, "message": "a property named error"}
        _serve(monkeypatch, _esri({0: page}))

        extract = await _materialise(tmp_path)

        assert extract.features == 1


class TestTheWorkerRefusalsKeepTheirCodes:
    """A failed import stores a reason and, for a fixed sentence, its code,
    which the frontend shows in the reader's language."""

    @staticmethod
    def _refusals():
        from app.platform.service_items import EmptyPageError, ServiceErrorResponseError
        from app.processing.ingest.ogr import refuse_short_arcgis_wfs

        def _mismatch(imported: int, expected: int) -> Exception:
            try:
                refuse_short_arcgis_wfs(imported, expected)
            except Exception as exc:  # broad: the refusal under test
                return exc
            raise AssertionError("no refusal")

        return [
            (_mismatch(3000, 3197), "arcgis_wfs_short"),
            (_mismatch(2429, 1429), "arcgis_wfs_repeated"),
            (ServiceErrorResponseError(498), "service_auth_refused"),
            (ServiceErrorResponseError(400), "service_error"),
            (EmptyPageError(), "service_empty_page"),
        ]

    def test_each_stores_its_code(self) -> None:
        from app.core.failure_reason import failure_code, redact_failure_reason

        for exc, code in self._refusals():
            assert failure_code(redact_failure_reason(exc)) == code

    def test_scrubbing_a_secret_keeps_the_code(self) -> None:
        from app.core.failure_reason import failure_code, redact_failure_reason
        from app.core.url_redaction import scrub_secret_from_exception

        for exc, code in self._refusals():
            scrub_secret_from_exception(exc, "s3cr3t-token-value")
            assert failure_code(redact_failure_reason(exc)) == code

    async def test_an_uncountable_wfs_stores_its_code(self, monkeypatch) -> None:
        from app.core.failure_reason import failure_code, redact_failure_reason
        from app.processing.ingest.ogr import IngestionError, run_ogr2ogr_service

        monkeypatch.setattr(
            "app.processing.ingest.ogr.arcgis_wfs_version",
            AsyncMock(return_value="2.0.0"),
        )
        monkeypatch.setattr(
            "app.processing.ingest.ogr.fetch_arcgis_wfs_hits",
            AsyncMock(return_value=None),
        )

        with pytest.raises(IngestionError) as caught:
            await run_ogr2ogr_service(
                f"WFS:{_ARCGIS_WFS}",
                "glTrial2Ogc:pts",
                "t",
                "PG:dbname=x",
                "wfs",
                schema="data",
            )

        assert failure_code(redact_failure_reason(caught.value)) == (
            "arcgis_wfs_count_unavailable"
        )
