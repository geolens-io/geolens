"""An ArcGIS query-string token stays on the origin it was given to.

Below 10.5.1, and on the 499 and web-tier fallbacks, ArcGIS reads put the
token in the URL. httpx never copies a query string across a redirect, so the
token reaches another origin only when the Location names it: the common
``return 301 https://new.example$request_uri`` rewrite does exactly that.
The header transport is refused on any cross-origin hop by name; this file
pins the URL transport through every read that can take it.

The services answer through a real ``make_safe_client`` over a mock
transport, because the claim is about the hook that client installs.
"""

from unittest.mock import AsyncMock
from urllib.parse import quote, unquote

import httpx
import pytest

from app.modules.catalog.sources.adapters.arcgis import (
    enrich_arcgis_feature_counts,
    fetch_arcgis_feature_count,
    fetch_arcgis_id_plan,
    fetch_arcgis_layer_meta,
    fetch_arcgis_layer_preview,
    fetch_arcgis_pagination_info,
    probe_arcgis_service,
)
from app.platform import security
from app.platform.probe_bounds import bounded_probe_read
from app.platform.security import (
    CredentialRedirectError,
    SSRFError,
    make_safe_client,
)
from app.processing.ingest.arcgis_errors import fetch_arcgis_error_detail

pytestmark = pytest.mark.anyio

SERVICE_HOST = "legacy.example"
ELSEWHERE_HOST = "elsewhere.example"
BASE = f"https://{SERVICE_HOST}/arcgis/rest/services/X/FeatureServer"
TOKEN = "tok-3252+slash/AND.more_"
ENCODED = quote(TOKEN, safe="")
LEGACY = "10.4"

_LEGACY_LAYER = {
    "currentVersion": 10.4,
    "name": "Parcels",
    "geometryType": "esriGeometryPolygon",
    "objectIdField": "OBJECTID",
    "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
}
_TOKEN_REQUIRED = {"error": {"code": 499, "message": "Token Required"}}


def _stream(data: dict, status_code: int = 200) -> httpx.Response:
    raw = httpx.Response(200, json=data).content

    async def _chunks():
        yield raw

    return httpx.Response(status_code, content=_chunks())


def _encoded(value: str, times: int) -> str:
    for _ in range(times):
        value = quote(value, safe="")
    return value


def _carries_token(request: httpx.Request) -> bool:
    return TOKEN in unquote(str(request.url))


@pytest.fixture
def service(monkeypatch):
    """A legacy ArcGIS service whose front end rewrites every URL to *host*.

    A request with the token in its URL gets a 302 to the same path and query
    on *host*. A header-only request gets *header_answer* (the 499 envelope by
    default, which sends the adapter to the query form) or the layer document
    on a layer's own metadata path. Every request is recorded, so a test can
    tell a refused hop from one that went out.
    """

    def install(
        host: str = ELSEWHERE_HOST, header_answer: httpx.Response | None = None
    ) -> list[httpx.Request]:
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if request.url.host != SERVICE_HOST or (
                host == SERVICE_HOST and request.url.path.startswith("/moved")
            ):
                return _stream({"count": 7, "objectIds": [1], "layers": []})
            if "token" in request.url.params:
                moved = "/moved" if host == SERVICE_HOST else ""
                return httpx.Response(
                    302,
                    headers={
                        "Location": f"https://{host}{moved}"
                        f"{request.url.raw_path.decode()}"
                    },
                )
            if request.url.path.endswith("/FeatureServer/0"):
                return _stream(_LEGACY_LAYER)
            if header_answer is not None:
                return header_answer
            return _stream(_TOKEN_REQUIRED)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
        return recorded

    return install


def _assert_refused_before_the_other_origin(recorded: list[httpx.Request]) -> None:
    """The query form went out, was redirected, and nothing followed it."""
    assert any(r.url.host == SERVICE_HOST and _carries_token(r) for r in recorded), (
        "positive control: no request took the query-token form"
    )
    assert [r for r in recorded if r.url.host == ELSEWHERE_HOST] == []


# ---------------------------------------------------------------------------
# Every read that can put the token in the URL
# ---------------------------------------------------------------------------


