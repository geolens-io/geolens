"""Request-only authentication for STAC sources (feat(#1764)).

A STAC credential is a header on every hop and reaches no GDAL header file,
so the format sets, the charset and the wire-line round trip are asserted
separately from the WFS/OAPIF ones. The credential goes to the catalog
origin and nowhere else, whether the other address arrives in a 302 or in
the item document itself, and a refused one is never echoed.

The refresh path's own tests are in ``test_stac_refresh_1266.py``, which
owns the dispatch harness.
"""

import json as _json
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest
import structlog

from app.core.service_tokens import (
    ARCGIS_SERVICE_FORMAT,
    HEADER_AUTH_SERVICE_FORMATS,
    HEADER_LINE_SERVICE_FORMATS,
    STAC_SERVICE_FORMAT,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
    carries_credential_as_header_line,
    credential_from_header_line,
    credential_header_line,
    requires_header_token_policy,
    sends_credential_as_header,
)
from app.modules.catalog.sources import origin_probe
from app.modules.catalog.sources.adapters import stac as stac_adapter
from app.modules.catalog.sources.stac_resolve import resolve_stac_binding
from app.platform import security
from app.platform.security import SSRFError
from app.platform.service_auth import service_carries_method

_ROOT = "https://catalog.test/v1"
_KEY = "s3cretkey123"
_HEADER_NAME = "Ocp-Apim-Subscription-Key"

_LANDING = {"stac_version": "1.0.0", "id": "cat", "title": "Cat", "type": "Catalog"}


# Bound to the STAC format at construction: `origin_probe` composes from the
# credential as given, so an unbound one reads anonymously by design.
def _bearer(token: str = _KEY) -> ServiceCredential:
    return ServiceCredential(
        method=CredentialMethod.BEARER,
        service_format=STAC_SERVICE_FORMAT,
        token=token,
    )


def _basic(username: str = "reader", password: str = "pw-123") -> ServiceCredential:
    return ServiceCredential(
        method=CredentialMethod.BASIC,
        service_format=STAC_SERVICE_FORMAT,
        username=username,
        password=password,
    )


def _header_key(value: str = _KEY) -> ServiceCredential:
    return ServiceCredential(
        method=CredentialMethod.HEADER_KEY,
        service_format=STAC_SERVICE_FORMAT,
        header_name=_HEADER_NAME,
        header_value=value,
    )


# ---------------------------------------------------------------------------
# The format vocabulary
# ---------------------------------------------------------------------------


class TestTheFormatSets:
    """STAC is a header-line format that is not a header-FILE format, and the
    two questions have to stay separable or the base64url charset would
    silently narrow what a STAC bearer token may contain."""

    def test_stac_carries_a_header_line_but_writes_no_header_file(self) -> None:
        assert carries_credential_as_header_line(STAC_SERVICE_FORMAT) is True
        assert sends_credential_as_header(STAC_SERVICE_FORMAT) is True
        assert requires_header_token_policy(STAC_SERVICE_FORMAT) is False
        assert STAC_SERVICE_FORMAT not in HEADER_AUTH_SERVICE_FORMATS
        assert STAC_SERVICE_FORMAT in HEADER_LINE_SERVICE_FORMATS

    def test_arcgis_still_carries_no_header_line(self) -> None:
        """Its worker-side token is a query parameter, so widening the line
        set must not have swept it in."""
        assert carries_credential_as_header_line(ARCGIS_SERVICE_FORMAT) is False

    def test_the_header_file_formats_are_line_formats_too(self) -> None:
        for source_format in HEADER_AUTH_SERVICE_FORMATS:
            assert carries_credential_as_header_line(source_format) is True

    @pytest.mark.parametrize(
        "method", [CredentialMethod.BASIC, CredentialMethod.HEADER_KEY]
    )
    def test_stac_carries_every_method_a_header_can_spell(self, method) -> None:
        assert service_carries_method(STAC_SERVICE_FORMAT, method) is True
        assert service_carries_method(ARCGIS_SERVICE_FORMAT, method) is False

    def test_a_stac_bearer_token_is_judged_as_a_header_value(self) -> None:
        """``+`` and ``/`` are outside base64url and legitimate in a provider
        key. The narrower charset exists for the GDAL header file, which no
        STAC read ever writes."""
        pair = build_credential_header(
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format=STAC_SERVICE_FORMAT,
                token="ab+cd/ef",
            )
        )
        assert pair == ("Authorization", "Bearer ab+cd/ef")
        with pytest.raises(ValueError):
            build_credential_header(
                ServiceCredential(
                    method=CredentialMethod.BEARER,
                    service_format="wfs",
                    token="ab+cd/ef",
                )
            )


