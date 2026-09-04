"""The ArcGIS token travels as an Authorization header (lane C2).

Measured live on 2026-09-04 before any of this was written, against
``Cons_Map_WFL1/FeatureServer/0`` on services6.arcgis.com with a token minted
by ``generateToken`` using ``client=referer``:

======================================  ==================================
no credential                           499 "Token Required" in an HTTP 200
``?token=`` (the control)               ``{"count": 9567}``
``X-Esri-Authorization: Bearer <t>``    ``{"count": 9567}``
``Authorization: Bearer <t>``           ``{"count": 9567}``
a wrong or absent ``Referer``           no difference on any of the above
======================================  ==================================

``Authorization`` rather than ``X-Esri-Authorization`` is plan rule A: GDAL
and libcurl strip ``Authorization`` on a cross-host redirect and forward a
custom header verbatim, and httpx does the same, so the standard name is the
one that survives a hostile 302 without needing a rule of its own. No
``Referer`` is sent, because none is needed.

What these tests pin, in order: the version parser and the gate it feeds, the
transport chooser, the header actually reaching every read the adapter makes,
the URL carrying nothing on any of them, the pre-10.5.1 fallback and what
triggers it, and the two security invariants -- a cross-origin redirect does
not carry the header, and no token can reach httpx's ``HTTP Request: GET ...``
INFO line because it is no longer in the URL.
"""

import json as _json
import logging

import httpx
import pytest

from app.core.service_tokens import (
    ARCGIS_SERVICE_FORMAT,
    HEADER_AUTH_SERVICE_FORMATS,
    HEADER_TOKEN_MIN_LENGTH,
    HEADER_TRANSPORT_SERVICE_FORMATS,
    registered_credential_secrets,
    requires_header_token_policy,
    reset_registered_credential_secrets,
    sends_credential_as_header,
)
from app.core.url_redaction import scrub_registered_credentials
from app.modules.catalog.sources.adapters import arcgis as arcgis_mod
from app.modules.catalog.sources.adapters.arcgis import (
    ARCGIS_HEADER_TOKEN_MIN_VERSION,
    arcgis_accepts_header_token,
    arcgis_request_auth,
    build_arcgis_count_query_url,
    enrich_arcgis_feature_counts,
    fetch_arcgis_feature_count,
    fetch_arcgis_layer_preview,
    fetch_arcgis_pagination_info,
    parse_arcgis_current_version,
    probe_arcgis_service,
)
from app.platform.security import SSRFError

_BASE = (
    "https://services6.arcgis.com/ZrVlS0wslq8Nvq5I/arcgis/rest/services/X/FeatureServer"
)
_TOKEN = "tok-C2+slash/AND.more_"


def _stream(data: dict, status_code: int = 200) -> httpx.Response:
    """A response whose body supports the streaming read the adapter uses.

    ``httpx.Response(200, json=...)`` materialises the body at construction, so
    ``client.stream(...)``'s ``aiter_raw()`` over one raises ``StreamConsumed``.
    """
    raw = _json.dumps(data).encode()

    async def _chunks():
        yield raw

    return httpx.Response(status_code, content=_chunks())


def _client(handle) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


_HOSTED_SERVICE = {
    "currentVersion": 11.3,
    "layers": [{"id": 0, "name": "Parcels", "geometryType": "esriGeometryPolygon"}],
}
_HOSTED_LAYER = {
    "currentVersion": 11.3,
    "name": "Parcels",
    "geometryType": "esriGeometryPolygon",
    "objectIdField": "OBJECTID",
    "maxRecordCount": 2000,
    "advancedQueryCapabilities": {"supportsPagination": True},
    "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
    "extent": {"spatialReference": {"latestWkid": 4326}},
}


# ---------------------------------------------------------------------------
# The version gate
# ---------------------------------------------------------------------------


