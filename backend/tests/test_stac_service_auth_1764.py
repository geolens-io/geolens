"""Request-only authentication for STAC sources (feat(#1764)).

STAC is the third service family to carry a credential, and it is the first
whose credential never reaches GDAL: the catalog, the item document and the
asset are all read over httpx. So it answers yes to "is this credential a
header line" and no to the three questions ``HEADER_AUTH_SERVICE_FORMATS``
asks, which is why the format sets are asserted apart from each other here.

What these tests pin, in order: the format vocabulary; the wire line's
round trip, which is what lets the refresh worker compose at its own write
sites instead of carrying a finished header; the transport, one test per
door and per method; the two security invariants (a credential does not
follow a cross-origin redirect, and a refused credential is never echoed);
The refresh path's own tests live beside the strategy they exercise, in
``test_stac_refresh_1266.py``, which already owns the dispatch harness.
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
from app.platform import security
from app.platform.security import SSRFError
from app.platform.service_auth import service_carries_method

_ROOT = "https://catalog.test/v1"
_KEY = "s3cretkey123"
_HEADER_NAME = "Ocp-Apim-Subscription-Key"

_LANDING = {"stac_version": "1.0.0", "id": "cat", "title": "Cat", "type": "Catalog"}


def _bearer(token: str = _KEY) -> ServiceCredential:
    return ServiceCredential(method=CredentialMethod.BEARER, token=token)


def _basic(username: str = "reader", password: str = "pw-123") -> ServiceCredential:
    return ServiceCredential(
        method=CredentialMethod.BASIC, username=username, password=password
    )


def _header_key(value: str = _KEY) -> ServiceCredential:
    return ServiceCredential(
        method=CredentialMethod.HEADER_KEY,
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
    async def test_the_asset_probe_carries_it(self, stac_transport) -> None:
        recorded = stac_transport(status=206)
        result = await origin_probe.probe_remote_uri(
            "https://assets.test/scene.tif", credential=_header_key()
        )
        assert result.ok
        assert recorded[0].headers[_HEADER_NAME] == _KEY
        # Still a ranged read: the credential is added, nothing is replaced.
        assert recorded[0].headers["Range"] == "bytes=0-0"


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
    async def test_a_cross_origin_redirect_is_refused_on_the_asset_probe(
        self, stac_transport
    ) -> None:
        def redirect(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "https://elsewhere.test/blob"}
            )

        recorded = stac_transport(redirect)
        result = await origin_probe.probe_remote_uri(
            "https://assets.test/scene.tif", credential=_header_key()
        )
        assert result.health == origin_probe.INACCESSIBLE
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