# ---------------------------------------------------------------------------
# The wire line round trip
# ---------------------------------------------------------------------------


class TestTheWireLineRoundTrip:
    """The queue is the one hop that cannot compose at the write site, so a
    STAC worker recovers the credential the line describes and composes
    again. Recomposing has to yield the same line, or the worker would
    authenticate as somebody else."""

    @pytest.mark.parametrize(
        "credential",
        [_bearer(), _basic(), _header_key()],
        ids=["bearer", "basic", "header"],
    )
    def test_a_line_recomposes_to_itself(self, credential) -> None:
        bound = replace(credential, service_format=STAC_SERVICE_FORMAT)
        line = credential_header_line(build_credential_header(bound))
        recovered = credential_from_header_line(
            line, service_format=STAC_SERVICE_FORMAT
        )
        assert credential_header_line(build_credential_header(recovered)) == line

    def test_basic_recovers_the_username_and_password(self) -> None:
        line = credential_header_line(
            build_credential_header(
                ServiceCredential(
                    method=CredentialMethod.BASIC,
                    service_format=STAC_SERVICE_FORMAT,
                    username="reader",
                    password="pw:with:colons",
                )
            )
        )
        recovered = credential_from_header_line(line)
        assert recovered.method == CredentialMethod.BASIC
        assert recovered.username == "reader"
        # The colon in the PASSWORD survives: only the first one splits.
        assert recovered.password == "pw:with:colons"

    @pytest.mark.parametrize(
        "line",
        [
            None,
            "",
            "no-separator",
            "Authorization: ",
            ": value",
            "Authorization: Digest abc",
            "Authorization: Basic not-base64!",
            "Authorization: Basic bm9jb2xvbg==",
        ],
    )
    def test_a_line_it_cannot_round_trip_yields_no_credential(self, line) -> None:
        """None means an anonymous request, which fails loudly at the origin.
        A guessed credential would authenticate as something nobody typed."""
        assert credential_from_header_line(line) is None


# ---------------------------------------------------------------------------
# Transport: every STAC read carries the header
# ---------------------------------------------------------------------------


def json_response(status: int, body) -> httpx.Response:
    """A STREAMING JSON response.

    ``bounded_probe_read`` reads through ``aiter_raw``, which a response
    built from an in-memory body refuses with ``StreamConsumed``.
    """
    raw = b"" if body is None else _json.dumps(body).encode()

    async def chunks():
        yield raw

    return httpx.Response(
        status,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        },
        content=chunks(),
    )


@pytest.fixture
def stac_transport(monkeypatch):
    """Answer every STAC read from a mock transport, recording the requests.

    Patches ``make_safe_transport`` rather than the client factory, so the
    client under test is the one ``make_safe_client`` builds and the redirect
    hook this feature depends on is the real one.
    """
    recorded: list[httpx.Request] = []

    def install(handler=None, *, status: int = 200, json_body=None):
        def default(request: httpx.Request) -> httpx.Response:
            return json_response(status, json_body)

        chosen = handler or default

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return chosen(request)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
        return recorded

    return install