class TestTheVersionParser:
    """Esri encodes a patch release as a second fractional digit.

    10.5.1 is reported as ``10.51``, so a float comparison against 10.5 puts
    the two in the right order for the wrong reason and 10.41 (10.4.1) above
    10.5 for a wrong one. This is the whole reason the parser exists.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("10.5", (10, 5, 0)),
            ("10.51", (10, 5, 1)),
            ("10.5.1", (10, 5, 1)),
            ("10.4", (10, 4, 0)),
            ("10.41", (10, 4, 1)),
            ("10.3", (10, 3, 0)),
            ("10.61", (10, 6, 1)),
            ("10.91", (10, 9, 1)),
            ("11.3", (11, 3, 0)),
            ("11", (11, 0, 0)),
            ("11.3.1", (11, 3, 1)),
            (10.51, (10, 5, 1)),
            (10.5, (10, 5, 0)),
            (11, (11, 0, 0)),
            ("  11.3  ", (11, 3, 0)),
        ],
    )
    def test_it_parses(self, value: object, expected: tuple[int, int, int]) -> None:
        assert parse_arcgis_current_version(value) == expected

    @pytest.mark.parametrize(
        "value", [None, "", "unknown", "v10.5", "10.5-beta", "10..5", True, False, []]
    )
    def test_it_gives_up_rather_than_guessing(self, value: object) -> None:
        assert parse_arcgis_current_version(value) is None

    def test_the_order_the_gate_depends_on(self) -> None:
        """The one comparison this is all for, spelled out."""
        assert parse_arcgis_current_version("10.5") < ARCGIS_HEADER_TOKEN_MIN_VERSION
        assert parse_arcgis_current_version("10.41") < ARCGIS_HEADER_TOKEN_MIN_VERSION
        assert parse_arcgis_current_version("10.51") >= ARCGIS_HEADER_TOKEN_MIN_VERSION
        assert parse_arcgis_current_version("11.3") >= ARCGIS_HEADER_TOKEN_MIN_VERSION


class TestTheHeaderGate:
    @pytest.mark.parametrize(
        "version", ["10.51", "10.6", "10.9", "11.0", "11.3", 11.3, "10.5.1"]
    )
    def test_new_enough_uses_the_header(self, version: object) -> None:
        assert arcgis_accepts_header_token(version) is True

    @pytest.mark.parametrize("version", ["10.5", "10.4", "10.41", "10.3", "9.3", 10.4])
    def test_older_than_10_5_1_uses_the_query(self, version: object) -> None:
        assert arcgis_accepts_header_token(version) is False

    @pytest.mark.parametrize("version", [None, "", "unknown"])
    def test_unknown_uses_the_header(self, version: object) -> None:
        """Hosted ArcGIS Online is the common case and every ArcGIS Server old
        enough to need the query form does report a version. A wrong guess in
        this direction costs one retry; the other direction would put the
        token back in the URL for everyone."""
        assert arcgis_accepts_header_token(version) is True


class TestTheTransportChooser:
    def test_the_header_is_the_default(self) -> None:
        headers, query_token = arcgis_request_auth(_TOKEN)
        assert headers == {"Authorization": f"Bearer {_TOKEN}"}
        assert query_token is None

    def test_an_old_server_gets_the_query_form(self) -> None:
        headers, query_token = arcgis_request_auth(_TOKEN, current_version="10.4")
        assert headers == {}
        assert query_token == _TOKEN

    @pytest.mark.parametrize("token", [None, ""])
    def test_no_token_means_neither(self, token: str | None) -> None:
        assert arcgis_request_auth(token) == ({}, None)

    def test_a_token_that_cannot_be_a_header_value_degrades_to_the_query(
        self,
    ) -> None:
        """The builder refuses whitespace and non-ASCII. No ArcGIS token looks
        like that, but degrading to the query form (which percent-encodes it)
        keeps the pre-C2 behaviour rather than failing a read outright, and
        nothing about the value is logged."""
        headers, query_token = arcgis_request_auth("has space")
        assert headers == {}
        assert query_token == "has space"

    def test_the_two_halves_are_never_both_populated(self) -> None:
        for version in (None, "11.3", "10.4", "nonsense"):
            headers, query_token = arcgis_request_auth(_TOKEN, current_version=version)
            assert bool(headers) != bool(query_token)


class TestTheFormatSets:
    """The GDAL header-FILE question and the httpx header question are two,
    and lane C2 moved ArcGIS across exactly one of them."""

    def test_arcgis_sends_a_header_but_is_not_a_header_file_format(self) -> None:
        assert sends_credential_as_header(ARCGIS_SERVICE_FORMAT) is True
        assert requires_header_token_policy(ARCGIS_SERVICE_FORMAT) is False
        assert ARCGIS_SERVICE_FORMAT not in HEADER_AUTH_SERVICE_FORMATS
        assert ARCGIS_SERVICE_FORMAT in HEADER_TRANSPORT_SERVICE_FORMATS

    def test_the_two_header_file_formats_are_in_both(self) -> None:
        for source_format in ("wfs", "ogcapi_features"):
            assert requires_header_token_policy(source_format) is True
            assert sends_credential_as_header(source_format) is True

    def test_a_format_nobody_taught_it_is_in_neither(self) -> None:
        for source_format in (None, "", "stac", "geojson"):
            assert sends_credential_as_header(source_format) is False


# ---------------------------------------------------------------------------
# Every read the adapter makes
# ---------------------------------------------------------------------------


class TestEveryReadSendsTheHeaderAndNoQueryToken:
    """One case per read site, because each composes its own URL.

    A site that grew back a ``token=`` would still return the right answer and
    would only be visible here.
    """

    pytestmark = pytest.mark.asyncio

    async def _record(self, call) -> list[httpx.Request]:
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            url = str(request.url)
            if "returnCountOnly" in url:
                return _stream({"count": 9567})
            if url.rstrip("/").endswith("FeatureServer"):
                return _stream(_HOSTED_SERVICE)
            if "/query" in url:
                return _stream({"features": [{"attributes": {"OBJECTID": 1}}]})
            return _stream(_HOSTED_LAYER)

        async with _client(handle) as client:
            await call(client)
        assert recorded, "positive control: no request was made"
        return recorded

    @staticmethod
    def _assert_clean(recorded: list[httpx.Request]) -> None:
        for request in recorded:
            assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
            assert "token" not in str(request.url)
            assert _TOKEN not in str(request.url)
            # feat(C2) sends no Referer: measured, and not needed even for a
            # referer-bound token.
            assert "referer" not in {name.lower() for name in request.headers}
            # Rule A: the standard name, not the Esri-specific one.
            assert "x-esri-authorization" not in {
                name.lower() for name in request.headers
            }

    async def test_the_service_probe(self) -> None:
        self._assert_clean(
            await self._record(lambda c: probe_arcgis_service(_BASE, c, token=_TOKEN))
        )

    async def test_the_count_enrichment(self) -> None:
        self._assert_clean(
            await self._record(
                lambda c: enrich_arcgis_feature_counts(
                    _BASE, [{"id": 0, "name": "Parcels"}], c, token=_TOKEN
                )
            )
        )

    async def test_the_feature_count(self) -> None:
        self._assert_clean(
            await self._record(
                lambda c: fetch_arcgis_feature_count(_BASE, 0, c, token=_TOKEN)
            )
        )

    async def test_the_pagination_info(self) -> None:
        self._assert_clean(
            await self._record(
                lambda c: fetch_arcgis_pagination_info(_BASE, 0, c, token=_TOKEN)
            )
        )

    async def test_the_layer_preview(self) -> None:
        """Three reads in one call: layer metadata, sample rows, count."""
        recorded = await self._record(
            lambda c: fetch_arcgis_layer_preview(_BASE, 0, c, token=_TOKEN)
        )
        assert len(recorded) == 3
        self._assert_clean(recorded)

    async def test_an_anonymous_read_sends_no_header_at_all(self) -> None:
        recorded = await self._record(lambda c: probe_arcgis_service(_BASE, c))
        assert "authorization" not in {n.lower() for n in recorded[0].headers}
        assert "token" not in str(recorded[0].url)


class TestTheCountQueryHasOneProducer:
    """fix(#1755 item 14): ``enrich_arcgis_feature_counts`` hand-rolled the
    count query a third time. Folded into the builder, so the enrichment, the
    single-layer fetch and the health probe cannot drift into asking three
    slightly different questions."""

    pytestmark = pytest.mark.asyncio

    async def test_the_enrichment_and_the_single_fetch_issue_the_same_url(
        self,
    ) -> None:
        recorded: list[str] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(str(request.url))
            return _stream({"count": 9567})

        async with _client(handle) as client:
            await enrich_arcgis_feature_counts(
                _BASE, [{"id": 7, "name": "Parcels"}], client, token=_TOKEN
            )
            await fetch_arcgis_feature_count(_BASE, 7, client, token=_TOKEN)

        assert recorded[0] == recorded[1]
        assert recorded[0] == build_arcgis_count_query_url(f"{_BASE}/7")

    async def test_the_fallback_token_is_encoded_by_the_builder(self) -> None:
        """The encoding change #1755 item 14 asked to be called out: the
        fold moved the fallback token from a hand-written ``quote(token,
        safe='')`` to ``urlencode``, which is what the other two sites always
        used."""
        url = build_arcgis_count_query_url(f"{_BASE}/0", "AA'#&ULTRASECRET")
        assert "token=AA%27%23%26ULTRASECRET" in url
        assert "#" not in url
        assert "&ULTRA" not in url


# ---------------------------------------------------------------------------
# The pre-10.5.1 fallback
# ---------------------------------------------------------------------------


class TestThePreTenFiveOneFallback:
    pytestmark = pytest.mark.asyncio

    async def test_a_known_old_version_goes_straight_to_the_query_form(self) -> None:
        """One request, not two: the caller already read ``currentVersion``."""
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return _stream({"count": 12})

        async with _client(handle) as client:
            count = await fetch_arcgis_feature_count(
                _BASE, 0, client, token=_TOKEN, current_version="10.4"
            )

        assert count == 12
        assert len(recorded) == 1
        assert "authorization" not in {n.lower() for n in recorded[0].headers}
        assert "token=" in str(recorded[0].url)

    async def test_a_499_to_the_header_form_retries_with_the_query(self) -> None:
        """The probe has no version yet, so this is how an old server is
        found: it ignores the header, sees no token, and says so."""
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if "token=" not in str(request.url):
                return _stream({"error": {"code": 499, "message": "Token Required"}})
            return _stream({"currentVersion": "10.4", "layers": []})

        async with _client(handle) as client:
            result = await probe_arcgis_service(_BASE, client, token=_TOKEN)

        assert result is not None
        assert len(recorded) == 2
        assert recorded[0].headers["Authorization"] == f"Bearer {_TOKEN}"
        assert "token" not in str(recorded[0].url)
        assert "authorization" not in {n.lower() for n in recorded[1].headers}
        assert "token=" in str(recorded[1].url)

    async def test_a_498_is_not_retried(self) -> None:
        """498 means a token WAS read and rejected, so the header arrived and
        resending the same bad token in a query buys one request and no
        information. The token challenge still reaches the caller."""
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return _stream({"error": {"code": 498, "message": "Invalid Token"}})

        async with _client(handle) as client:
            with pytest.raises(Exception) as raised:
                await probe_arcgis_service(_BASE, client, token=_TOKEN)

        assert "498" in str(raised.value)
        assert len(recorded) == 1

    async def test_an_anonymous_499_is_not_retried(self) -> None:
        """With no token there is no second transport to try."""
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return _stream({"error": {"code": 499, "message": "Token Required"}})

        async with _client(handle) as client:
            with pytest.raises(Exception):
                await probe_arcgis_service(_BASE, client)

        assert len(recorded) == 1

    async def test_the_preview_reads_the_version_once_and_reuses_it(self) -> None:
        """The layer document is fetched anyway, so an old server costs the
        preview one retry rather than one per read."""
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            url = str(request.url)
            if "token=" not in url:
                return _stream({"error": {"code": 499, "message": "Token Required"}})
            if "returnCountOnly" in url:
                return _stream({"count": 3})
            if "/query" in url:
                return _stream({"features": []})
            return _stream({**_HOSTED_LAYER, "currentVersion": "10.4"})

        async with _client(handle) as client:
            preview = await fetch_arcgis_layer_preview(_BASE, 0, client, token=_TOKEN)

        assert preview["feature_count"] == 3
        # metadata (header, 499) + metadata (query) + sample + count = 4.
        assert len(recorded) == 4
        assert all("token=" in str(r.url) for r in recorded[1:])


# ---------------------------------------------------------------------------
# Security invariants
# ---------------------------------------------------------------------------


class TestACrossOriginRedirectDoesNotCarryTheHeader:
    """Rule A, httpx half, and why ``Authorization`` is the name to use.

    httpx drops ``Authorization`` itself when a redirect leaves the origin,
    and forwards any other header verbatim -- which is why a custom name
    (``X-Esri-Authorization``) has to be declared to ``make_safe_client`` and
    this one does not. Recorded per hop, because a test that only reads the
    final request cannot tell a dropped header from one that was never sent.
    """

    pytestmark = pytest.mark.asyncio

    @staticmethod
    def _redirecting(location: str):
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if len(recorded) == 1:
                return httpx.Response(302, headers={"Location": location})
            return _stream({"count": 1})

        return handle, recorded

    async def test_another_origin_gets_no_credential(self) -> None:
        handle, recorded = self._redirecting("https://elsewhere.example/harvest")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), follow_redirects=True
        ) as client:
            await fetch_arcgis_feature_count(_BASE, 0, client, token=_TOKEN)

        assert len(recorded) == 2
        assert recorded[0].headers["Authorization"] == f"Bearer {_TOKEN}"
        assert "authorization" not in {n.lower() for n in recorded[1].headers}
        assert recorded[1].url.host == "elsewhere.example"
        assert all(_TOKEN not in str(r.url) for r in recorded)

    async def test_a_same_origin_redirect_still_authenticates(self) -> None:
        """The counterfactual: without it, the test above would pass for a
        client that simply never sent the header."""
        handle, recorded = self._redirecting(f"{_BASE}/0/query?moved=1")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), follow_redirects=True
        ) as client:
            await fetch_arcgis_feature_count(_BASE, 0, client, token=_TOKEN)

        assert len(recorded) == 2
        assert recorded[1].headers["Authorization"] == f"Bearer {_TOKEN}"

    async def test_the_query_fallback_does_not_follow_a_redirect_either(self) -> None:
        """On the pre-10.5.1 path the credential is in the request URL, and a
        redirect target is chosen by the SERVICE, so it carries none of our
        query string. Pinned so a future 'preserve the query across the
        redirect' convenience cannot land unnoticed."""
        handle, recorded = self._redirecting("https://elsewhere.example/harvest")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), follow_redirects=True
        ) as client:
            await fetch_arcgis_feature_count(
                _BASE, 0, client, token=_TOKEN, current_version="10.4"
            )

        assert "token=" in str(recorded[0].url)
        assert "token=" not in str(recorded[1].url)