async def test_version_gated_feature_count(service):
    recorded = service()
    async with make_safe_client() as client:
        with pytest.raises(SSRFError) as raised:
            await fetch_arcgis_feature_count(
                BASE, 0, client, token=TOKEN, current_version=LEGACY
            )
    _assert_refused_before_the_other_origin(recorded)
    assert TOKEN not in str(raised.value)


async def test_version_gated_id_plan(service):
    recorded = service()
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await fetch_arcgis_id_plan(
                BASE, 0, client, token=TOKEN, current_version=LEGACY
            )
    _assert_refused_before_the_other_origin(recorded)


async def test_version_gated_pagination_info_degrades(service):
    recorded = service()
    async with make_safe_client() as client:
        result = await fetch_arcgis_pagination_info(
            BASE, 0, client, token=TOKEN, current_version=LEGACY
        )
    assert result == (None, False, None)
    _assert_refused_before_the_other_origin(recorded)


async def test_version_gated_count_enrichment_degrades(service):
    recorded = service()
    async with make_safe_client() as client:
        layers = await enrich_arcgis_feature_counts(
            BASE, [{"id": 0}], client, token=TOKEN, current_version=LEGACY
        )
    assert layers == [{"id": 0, "feature_count": None}]
    _assert_refused_before_the_other_origin(recorded)


async def test_layer_preview_reads_after_the_metadata_names_a_legacy_version(
    service,
):
    """The metadata read learns 10.4, so the sample and count reads go out
    with the token in the URL; both are optional and degrade."""
    recorded = service()
    async with make_safe_client() as client:
        preview = await fetch_arcgis_layer_preview(BASE, 0, client, token=TOKEN)
    assert preview["sample_rows"] == []
    assert preview["feature_count"] is None
    _assert_refused_before_the_other_origin(recorded)


async def test_probe_after_the_499_fallback(service):
    recorded = service()
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await probe_arcgis_service(BASE, client, token=TOKEN)
    _assert_refused_before_the_other_origin(recorded)


async def test_layer_metadata_after_the_499_fallback(service):
    recorded = service()
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await fetch_arcgis_layer_meta(BASE, "1", client, token=TOKEN)
    _assert_refused_before_the_other_origin(recorded)


async def test_count_after_the_web_tier_fallback(service):
    """A 401 from a web tier in front of ArcGIS sends the read to the query
    form without any envelope."""
    recorded = service(header_answer=httpx.Response(401))
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await fetch_arcgis_feature_count(BASE, 0, client, token=TOKEN)
    _assert_refused_before_the_other_origin(recorded)


async def test_import_error_detail_rerun_of_the_gdal_query(service):
    """The worker re-sends the URL GDAL failed on, token included."""
    recorded = service()
    gdal_source = f"ESRIJSON:{BASE}/0/query?f=json&where=1%3D1&token={ENCODED}"
    assert await fetch_arcgis_error_detail(gdal_source, TOKEN) is None
    _assert_refused_before_the_other_origin(recorded)


# ---------------------------------------------------------------------------
# What still follows
# ---------------------------------------------------------------------------


async def test_same_origin_redirect_still_follows_with_the_token(service):
    recorded = service(host=SERVICE_HOST)
    async with make_safe_client() as client:
        count = await fetch_arcgis_feature_count(
            BASE, 0, client, token=TOKEN, current_version=LEGACY
        )
    assert count == 7
    assert len(recorded) == 2
    assert recorded[1].url.path.startswith("/moved")
    assert _carries_token(recorded[1])


@pytest.fixture
def one_redirect(monkeypatch):
    """A 302 to *location* on the first request, 200 after."""

    def install(location: str) -> list[httpx.Request]:
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if len(recorded) == 1:
                return httpx.Response(302, headers={"Location": location})
            return httpx.Response(200, text="ok")

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
        return recorded

    return install


async def test_a_cross_origin_hop_that_drops_the_token_still_follows(one_redirect):
    """An item download that 302s to a signed CDN URL is the ordinary case;
    the token is not in the request that leaves the origin."""
    recorded = one_redirect("https://cdn.example/blob?sig=abc")
    async with make_safe_client() as client:
        response = await client.get(f"https://{SERVICE_HOST}/data?token={TOKEN}")
    assert response.status_code == 200
    assert len(recorded) == 2
    assert not _carries_token(recorded[1])