class TestEveryStacReadCarriesTheCredential:
    """Probe, preview and import have to agree about what the catalog
    publishes, which they only do if all three ask as the same caller."""

    @pytest.mark.anyio
    async def test_connect_sends_a_bearer_header(self, stac_transport) -> None:
        recorded = stac_transport(json_body=_LANDING)
        result = await stac_adapter.connect_stac_api(_ROOT, _bearer())
        assert result is not None
        assert recorded[0].headers["Authorization"] == f"Bearer {_KEY}"

    @pytest.mark.anyio
    async def test_connect_sends_a_named_api_key(self, stac_transport) -> None:
        recorded = stac_transport(json_body=_LANDING)
        await stac_adapter.connect_stac_api(_ROOT, _header_key())
        assert recorded[0].headers[_HEADER_NAME] == _KEY

    @pytest.mark.anyio
    async def test_connect_sends_basic(self, stac_transport) -> None:
        recorded = stac_transport(json_body=_LANDING)
        await stac_adapter.connect_stac_api(_ROOT, _basic())
        assert recorded[0].headers["Authorization"].startswith("Basic ")

    @pytest.mark.anyio
    async def test_collections_sends_the_credential(self, stac_transport) -> None:
        recorded = stac_transport(json_body={"collections": []})
        await stac_adapter.list_stac_collections(_ROOT, _header_key())
        assert recorded[0].headers[_HEADER_NAME] == _KEY

    @pytest.mark.anyio
    async def test_search_sends_the_credential(self, stac_transport) -> None:
        recorded = stac_transport(json_body={"features": []})
        await stac_adapter.search_stac_items(_ROOT, credential=_header_key())
        assert recorded[0].headers[_HEADER_NAME] == _KEY
        assert recorded[0].method == "POST"

    @pytest.mark.anyio
    async def test_an_anonymous_read_sends_no_credential_header(
        self, stac_transport
    ) -> None:
        recorded = stac_transport(json_body=_LANDING)
        await stac_adapter.connect_stac_api(_ROOT)
        assert "Authorization" not in recorded[0].headers
        assert _HEADER_NAME not in recorded[0].headers

    @pytest.mark.anyio
    async def test_the_item_document_read_carries_it(self, stac_transport) -> None:
        recorded = stac_transport(json_body={"id": "x", "assets": {}})
        await origin_probe.fetch_json_document(
            f"{_ROOT}/collections/c/items/x", credential=_header_key()
        )
        assert recorded[0].headers[_HEADER_NAME] == _KEY

    @pytest.mark.anyio
    async def test_the_asset_probe_never_carries_it(self, stac_transport) -> None:
        """Titiler serves the asset out of process and cannot carry a
        request-only credential, so a probe that used one would report
        `healthy` for tiles that stay unreadable."""
        recorded = stac_transport(status=206)
        result = await origin_probe.probe_remote_uri(f"{_ROOT}/assets/scene.tif")
        assert result.ok
        assert _HEADER_NAME not in recorded[0].headers
        assert "Authorization" not in recorded[0].headers
        assert recorded[0].headers["Range"] == "bytes=0-0"

    @pytest.mark.anyio
    async def test_an_unbound_credential_composes_no_header(
        self, stac_transport
    ) -> None:
        """`origin_probe` serves every origin kind, so it composes from the
        credential as bound rather than relabelling it."""
        recorded = stac_transport(json_body={"id": "x", "assets": {}})
        await origin_probe.fetch_json_document(
            f"{_ROOT}/collections/c/items/x",
            credential=ServiceCredential(
                method=CredentialMethod.HEADER_KEY,
                header_name=_HEADER_NAME,
                header_value=_KEY,
            ),
        )
        assert _HEADER_NAME not in recorded[0].headers


# ---------------------------------------------------------------------------
# Security invariants
# ---------------------------------------------------------------------------


class TestTheCredentialStaysOnItsOrigin:
    """A catalog that 302s a credentialed read elsewhere gets a refusal, not
    the key. httpx would strip ``Authorization`` silently and forward a
    service-chosen name unchanged; neither is an acceptable answer here."""

    @pytest.mark.anyio
    async def test_a_cross_origin_redirect_is_refused_on_the_item_read(
        self, stac_transport
    ) -> None:
        def redirect(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "https://elsewhere.test/collect"}
            )

        recorded = stac_transport(redirect)
        result, document, _url = await origin_probe.fetch_json_document(
            f"{_ROOT}/collections/c/items/x", credential=_header_key()
        )
        # The probe classifies rather than raising, but the second request
        # never went out, which is the property that matters.
        assert result.health == origin_probe.INACCESSIBLE
        assert document is None
        assert len(recorded) == 1

    @pytest.mark.anyio
    async def test_a_same_origin_redirect_still_follows(self, stac_transport) -> None:
        def once(request: httpx.Request) -> httpx.Response:
            if len(recorded) == 1:
                return httpx.Response(
                    302, headers={"Location": f"{_ROOT}/collections/c/items/moved"}
                )
            return json_response(200, {"id": "x", "assets": {}})

        recorded = stac_transport(once)
        result, document, _url = await origin_probe.fetch_json_document(
            f"{_ROOT}/collections/c/items/x", credential=_header_key()
        )
        assert result.ok
        assert document == {"id": "x", "assets": {}}
        assert recorded[1].headers[_HEADER_NAME] == _KEY

    @pytest.mark.anyio
    async def test_the_adapter_declares_the_header_to_the_client(
        self, stac_transport
    ) -> None:
        """The declaration is what turns httpx's silent strip into a refusal,
        so it is asserted at the adapter, not only at the client factory."""

        def redirect(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "https://elsewhere.test/moved"}
            )

        recorded = stac_transport(redirect)
        with pytest.raises(SSRFError):
            await stac_adapter.list_stac_collections(_ROOT, _bearer())
        assert len(recorded) == 1