class TestTheTokenCannotReachTheHttpxRequestLog:
    """httpx logs every request at INFO as ``HTTP Request: GET <url> ...``.

    That line is the reason the transport moved at all: it is emitted before
    any GeoLens redactor sees it and it renders the URL verbatim. With the
    token out of the URL there is nothing in it to redact.
    """

    pytestmark = pytest.mark.asyncio

    @staticmethod
    async def _httpx_log_lines(**kwargs) -> list[str]:
        """Every line the ``httpx`` logger emits during one count fetch.

        A handler attached directly to that logger rather than ``caplog``:
        ``caplog`` reads records that reach the ROOT logger, and this suite's
        app configuration leaves nothing there to read (the same trap that
        makes ``caplog`` blind to structlog records). Attaching here reads the
        line at the point httpx writes it, which is the point that matters.
        """
        captured: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        logger = logging.getLogger("httpx")
        handler = _Capture()
        previous_level, previous_disabled = logger.level, logger.disabled
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.disabled = False
        try:

            def handle(request: httpx.Request) -> httpx.Response:
                return _stream({"count": 1})

            async with _client(handle) as client:
                await fetch_arcgis_feature_count(_BASE, 0, client, **kwargs)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            logger.disabled = previous_disabled
        return captured

    async def test_no_token_appears_in_the_httpx_request_log(self) -> None:
        lines = await self._httpx_log_lines(token=_TOKEN)
        assert lines, "positive control: httpx logged nothing to compare"
        assert all("HTTP Request" in line for line in lines)
        assert all(_TOKEN not in line for line in lines)
        assert all("token" not in line for line in lines)

    async def test_the_positive_control_the_old_transport_would_have_failed(
        self,
    ) -> None:
        """The same read on the pre-10.5.1 fallback DOES put the token in that
        line. Without this the test above could pass for a request that never
        carried a credential at all."""
        lines = await self._httpx_log_lines(token=_TOKEN, current_version="10.4")
        assert any("token=" in line for line in lines)