@pytest.mark.parametrize("token", ["a", "abc1"])
async def test_a_short_token_inside_an_unrelated_value_is_not_an_echo(
    one_redirect, token
):
    recorded = one_redirect(
        "https://cdn.example/%E4%B8%ADa%E6%96%87?sig=xabc1z&q=abc12"
    )
    async with make_safe_client() as client:
        response = await client.get(f"https://{SERVICE_HOST}/data?token={token}")
    assert response.status_code == 200
    assert len(recorded) == 2


async def test_a_token_spelled_by_an_escape_s_hex_digits_is_not_an_echo(
    one_redirect,
):
    recorded = one_redirect("https://cdn.example/%E4%B8%AD")
    async with make_safe_client() as client:
        response = await client.get(f"https://{SERVICE_HOST}/data?token=e4")
    assert response.status_code == 200
    assert len(recorded) == 2


async def test_the_parameter_name_is_matched_case_insensitively(one_redirect):
    recorded = one_redirect(f"https://{ELSEWHERE_HOST}/data?Token={ENCODED}")
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(f"https://{SERVICE_HOST}/data?TOKEN={ENCODED}")
    assert len(recorded) == 1


async def test_the_token_is_found_in_the_target_path_too(one_redirect):
    recorded = one_redirect(f"https://{ELSEWHERE_HOST}/t/{TOKEN}/data")
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(f"https://{SERVICE_HOST}/data?token={TOKEN}")
    assert len(recorded) == 1


@pytest.mark.parametrize(
    "echo",
    [
        pytest.param(f"?token={TOKEN}", id="literal"),
        pytest.param(f"?t={ENCODED}", id="percent-encoded"),
        pytest.param(f"?t={quote(ENCODED, safe='')}", id="double-encoded"),
        pytest.param(f"?t={quote(quote(ENCODED, safe=''), safe='')}", id="triple"),
        pytest.param(f"?t={_encoded(TOKEN, 5)}", id="five-times"),
        pytest.param(f"?t={ENCODED.upper()}", id="any-case"),
        pytest.param(f"#{ENCODED}", id="fragment"),
    ],
)
async def test_every_spelling_of_an_echo_is_refused(one_redirect, echo):
    recorded = one_redirect(f"https://{ELSEWHERE_HOST}/data{echo}")
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(f"https://{SERVICE_HOST}/data?token={ENCODED}")
    assert len(recorded) == 1


async def test_the_header_transport_is_unchanged(one_redirect):
    """No query token at all: the header alone still refuses the hop."""
    recorded = one_redirect(f"https://{ELSEWHERE_HOST}/data")
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(
                f"https://{SERVICE_HOST}/data",
                headers={"X-Esri-Authorization": f"Bearer {TOKEN}"},
            )
    assert len(recorded) == 1


# ---------------------------------------------------------------------------
# Chains, the adapter's strict rule, and the import that would hand GDAL the URL
# ---------------------------------------------------------------------------


@pytest.fixture
def chain(monkeypatch):
    """A 302 to each of *locations* in turn, then a JSON 200."""

    def install(*locations: str) -> list[httpx.Request]:
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if len(recorded) <= len(locations):
                return httpx.Response(
                    302, headers={"Location": locations[len(recorded) - 1]}
                )
            return _stream({"count": 7})

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
        return recorded

    return install


async def _get(url: str, follow: str) -> None:
    async with make_safe_client() as client:
        if follow == "httpx":
            await client.get(url)
        else:
            await bounded_probe_read(client, url, headers={}, accept="application/json")


@pytest.mark.parametrize("follow", ["httpx", "probe-loop"])
async def test_a_same_origin_hop_cannot_launder_the_token_for_the_next(chain, follow):
    """A sign-in front end wraps the request in a return URL, then hands that
    URL to its identity provider."""
    inner = quote(f"/svc?f=json&token={ENCODED}", safe="")
    outer = quote(f"https://{SERVICE_HOST}/svc?f=json&token={ENCODED}", safe="")
    recorded = chain(
        f"/web/login?ReturnUrl={inner}",
        f"https://{ELSEWHERE_HOST}/saml?RelayState={outer}",
    )
    with pytest.raises(SSRFError):
        await _get(f"https://{SERVICE_HOST}/svc?f=json&token={ENCODED}", follow)
    assert [r.url.host for r in recorded] == [SERVICE_HOST, SERVICE_HOST]