_ITEM_URL = f"{_ROOT}/collections/c/items/x"
_MIRROR_ITEM = "https://mirror.test/v1/collections/c/items/x"
_FOREIGN_ASSET = "https://assets.example/scene.tif"


def _item_document(self_href: str, asset_href: str) -> dict:
    return {
        "type": "Feature",
        "id": "x",
        "collection": "c",
        "properties": {},
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "links": [{"rel": "self", "href": self_href}],
        "assets": {"data": {"href": asset_href, "roles": ["data"]}},
    }


class TestTheCatalogChoosesTheCredentialNotTheDocument:
    """A STAC item document names its own self link and its assets, and both
    are fetched first-hop, where no redirect hook runs. The credential goes
    only to the origin it was given for."""

    @pytest.mark.anyio
    async def test_a_self_link_and_an_asset_on_other_origins_get_no_credential(
        self, stac_transport
    ) -> None:
        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.host in ("catalog.test", "mirror.test"):
                return json_response(200, _item_document(_MIRROR_ITEM, _FOREIGN_ASSET))
            return json_response(206, None)

        recorded = stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=_FOREIGN_ASSET,
            asset_key="data",
            credential=_header_key(),
            catalog_origin=_ITEM_URL,
        )

        by_host = {request.url.host: request for request in recorded}
        assert by_host["catalog.test"].headers[_HEADER_NAME] == _KEY
        for host, request in by_host.items():
            if host != "catalog.test":
                assert _HEADER_NAME not in request.headers, host
        # The off-origin self link is dropped rather than fetched, so the
        # stored pointer cannot drift off the catalog across refreshes.
        assert "mirror.test" not in by_host
        # The asset is still resolved: a catalog serving assets from someone
        # else's bucket is the ordinary case, not a refusal.
        assert result.asset_href == _FOREIGN_ASSET
        assert result.item_href == _ITEM_URL

    @pytest.mark.anyio
    async def test_a_self_link_on_the_catalog_origin_is_still_followed(
        self, stac_transport
    ) -> None:
        # A permalink: states no identity of its own, so it is adopted on
        # the strength of the document it serves rather than refused.
        moved = f"{_ROOT}/permalink/x"
        document = _item_document(moved, f"{_ROOT}/assets/scene.tif")

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.host != "catalog.test":
                return json_response(404, None)
            if request.url.path.endswith(".tif"):
                return json_response(206, None)
            return json_response(200, document)

        recorded = stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=f"{_ROOT}/assets/scene.tif",
            asset_key="data",
            credential=_header_key(),
            catalog_origin=_ITEM_URL,
        )
        assert result.item_href == moved
        # Every catalog read carries it; the asset probe is anonymous, since
        # Titiler is what actually fetches that URL.
        for request in recorded:
            expected = _KEY if not request.url.path.endswith(".tif") else None
            assert request.headers.get(_HEADER_NAME) == expected, request.url

    @pytest.mark.anyio
    async def test_an_anonymous_refresh_does_not_move_the_anchor(
        self, stac_transport
    ) -> None:
        """The stored pointer is the origin every LATER refresh sends its
        credential to, so an anonymous one may not move it off the catalog
        either. Without this an anonymous refresh adopts the mirror and the
        next credentialed refresh hands it the key on its first read."""

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(".tif"):
                return json_response(206, None)
            return json_response(200, _item_document(_MIRROR_ITEM, _FOREIGN_ASSET))

        recorded = stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=_FOREIGN_ASSET,
            asset_key="data",
        )
        assert result.item_href == _ITEM_URL
        assert all(request.url.host != "mirror.test" for request in recorded)
        # The asset is unaffected: only the POINTER is fenced to the catalog.
        assert result.asset_href == _FOREIGN_ASSET

    @pytest.mark.anyio
    async def test_an_anonymous_same_origin_self_link_is_still_adopted(
        self, stac_transport
    ) -> None:
        """The rule is about the ORIGIN, not about holding a credential:
        fencing on "this read carries no credential" would stop a public
        catalog's pointer following its own canonical URL."""
        moved = f"{_ROOT}/permalink/x"
        asset = f"{_ROOT}/assets/scene.tif"
        document = _item_document(moved, asset)

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.host != "catalog.test":
                return json_response(404, None)
            if request.url.path.endswith(".tif"):
                return json_response(206, None)
            return json_response(200, document)

        stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=asset,
            asset_key="data",
        )
        assert result.item_href == moved