# ---------------------------------------------------------------------------
# Audit round 1
# ---------------------------------------------------------------------------


class TestARefusedRedirectHopStillReachesTheDoor:
    """fix(#1840 audit round 1).

    ``SSRFError`` subclasses ``ValueError`` (``platform/security.py``), and the
    first cut of this lane folded ``json.loads`` into the request's own ``try``
    -- so ``except (ValueError, TypeError): return None``, which exists to
    degrade an unparseable body to "not an ArcGIS service", started swallowing
    a refused redirect hop as well. The SSRF stayed blocked either way; what
    regressed is the ANSWER: the ``/probe`` door's coded refusal became "not
    recognized", and the caller went on trying the other probes.
    """

    pytestmark = pytest.mark.asyncio

    async def test_an_ssrf_refusal_propagates(self, monkeypatch) -> None:
        async def _refuse(*_args, **_kwargs):
            raise SSRFError("redirect target refused: evil.example.com")

        monkeypatch.setattr(arcgis_mod, "bounded_probe_read", _refuse)

        async with _client(lambda _request: _stream({})) as client:
            with pytest.raises(SSRFError):
                await probe_arcgis_service(_BASE, client, token=_TOKEN)

    async def test_an_unparseable_body_still_degrades_to_none(self) -> None:
        """The counterfactual. Without it the test above would pass for a
        probe that had stopped catching parse failures at all."""

        def handle(_request: httpx.Request) -> httpx.Response:
            async def _chunks():
                yield b"<html>not json</html>"

            return httpx.Response(200, content=_chunks())

        async with _client(handle) as client:
            assert await probe_arcgis_service(_BASE, client, token=_TOKEN) is None