async def test_a_token_moved_into_the_path_is_still_followed_into_the_next_hop(chain):
    recorded = chain(f"/t/{ENCODED}/svc", f"https://{ELSEWHERE_HOST}/t/{ENCODED}/svc")
    with pytest.raises(SSRFError):
        await _get(f"https://{SERVICE_HOST}/svc?token={ENCODED}", "httpx")
    assert len(recorded) == 2


async def test_an_adapter_query_token_refuses_any_cross_origin_hop(chain):
    """The adapter composed this URL, and none of its reads needs another
    origin, so the hop is refused even though the token isn't repeated."""
    recorded = chain(f"https://{ELSEWHERE_HOST}/harvest")
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await fetch_arcgis_feature_count(
                BASE, 0, client, token=TOKEN, current_version=LEGACY
            )
    assert len(recorded) == 1


@pytest.mark.parametrize(
    "header_answer",
    [_stream(_TOKEN_REQUIRED), httpx.Response(401)],
    ids=["499", "web-tier"],
)
async def test_a_fallback_query_token_refuses_any_cross_origin_hop(
    monkeypatch, header_answer
):
    """The header read is turned away, the adapter retries with the token in
    the URL, and that request is redirected elsewhere without repeating it."""
    recorded: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if "token" in request.url.params:
            return httpx.Response(
                302, headers={"Location": f"https://{ELSEWHERE_HOST}/harvest"}
            )
        return header_answer

    monkeypatch.setattr(
        security, "make_safe_transport", lambda: httpx.MockTransport(handle)
    )
    monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await fetch_arcgis_layer_meta(BASE, "1", client, token=TOKEN)
    assert [r.url.host for r in recorded] == [SERVICE_HOST, SERVICE_HOST]


async def test_the_import_error_rerun_refuses_any_cross_origin_hop(chain):
    recorded = chain(f"https://{ELSEWHERE_HOST}/harvest")
    gdal_source = f"ESRIJSON:{BASE}/0/query?f=json&token={ENCODED}"
    assert await fetch_arcgis_error_detail(gdal_source, TOKEN) is None
    assert len(recorded) == 1


async def test_a_refused_count_read_fails_the_import(service):
    """GDAL would follow the same redirect with the token in its URL."""
    from app.processing.ingest.tasks_vector import _fetch_arcgis_import_page_info

    service()
    with pytest.raises(CredentialRedirectError):
        await _fetch_arcgis_import_page_info(f"{BASE}", 0, TOKEN)


async def test_the_hook_sees_the_hostname_through_the_pinning_transport(monkeypatch):
    """The real transport pins each hop to an IP and restores the hostname
    before the hook runs; a same-origin echo must still count as same-origin."""
    sent: list[str] = []

    async def _wire(self, request):
        sent.append(str(request.url))
        if len(sent) == 1:
            return httpx.Response(
                302, headers={"Location": f"/moved?token={ENCODED}"}, request=request
            )
        return httpx.Response(200, text="ok", request=request)

    monkeypatch.setattr(
        security, "_resolve_and_validate", AsyncMock(return_value="203.0.113.7")
    )
    monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _wire)

    async with make_safe_client() as client:
        response = await client.get(f"https://{SERVICE_HOST}/svc?token={ENCODED}")

    assert response.status_code == 200
    assert [httpx.URL(url).host for url in sent] == ["203.0.113.7", "203.0.113.7"]
    assert response.url.host == SERVICE_HOST


async def test_a_token_echoed_into_the_hostname_is_refused(one_redirect):
    """httpx lowercases the host, so the comparison ignores case."""
    token = "AbCdEf0123456789xyzTOKEN"
    recorded = one_redirect(f"https://{token}.{ELSEWHERE_HOST}/")
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(f"https://{SERVICE_HOST}/data?token={token}")
    assert len(recorded) == 1


async def test_the_pinning_transport_still_refuses_a_cross_origin_echo(monkeypatch):
    sent: list[str] = []

    async def _wire(self, request):
        sent.append(str(request.url))
        location = f"https://{ELSEWHERE_HOST}/m?token={ENCODED}"
        return httpx.Response(302, headers={"Location": location}, request=request)

    monkeypatch.setattr(
        security, "_resolve_and_validate", AsyncMock(return_value="203.0.113.7")
    )
    monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _wire)

    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(f"https://{SERVICE_HOST}/svc?token={ENCODED}")
    assert len(sent) == 1