class TestAReflectedCredentialIsNeverStored:
    """An origin can hand the caller's own credential back inside a URL it
    publishes. ``DatasetResponse.origin_ref`` promises it never contains
    credentials, and ADR-002 invariant 4 says the same, so a reflected one is
    refused at the one gate every stored value passes."""

    @pytest.mark.anyio
    async def test_an_asset_href_reflecting_the_credential_is_refused(
        self, stac_transport, monkeypatch
    ) -> None:
        """Under an unlisted parameter name: ``has_url_credentials``
        allowlists NAMES, so only the value check catches this.

        The moved-href probes are stubbed so the refusal cannot be confused
        with a Titiler read that simply failed.
        """
        reflected = f"{_ROOT}/assets/scene.tif?catalog_ref={_KEY}"
        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.validate_url_for_ssrf",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            AsyncMock(return_value={"band_count": 1}),
        )

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/v1/assets/"):
                return json_response(206, None)
            return json_response(200, _item_document(_ITEM_URL, reflected))

        stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=f"{_ROOT}/assets/scene.tif",
            asset_key="data",
            credential=_header_key(),
            catalog_origin=_ITEM_URL,
        )
        assert result.resolved is False
        assert result.asset_href is None
        assert result.detail == origin_probe.UNAUTHORIZED
        assert _KEY not in str(result)

    @pytest.mark.anyio
    async def test_a_self_link_reflecting_the_credential_is_not_adopted(
        self, stac_transport
    ) -> None:
        """The self link becomes the stored item pointer, so it passes the
        same gate before anything can write it."""
        asset = f"{_ROOT}/assets/scene.tif"
        reflected_self = f"{_ROOT}/permalink/x?catalog_ref={_KEY}"

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/v1/assets/"):
                return json_response(206, None)
            return json_response(200, _item_document(reflected_self, asset))

        stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=asset,
            asset_key="data",
            credential=_header_key(),
            catalog_origin=_ITEM_URL,
        )
        # The asset still resolves; only the poisoned pointer is dropped, so
        # the stored one stays what it was.
        assert result.asset_href == asset
        assert result.item_href == _ITEM_URL
        assert _KEY not in str(result)

    @pytest.mark.anyio
    async def test_an_href_carrying_no_credential_is_still_stored(
        self, stac_transport
    ) -> None:
        """The gate reads the registry, so an ordinary query string on a
        credentialed refresh is untouched."""
        asset = f"{_ROOT}/assets/scene.tif?version=3"

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/v1/assets/"):
                return json_response(206, None)
            return json_response(200, _item_document(_ITEM_URL, asset))

        stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=asset,
            asset_key="data",
            credential=_header_key(),
            catalog_origin=_ITEM_URL,
        )
        assert result.asset_href == asset


class TestSearchDoesNotHandBackTheCredential:
    """Only ``item_href`` passes ``storable_href`` on the search path. Every
    other field is echoed to ``/import`` by the client, whose own request
    registers no credential and so cannot recognise one, and is then stored."""

    def _feature(self, **overrides) -> dict:
        feature = {
            "type": "Feature",
            "id": "x",
            "collection": "c",
            "properties": {"title": "Scene"},
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "links": [{"rel": "self", "href": _ITEM_URL}],
            "assets": {
                "data": {"href": f"{_ROOT}/assets/scene.tif", "roles": ["data"]}
            },
        }
        feature.update(overrides)
        return feature

    @pytest.mark.anyio
    async def test_an_item_reflecting_the_credential_is_not_returned(
        self, stac_transport
    ) -> None:
        poisoned = self._feature(
            assets={
                "data": {
                    "href": f"{_ROOT}/assets/scene.tif?catalog_ref={_KEY}",
                    "roles": ["data"],
                }
            }
        )
        recorded = stac_transport(
            json_body={"features": [poisoned], "numberMatched": 1}
        )
        result = await stac_adapter.search_stac_items(_ROOT, credential=_header_key())
        assert result["items"] == []
        assert result["returned"] == 0
        assert _KEY not in str(result)
        # The request itself still carried the credential; only the answer
        # is refused.
        assert recorded[0].headers[_HEADER_NAME] == _KEY

    @pytest.mark.anyio
    async def test_a_reflection_in_a_non_href_field_is_caught_too(
        self, stac_transport
    ) -> None:
        """``id`` becomes ``origin_ref["item_id"]`` and ``source_filename``,
        so a field that is not a URL still reaches storage."""
        stac_transport(
            json_body={"features": [self._feature(id=f"scene-{_KEY}")], "matched": 1}
        )
        result = await stac_adapter.search_stac_items(_ROOT, credential=_header_key())
        assert result["items"] == []

    @pytest.mark.anyio
    async def test_an_ordinary_item_is_returned_unchanged(self, stac_transport) -> None:
        stac_transport(json_body={"features": [self._feature()], "numberMatched": 1})
        result = await stac_adapter.search_stac_items(_ROOT, credential=_header_key())
        assert result["returned"] == 1
        assert result["items"][0]["data_asset_href"] == f"{_ROOT}/assets/scene.tif"