class TestTheQueryFallbackRegistersItsSecret:
    """fix(#1840 audit round 1).

    ``build_credential_header`` registers the line it composes, so the header
    transport is covered by the exact-value scrub #1770 round 43 introduced.
    The query fallback composes no header and so registered nothing -- on
    exactly the branch that puts the token in a URL, and where this module
    logs the server's own ``message`` at WARNING (``ArcGIS error response:
    url=%s code=%s message=%s``). Redaction there fell back to matching the
    ``token=`` query key by shape, which is the coverage the registry exists
    to replace.
    """

    def test_the_version_gated_fallback_registers_the_token(self) -> None:
        reset_registered_credential_secrets()
        headers, query_token = arcgis_request_auth(_TOKEN, current_version="10.4")
        assert (headers, query_token) == ({}, _TOKEN)
        assert _TOKEN in registered_credential_secrets()
        scrubbed = scrub_registered_credentials(f"Invalid token supplied: {_TOKEN}")
        assert _TOKEN not in scrubbed

    def test_the_unusable_value_fallback_does_not_register(self) -> None:
        """fix(#1840 audit round 2): a value that could not have been a header
        credential is not registered either. It still reaches the origin in
        the query; only the log-scrub registration is gated."""
        reset_registered_credential_secrets()
        unusable = "has space"
        assert arcgis_request_auth(unusable) == ({}, unusable)
        assert registered_credential_secrets() == frozenset()

    @pytest.mark.parametrize("short", ["json", "abc", "a", "tok"])
    def test_a_short_token_is_not_registered(self, short: str) -> None:
        """fix(#1840 audit round 2): exact-value scrubbing is a substring
        replacement over every log line in the request's context, so a short
        value corrupts ordinary text instead of protecting a credential.
        ArcGIS is the one transport that never meets ``HEADER_TOKEN_CHARSET``
        (``credential_or_422`` returns before that check for a URL-query
        format), so nothing upstream rejects a four-character token. Measured:
        registering ``json`` rewrote ``https://json.example.com`` to
        ``https://***.example.com`` in that request's own logs.
        """
        reset_registered_credential_secrets()
        headers, query_token = arcgis_request_auth(short, current_version="10.4")
        assert (headers, query_token) == ({}, short)
        assert registered_credential_secrets() == frozenset()
        assert scrub_registered_credentials("https://json.example.com") == (
            "https://json.example.com"
        )

    def test_a_token_at_the_floor_is_registered(self) -> None:
        """The counterfactual for the floor: one character longer and it is
        registered, so the gate is a length rule and not a switched-off
        registration."""
        reset_registered_credential_secrets()
        at_floor = "a" * HEADER_TOKEN_MIN_LENGTH
        assert arcgis_request_auth(at_floor, current_version="10.4") == ({}, at_floor)
        assert at_floor in registered_credential_secrets()

        reset_registered_credential_secrets()
        below = "a" * (HEADER_TOKEN_MIN_LENGTH - 1)
        assert arcgis_request_auth(below, current_version="10.4") == ({}, below)
        assert registered_credential_secrets() == frozenset()

    def test_the_header_path_registers_the_composed_line(self) -> None:
        """The pre-existing half, asserted beside it so the two are read
        together."""
        reset_registered_credential_secrets()
        headers, query_token = arcgis_request_auth(_TOKEN)
        assert query_token is None
        assert headers  # positive control: a header was composed
        assert f"Authorization: Bearer {_TOKEN}" in registered_credential_secrets()

    def test_nothing_is_registered_without_a_token(self) -> None:
        """The counterfactual: the registry is not simply always non-empty."""
        reset_registered_credential_secrets()
        assert arcgis_request_auth(None) == ({}, None)
        assert registered_credential_secrets() == frozenset()

    @pytest.mark.asyncio
    async def test_the_499_retry_registers_before_it_re_reads(self) -> None:
        """The retry composes its URL directly rather than through the version
        gate, so it needs a registration of its own."""
        reset_registered_credential_secrets()

        def handle(request: httpx.Request) -> httpx.Response:
            if "token=" not in str(request.url):
                return _stream({"error": {"code": 499, "message": "Token Required"}})
            return _stream({"currentVersion": "10.4", "layers": []})

        async with _client(handle) as client:
            await probe_arcgis_service(_BASE, client, token=_TOKEN)

        assert _TOKEN in registered_credential_secrets()
