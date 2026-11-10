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

import json
import pathlib
import secrets
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
)
from app.platform.service_items import (
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
