"""A credential header stays on the origin it was given to (fix(#1746)).

httpx removes ``Authorization`` when a redirect changes origin and forwards
every other header unchanged. The header-key auth method sends a credential
under a name the service chose -- ``X-API-Key``, Ordnance Survey's ``key``,
Azure's ``Ocp-Apim-Subscription-Key`` -- so without this check a 302 from a
probed service hands that key to whatever origin the Location names.

The per-hop SSRF revalidation next to this does not close it. That one asks
whether the target is a private address; this one asks whether it is the same
service. A redirect to an ordinary public host passes the first question and
fails the second.

These tests drive a real client from ``make_safe_client`` over a mock
transport, because two of the claims are about what httpx itself does: that a
response hook raising stops the follow before a second request goes out, and
that httpx strips ``Authorization`` on its own. Asserted against a stub, both
would break silently on an httpx bump.
"""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.platform import security
from app.platform.security import SSRFError, make_safe_client

CREDENTIAL = "k1234567"
FIRST = "https://service.example/data"
SAME_ORIGIN = "https://service.example/moved"
DEFAULT_PORT = "https://service.example:443/moved"
CROSS_ORIGIN = "https://elsewhere.example/collect"


@pytest.fixture
def transport(monkeypatch):
    """Install a transport that answers one 302 to *location*, then 200.

    Patches the transport factory rather than reaching into the client, so the
    client under test is the one ``make_safe_client`` actually builds, and
    patches the SSRF validator so following a redirect does not depend on DNS.
    Passing None answers 200 immediately.
    """

    def install(location: str | None) -> list[httpx.Request]:
        recorded: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if location is not None and len(recorded) == 1:
                return httpx.Response(302, headers={"Location": location})
            return httpx.Response(200, text="ok")

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        monkeypatch.setattr(security, "validate_url_for_ssrf", AsyncMock())
        return recorded

    return install


def _assert_real_client(client: httpx.AsyncClient) -> None:
    """Guard against a sibling module's leaked patch of httpx.AsyncClient.

    ``test_ssrf_redirect.py`` records contamination at this layer as a known
    hazard, so a client that is not a real one fails here saying so, rather
    than further down looking like a policy bug.
    """
    assert isinstance(client, httpx.AsyncClient), (
        "make_safe_client did not return a real httpx client, so this test is "
        "measuring a leaked patch rather than the redirect policy"
    )


@pytest.mark.anyio
async def test_cross_origin_redirect_carrying_the_credential_is_refused(transport):
    """The finding: the key must not reach the origin the 302 names."""
    recorded = transport(CROSS_ORIGIN)
    async with make_safe_client(credential_header="X-API-Key") as client:
        _assert_real_client(client)
        with pytest.raises(SSRFError) as raised:
            await client.get(FIRST, headers={"X-API-Key": CREDENTIAL})

    assert security.CROSS_ORIGIN_CREDENTIAL_POLICY in str(raised.value)
    assert CREDENTIAL not in str(raised.value)
    # The hook runs before httpx follows, so the second request never happened.
    assert len(recorded) == 1


@pytest.mark.anyio
async def test_the_declared_name_is_matched_case_insensitively(transport):
    """HTTP field names are case-insensitive and callers spell them either way."""
    recorded = transport(CROSS_ORIGIN)
    async with make_safe_client(credential_header="X-API-Key") as client:
        with pytest.raises(SSRFError):
            await client.get(FIRST, headers={"x-api-key": CREDENTIAL})
    assert len(recorded) == 1


@pytest.mark.anyio
async def test_same_origin_redirect_still_follows_with_the_credential(transport):
    """A service moving its own path is the ordinary case and keeps working."""
    recorded = transport(SAME_ORIGIN)
    async with make_safe_client(credential_header="X-API-Key") as client:
        response = await client.get(FIRST, headers={"X-API-Key": CREDENTIAL})

    assert response.status_code == 200
    assert len(recorded) == 2
    assert recorded[1].headers.get("X-API-Key") == CREDENTIAL


@pytest.mark.anyio
async def test_the_scheme_default_port_is_the_same_origin(transport):
    """``https://host`` and ``https://host:443`` are one origin, not two.

    Comparing the port as httpx reports it would make this a refusal, and a
    real service would break over a spelling difference.
    """
    recorded = transport(DEFAULT_PORT)
    async with make_safe_client(credential_header="X-API-Key") as client:
        response = await client.get(FIRST, headers={"X-API-Key": CREDENTIAL})

    assert response.status_code == 200
    assert len(recorded) == 2


@pytest.mark.anyio
async def test_cross_origin_redirect_without_the_credential_still_follows(transport):
    """The refusal is about the credential, not about crossing origins."""
    recorded = transport(CROSS_ORIGIN)
    async with make_safe_client(credential_header="X-API-Key") as client:
        response = await client.get(FIRST)

    assert response.status_code == 200
    assert len(recorded) == 2


@pytest.mark.anyio
async def test_a_caller_declaring_nothing_is_unchanged(transport):
    """Every call site that exists today passes no credential_header."""
    recorded = transport(CROSS_ORIGIN)
    async with make_safe_client() as client:
        response = await client.get(FIRST, headers={"X-API-Key": CREDENTIAL})

    assert response.status_code == 200
    assert len(recorded) == 2


@pytest.mark.anyio
async def test_x_esri_authorization_is_refused_without_being_declared(transport):
    """That name is a credential by definition, so it needs no declaration."""
    recorded = transport(CROSS_ORIGIN)
    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get(FIRST, headers={"X-Esri-Authorization": CREDENTIAL})
    assert len(recorded) == 1


@pytest.mark.anyio
async def test_httpx_still_strips_authorization_across_origins(transport):
    """The pin. ``Authorization`` is handled by httpx, not by this module.

    Nothing in GeoLens refuses a cross-origin redirect carrying
    ``Authorization``, because httpx drops the header itself. If an httpx bump
    ever stopped doing that, the bearer token would start following redirects
    off-origin and nothing else in the tree would notice.
    """
    recorded = transport(CROSS_ORIGIN)
    async with make_safe_client() as client:
        response = await client.get(
            FIRST, headers={"Authorization": f"Bearer {CREDENTIAL}"}
        )

    assert response.status_code == 200
    assert len(recorded) == 2
    assert recorded[0].headers.get("Authorization") == f"Bearer {CREDENTIAL}"
    assert "authorization" not in recorded[1].headers


@pytest.mark.anyio
async def test_a_response_that_is_not_a_redirect_is_never_judged(transport):
    """No hop, nothing to refuse."""
    recorded = transport(None)
    async with make_safe_client(credential_header="X-API-Key") as client:
        response = await client.get(FIRST, headers={"X-API-Key": CREDENTIAL})

    assert response.status_code == 200
    assert len(recorded) == 1