class TestAShortCredentialDoesNotRefuseEveryUrl:
    """The gate refuses storage, so over-matching strands a legitimate
    refresh. A variant too short to be evidence has to BE a whole value."""

    @pytest.mark.anyio
    async def test_a_one_character_key_does_not_refuse_an_unrelated_href(
        self, stac_transport
    ) -> None:
        tiny = ServiceCredential(
            method=CredentialMethod.HEADER_KEY,
            service_format=STAC_SERVICE_FORMAT,
            header_name=_HEADER_NAME,
            header_value="a",
        )
        asset = f"{_ROOT}/assets/scene-alpha.tif"

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(".tif"):
                return json_response(206, None)
            return json_response(200, _item_document(_ITEM_URL, asset))

        stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=asset,
            asset_key="data",
            credential=tiny,
            catalog_origin=_ITEM_URL,
        )
        # "a" occurs in "assets" and "alpha"; neither is the credential.
        assert result.asset_href == asset

    @pytest.mark.anyio
    async def test_a_one_character_key_is_still_caught_as_a_whole_value(
        self, stac_transport
    ) -> None:
        tiny = ServiceCredential(
            method=CredentialMethod.HEADER_KEY,
            service_format=STAC_SERVICE_FORMAT,
            header_name=_HEADER_NAME,
            header_value="a",
        )
        reflected = f"{_ROOT}/assets/scene.tif?catalog_ref=a"

        def routes(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(".tif"):
                return json_response(206, None)
            return json_response(200, _item_document(_ITEM_URL, reflected))

        stac_transport(routes)
        result = await resolve_stac_binding(
            item_href=_ITEM_URL,
            item_id="x",
            collection_id="c",
            asset_href=reflected,
            asset_key="data",
            credential=tiny,
            catalog_origin=_ITEM_URL,
        )
        assert result.resolved is False


class TestARefusedCredentialIsNeverEchoed:
    """The refusal reaches a 422 body, a log line and a job row, so it names
    the policy and never the value."""

    @pytest.mark.parametrize(
        "credential",
        [
            ServiceCredential(
                method=CredentialMethod.HEADER_KEY,
                service_format=STAC_SERVICE_FORMAT,
                header_name="Cookie",
                header_value="s3cret-value-99",
            ),
            ServiceCredential(
                method=CredentialMethod.BASIC,
                service_format=STAC_SERVICE_FORMAT,
                username="user:with:colon",
                password="s3cret-value-99",
            ),
            ServiceCredential(
                method=CredentialMethod.BEARER,
                service_format=STAC_SERVICE_FORMAT,
                token="has space s3cret-value-99",
            ),
        ],
        ids=["reserved-name", "colon-username", "whitespace-token"],
    )
    def test_the_builder_message_never_carries_the_value(self, credential) -> None:
        with pytest.raises(ValueError) as raised:
            build_credential_header(credential)
        assert "s3cret-value-99" not in str(raised.value)

    @pytest.mark.anyio
    async def test_a_failed_read_logs_no_credential(self, stac_transport) -> None:
        """``connect_stac_api`` degrades to None and logs the failure; the
        header it sent must not be in the record."""
        stac_transport(status=500)
        with structlog.testing.capture_logs() as captured:
            result = await stac_adapter.connect_stac_api(_ROOT, _header_key())
        assert result is None
        assert all(_KEY not in str(record) for record in captured)
