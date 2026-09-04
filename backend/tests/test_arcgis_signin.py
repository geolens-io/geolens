"""Tests for POST /services/arcgis/signin/, the ArcGIS username-and-password door.

The endpoint sends a password to a third party on an authenticated user's
say-so, so most of what is pinned here is not the happy path. Four groups:

* Protocol. The discovery hop and its fallback, the mandatory
  ``client=referer`` pairing, the 60-minute expiry, the single POST that must
  never become a retry loop, and the absence of any ``token=`` query anywhere.
* The error table. Two caller-facing ArcGIS codes and no more, with the
  invalid/locked distinction surviving only in the audit row.
* The abuse controls. The ``create_layers`` gate, the per-process limits,
  the shared attempt counter and the advisory lock.
* Redaction. No password and no token in a log line, an audit row or an
  exception string.

Outbound HTTP is served by ``httpx.MockTransport`` behind a stand-in for
``make_safe_client``, so the requests the module actually builds (URL, form
body, method) are the things under test rather than a mock's call args.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import idna
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, exc as sa_exc, func, select

from app.modules.audit.models import AuditLog
from app.modules.catalog.sources.models import ArcGISSignInAttempt
from app.modules.catalog.sources import (
    arcgis_signin,
    router as sources_router,
    signin_guard,
)
from app.modules.catalog.sources.arcgis_signin import (
    ArcGISSignInError,
    DEFAULT_SIGNIN_REFERER,
    _rest_base,
    mint_portal_token,
    portal_host,
    signin_account_key,
    signin_referer,
)
from app.platform.ratelimit import limiter
from app.platform.security import (
    SSRFError,
    SSRFResolutionError,
    _revalidate_redirect,
)
from tests._logging_state import configured_logging

pytestmark = pytest.mark.anyio

SIGNIN_URL = "/services/arcgis/signin/"

# A fixed pair for the pure URL-parsing tests, which touch no database.
SAMPLE_PORTAL = "https://portal.geolens-signin-fixture.test"
SAMPLE_REST_BASE = f"{SAMPLE_PORTAL}/sharing/rest"

# One portal host per test, set by the autouse fixture below. The shared
# attempt counter reads committed audit rows keyed on (user, portal host) and
# every HTTP test here signs in as the same admin, so a fixed host would let
# one test's three successes spend the next test's budget. A fresh host per
# test needs no cleanup and no ordering, and it survives `-n 4`.
_CURRENT_PORTAL: list[str] = []

# Deliberately not password-shaped strings: Rule 3 bans a credential literal
# as an example or a test value, and these exist only to be searched for in
# log lines and audit rows.
FIXTURE_USERNAME = "signin-fixture-account"
FIXTURE_SECRET = "signin-fixture-secret-value"
FIXTURE_TOKEN = "signin-fixture-minted-token"


@pytest.fixture(autouse=True)
def _fresh_portal():
    _CURRENT_PORTAL.clear()
    _CURRENT_PORTAL.append(f"https://p{uuid.uuid4().hex}.signin-fixture.test")
    yield


def _portal() -> str:
    """This test's portal URL."""
    return _CURRENT_PORTAL[0]


def _host() -> str:
    """This test's portal host, as the audit row records it."""
    return urlsplit(_portal()).hostname


def _parent_domain() -> str:
    """This test's portal domain, which a token service may delegate within."""
    return _host().split(".", 1)[1]


def _scope(host: str | None = None, path: str = "/sharing/rest") -> str:
    """The identity the limits key on: authority plus web-adaptor path.

    fix(#1758 codex r11): a hostname is not an account store. The default is
    this test's portal answering on its own conventional endpoint.
    """
    return f"{host or _host()}:443{path}"


def _rest() -> str:
    """This test's `/sharing/rest` base."""
    return f"{_portal()}/sharing/rest"


def _body(username: str = FIXTURE_USERNAME, secret: str = FIXTURE_SECRET) -> dict:
    return {"portal_url": _portal(), "username": username, "password": secret}


class _AsyncBytes(httpx.AsyncByteStream):
    """A response body that actually streams.

    fix(#1758 codex r14): `httpx.Response(json=...)` materializes its content,
    and `aiter_raw()` on a materialized response raises `StreamConsumed`. A
    real transport streams, so the double has to as well, or it would only
    ever exercise a path production does not take. It also counts the chunks
    it handed over, which is how the cap test shows the read stops.
    """

    def __init__(self, data: bytes = b"", chunk_size: int = 65536) -> None:
        self.data = data
        self.chunk_size = chunk_size
        self.chunks_read = 0

    async def __aiter__(self):
        for start in range(0, max(len(self.data), 1), self.chunk_size):
            self.chunks_read += 1
            yield self.data[start : start + self.chunk_size]


@dataclass
class _Reply:
    """A reply DESCRIPTION, built fresh for each request.

    fix(#1758 codex r14): a streaming `httpx.Response` can be read once, so a
    route that handed the same object back twice made every attempt after the
    first look like a truncated body. The exchange now builds a new response
    per request, which is what a real transport does.
    """

    status_code: int = 200
    body: bytes = b""
    headers: dict[str, str] | None = None
    chunk_size: int = 65536
    last_stream: _AsyncBytes | None = None

    def build(self) -> httpx.Response:
        merged = {"content-type": "application/json"}
        merged.update(self.headers or {})
        self.last_stream = _AsyncBytes(self.body, self.chunk_size)
        return httpx.Response(self.status_code, headers=merged, stream=self.last_stream)


def _stream_response(
    status_code: int = 200,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    chunk_size: int = 65536,
) -> _Reply:
    return _Reply(status_code, body, headers, chunk_size)


def _json_response(payload: dict, status_code: int = 200) -> _Reply:
    return _stream_response(status_code, body=json.dumps(payload).encode())


def _info_payload(token_services_url: str | None = None) -> dict:
    payload: dict = {"currentVersion": 11.4}
    if token_services_url is not None:
        payload["authInfo"] = {
            "isTokenBasedSecurity": True,
            "tokenServicesUrl": token_services_url,
        }
    return payload


def _token_payload(expires_ms: int | None = 1_800_000_000_000) -> dict:
    payload: dict = {"token": FIXTURE_TOKEN, "ssl": True}
    if expires_ms is not None:
        payload["expires"] = expires_ms
    return payload


def _error_payload(code: int = 400, message: str = "", details=()) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": list(details),
        }
    }


class _Exchange:
    """Records every outbound request and replays canned answers."""

    def __init__(self, routes: dict[str, object]) -> None:
        # Keyed by the last path segment: "info", "generateToken", "self".
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        answer = self.routes.get(key)
        if answer is None:
            return _json_response({"error": "no route"}, 404).build()
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, _Reply):
            return answer.build()
        if callable(answer):
            return answer(request)
        return answer

    @property
    def posts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST"]

    def form(self, index: int = 0) -> dict[str, str]:
        raw = self.posts[index].content.decode()
        return {key: values[0] for key, values in parse_qs(raw).items()}


def _install(exchange: _Exchange):
    """Patch make_safe_client with a MockTransport client over *exchange*.

    ``follow_redirects`` and ``max_redirects`` mirror ``make_safe_client``
    exactly (fix(#1758 codex r2)). Without that the stand-in would default to
    NOT following, every redirect assertion below would pass whether or not
    the code sets the per-request flag, and the test would be evidence about
    httpx's default rather than about this module.
    """

    def factory(timeout=None):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(exchange.handle),
            timeout=10.0,
            follow_redirects=True,
            max_redirects=5,
        )

    return patch("app.modules.catalog.sources.arcgis_signin.make_safe_client", factory)


@pytest.fixture
def allow_ssrf():
    """Let the module's own SSRF gate pass; the transport is mocked anyway."""
    with patch(
        "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


async def _clear_unknown_host_rows(session) -> None:
    """Drop the sign-in rows audited before a destination host was known.

    fix(#1758 codex r7): every other assertion in this file is isolated by the
    per-test portal host, but a phase-one refusal happens before there is a
    host to bucket under, so those rows all land under "unknown" and would
    otherwise accumulate across tests on one worker's database.
    """
    await session.execute(
        delete(AuditLog).where(
            AuditLog.action == "arcgis_signin",
            AuditLog.details["token_service_host"].astext == "unknown",
        )
    )
    await session.commit()


async def _audit_rows(session, host: str | None = None) -> list[AuditLog]:
    """This test's sign-in audit rows, oldest first.

    Scoped to a portal host, this test's by default: the database is shared
    across every test on one xdist worker, so a query on the action alone
    would read rows the test did not write.
    """
    result = await session.execute(
        select(AuditLog)
        .where(
            AuditLog.action == "arcgis_signin",
            AuditLog.details["token_service_host"].astext == (host or _scope()),
        )
        .order_by(AuditLog.created_at)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# URL handling and the referer value
# ---------------------------------------------------------------------------


def _base_of(given: str) -> str:
    """The REST base a pasted portal reaches, through the one canonicalizer."""
    portal = arcgis_signin.usable_service_url(given)
    assert portal is not None, given
    return str(_rest_base(portal))


@pytest.mark.parametrize(
    "given",
    [
        SAMPLE_PORTAL,
        f"{SAMPLE_PORTAL}/",
        f"{SAMPLE_PORTAL}/sharing",
        f"{SAMPLE_PORTAL}/sharing/rest",
        # fix(#1758 codex r13): a dot segment in the portal is resolved by the
        # same canonicalizer the advertised URL takes, percent-encoded or not,
        # so it cannot reach the fallback as a spelling of its own.
        f"{SAMPLE_PORTAL}/a/../sharing/rest",
        f"{SAMPLE_PORTAL}/a/%2e%2e/sharing/rest",
        SAMPLE_PORTAL.replace("portal.", "PORTAL."),
        SAMPLE_PORTAL + ".",
    ],
)
def test_rest_base_normalizes_the_forms_a_user_pastes(given):
    assert _base_of(given) == SAMPLE_REST_BASE


@pytest.mark.parametrize(
    "given",
    [
        f"{SAMPLE_PORTAL}/sharing/rest/",
        f"{SAMPLE_PORTAL}/sharing/rest?f=json",
        f"{SAMPLE_PORTAL}/sharing/rest#frag",
        f"{SAMPLE_PORTAL}//sharing//rest",
        f"{SAMPLE_PORTAL}/%2Fsharing/rest",
        "https://someone:secret@portal.geolens-signin-fixture.test",
    ],
)
def test_a_portal_url_that_cannot_be_pinned_down_is_refused(given):
    """fix(#1758 codex r13): the caller's URL takes the same road, refusals
    included. It used to be stripped into shape by a parser of its own."""
    assert arcgis_signin.usable_service_url(given) is None


def test_rest_base_keeps_an_enterprise_context_path():
    assert (
        _base_of("https://gis.example.test/portal")
        == "https://gis.example.test/portal/sharing/rest"
    )


def test_rest_base_keeps_an_explicit_port():
    assert (
        _base_of("https://gis.example.test:7443/arcgis")
        == "https://gis.example.test:7443/arcgis/sharing/rest"
    )


@pytest.mark.parametrize(
    "prefix",
    ["", "/a/..", "/a/%2e%2e", "/a/b/../.."],
    ids=["plain", "dot-segment", "encoded-dot-segment", "two-levels"],
)
def test_one_canonicalizer_serves_portal_advertised_and_fallback(prefix):
    """fix(#1758 codex r13): no input has a normalization path of its own.

    One hostile spelling, fed through all three roles a URL plays here: the
    portal a caller types, the fallback composed from that portal, and the
    token service a portal advertises. All three reach one scope, because all
    three go through ``usable_service_url``. The portal used to reach the
    fallback through a separate ``urlsplit``, which resolves no
    percent-encoded dot segments, so ``/a/%2e%2e`` and ``/b/%2e%2e`` were two
    scopes for one endpoint.
    """
    expected = "gis.example.test:443/sharing/rest"

    portal = arcgis_signin.usable_service_url(f"https://gis.example.test{prefix}")
    assert portal is not None
    fallback = arcgis_signin.usable_service_url(f"{_rest_base(portal)}/generateToken")
    advertised = arcgis_signin.usable_service_url(
        f"https://gis.example.test{prefix}/sharing/rest/generateToken"
    )
    assert fallback is not None and advertised is not None

    assert arcgis_signin.canonical_token_service_scope(fallback) == expected
    assert arcgis_signin.canonical_token_service_scope(advertised) == expected


@pytest.mark.parametrize(
    "spelling",
    [
        "//sharing//rest",
        "/%2Fsharing/rest",
        "/sharing/rest?f=json",
        "/sharing/rest#frag",
    ],
)
def test_the_same_refusals_apply_to_every_role_a_url_plays(spelling):
    """A spelling refused as an advertised token service is refused as a
    portal too, because it is one function saying no in both places."""
    raw = f"https://gis.example.test{spelling}"
    assert arcgis_signin.usable_service_url(raw) is None
    assert arcgis_signin.usable_service_url(f"{raw}/generateToken") is None


def test_portal_host_is_the_hostname_and_nothing_else():
    assert portal_host("https://gis.example.test:7443/portal?f=json") == (
        "gis.example.test"
    )
    assert portal_host("not a url at all") == "unknown"


def test_signin_referer_prefers_the_public_base_url(monkeypatch):
    monkeypatch.setattr(
        arcgis_signin.settings, "public_base_url", "https://geo.example.test"
    )
    monkeypatch.setattr(
        arcgis_signin.settings, "public_app_url", "https://app.example.test"
    )
    assert signin_referer() == "https://geo.example.test"


def test_signin_referer_falls_back_to_the_app_url_then_the_constant(monkeypatch):
    monkeypatch.setattr(arcgis_signin.settings, "public_base_url", None)
    monkeypatch.setattr(
        arcgis_signin.settings, "public_app_url", "https://app.example.test"
    )
    assert signin_referer() == "https://app.example.test"

    monkeypatch.setattr(arcgis_signin.settings, "public_app_url", None)
    assert signin_referer() == DEFAULT_SIGNIN_REFERER


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


async def test_signin_returns_only_a_token_and_an_expiry(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert set(resp.json()) == {"token", "expires_at"}
    assert resp.json()["token"] == FIXTURE_TOKEN
    assert resp.json()["expires_at"].startswith("2027-")


async def test_signin_follows_the_advertised_token_service(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    # fix(#1758 codex r13): a SUBDOMAIN of the portal. A sibling under the
    # same organisation domain no longer qualifies, because that rule could
    # not be told apart from a public suffix without a suffix list.
    advertised = f"https://federated.{_host()}/arcgis/tokens/generateToken"
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload(advertised)),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == advertised
    # A different host is re-validated before it is followed.
    allow_ssrf.assert_any_await(advertised)


async def test_signin_falls_back_to_the_conventional_token_url(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    """No authInfo in the discovery document, so the default URL is used."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"


async def test_discovery_falls_back_when_the_portal_answers_a_web_page(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _stream_response(
                body=b"<html><body>Sign in</body></html>",
                headers={"content-type": "text/html"},
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"


async def test_discovery_falls_back_when_the_portal_refuses_the_info_document(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _json_response({"error": "denied"}, 403),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"


async def test_an_advertised_token_service_that_fails_ssrf_is_refused(
    client: AsyncClient, admin_auth_header: dict
):
    # fix(#1758 codex r14): a TRUSTED delegate, because an untrusted one is
    # refused before it is ever resolved. The SSRF verdict only applies to a
    # candidate the sign-in would go on to contact.
    advertised = f"https://tokens.{_host()}/generateToken"
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload(advertised)),
            "generateToken": _json_response(_token_payload()),
        }
    )

    async def _gate(url: str) -> None:
        if url != _portal():
            raise SSRFError("URLs targeting private/internal networks are not allowed")

    with patch(
        "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
        new_callable=AsyncMock,
        side_effect=_gate,
    ):
        with _install(exchange):
            resp = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "ssrf_refused"
    assert exchange.posts == []


async def test_the_form_body_carries_the_mandatory_referer_pairing(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, monkeypatch
):
    monkeypatch.setattr(
        arcgis_signin.settings, "public_base_url", "https://geo.example.test"
    )
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    form = exchange.form()
    assert form["client"] == "referer"
    assert form["referer"] == "https://geo.example.test"
    assert form["expiration"] == "60"
    assert form["f"] == "json"
    assert form["username"] == FIXTURE_USERNAME
    assert form["password"] == FIXTURE_SECRET


async def test_no_data_request_carries_a_referer_header(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    """The form field and the request header are independent, and only the
    form field is wanted. A Referer header on an outbound ArcGIS request is a
    standing prohibition, so pin its absence rather than assume it."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    for request in exchange.requests:
        assert "referer" not in {name.lower() for name in request.headers}


async def test_no_request_url_ever_carries_a_token_query_parameter(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    for request in exchange.requests:
        assert "token=" not in str(request.url)
        assert FIXTURE_SECRET not in str(request.url)


async def test_a_missing_expiry_defaults_to_sixty_minutes(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload(expires_ms=None)),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    from datetime import UTC, datetime

    expires_at = datetime.fromisoformat(resp.json()["expires_at"])
    minutes = (expires_at - datetime.now(tz=UTC)).total_seconds() / 60
    assert 55 <= minutes <= 60


@pytest.mark.parametrize(
    ("status_code", "location"),
    [
        (307, "http://tokens.example.test/generateToken"),
        (308, "https://elsewhere.example.test/generateToken"),
        (302, "https://elsewhere.example.test/generateToken"),
    ],
)
async def test_a_redirect_on_the_credential_post_is_never_followed(
    client: AsyncClient,
    admin_auth_header: dict,
    allow_ssrf,
    test_db_session,
    status_code,
    location,
):
    """fix(#1758 codex r2): httpx replays a form body on 307 and 308.

    The redirect target is chosen by the response, so following one resends
    the username and password to whatever it names, an http address or
    another public origin included, and the per-hop SSRF hook clears both
    because neither is private. The POST therefore goes out with redirects
    disabled and any 3xx is a refusal.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _stream_response(
                status_code, headers={"Location": location}
            ),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"
    # The whole point: exactly one POST, and nothing addressed to the target.
    assert len(exchange.posts) == 1
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"
    assert all(location not in str(request.url) for request in exchange.requests)

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["token_service_redirect"]


async def test_a_redirect_the_ssrf_hook_refuses_still_spends_the_budget(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1758 codex r4): the per-hop SSRF hook runs on every response.

    A 3xx whose Location is private raises SSRFError out of the hook before
    the redirect branch can read the status, and the outer handler recorded
    `ssrf_blocked`, which the budget excludes on the grounds that nothing
    reached ArcGIS. On this one request that is false: the password was
    already on the wire. This test installs the REAL hook rather than the
    plain stand-in, so the exception comes from production code.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _stream_response(
                307, headers={"Location": "http://10.0.0.9/generateToken"}
            ),
        }
    )

    def factory(timeout=None):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(exchange.handle),
            timeout=10.0,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"response": [_revalidate_redirect]},
        )

    with patch("app.modules.catalog.sources.arcgis_signin.make_safe_client", factory):
        statuses = [
            (
                await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)
            ).status_code
            for _ in range(4)
        ]

    # Three refusals that each spent an attempt, then the budget refusing.
    assert statuses == [502, 502, 502, 429]
    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == [
        "token_service_redirect",
        "token_service_redirect",
        "token_service_redirect",
        "rate_limited",
    ]
    assert "token_service_redirect" not in arcgis_signin.UNCOUNTED_SIGNIN_RESULTS


@pytest.mark.parametrize(
    "location",
    [
        "http://portal.example.test/sharing/rest/info?f=json",
        "https://portal.example.test/sharing/rest/portalinfo?f=json",
    ],
    ids=["to-http", "to-https-elsewhere"],
)
async def test_a_discovery_redirect_is_never_followed(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, location
):
    """fix(#1758 codex r9): the discovery document decides where the password
    goes, so a redirect on it is a way to rewrite that decision.

    An https-to-http hop hands the document to anyone on the path, and the
    rewritten document names an attacker's https token service that passes
    every later check. Not following at all is stricter and simpler than
    judging each hop, and it costs only a fallback to the conventional
    endpoint on the portal origin that was already validated.
    """
    exchange = _Exchange(
        {
            "info": _stream_response(302, headers={"Location": location}),
            "portalinfo": _json_response(
                _info_payload("https://attacker.example.test/generateToken")
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    # One GET, not two: the Location was never fetched.
    gets = [str(r.url) for r in exchange.requests if r.method == "GET"]
    assert gets == [f"{_rest()}/info?f=json"]
    # And the password went to the conventional endpoint on the portal.
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"


async def test_a_token_service_on_an_unrelated_host_is_not_followed(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1758 codex r9): tokenServicesUrl was followed to any host that
    passed https and SSRF, which made the discovery document a way to redirect
    a credential to an attacker's own server."""
    exchange = _Exchange(
        {
            "info": _json_response(
                _info_payload("https://unrelated.example.test/generateToken")
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"
    assert all(
        "unrelated.example.test" not in str(request.url)
        for request in exchange.requests
    )

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["success"]
    assert rows[0].details["discovery_note"] == "discovery_untrusted_delegate"


@pytest.mark.parametrize(
    ("portal", "delegate", "trusted"),
    [
        # ArcGIS Online delegates to www.arcgis.com from an org host.
        ("myorg.maps.arcgis.com", "www.arcgis.com", True),
        ("myorg.maps.arcgis.com", "myorg.maps.arcgis.com", True),
        # A subdomain of the portal is the only other delegation left.
        ("gis.example.test", "tokens.gis.example.test", True),
        ("gis.example.test", "gis.example.test", True),
        # fix(#1758 codex r13): siblings are gone, and this is why. "Host
        # minus its leftmost label" is the organisation domain only when the
        # portal sits exactly one label above its public suffix; for
        # agency.co.uk it is co.uk, and attacker.co.uk read as a sibling.
        ("agency.co.uk", "attacker.co.uk", False),
        ("gis.agency.co.uk", "server.agency.co.uk", False),
        ("gis.example.test", "gisserver.example.test", False),
        ("gis.example.test", "example.test", False),
        ("gis.example.test", "evil.test", False),
        ("gis.example.test", "example.test.evil.test", False),
        # A suffix match is not a subdomain match.
        ("gis.example.test", "evilgis.example.test", False),
        # An IP literal delegates only to itself.
        ("198.51.100.9", "198.51.100.9", True),
        ("198.51.100.9", "198.51.100.10", False),
    ],
)
def test_the_delegate_bound_matches_the_federations_that_exist(
    portal, delegate, trusted
):
    assert arcgis_signin._is_trusted_delegate(portal, delegate) is trusted


async def test_a_stalling_resolver_is_cut_by_the_deadline(
    client: AsyncClient, admin_auth_header: dict, monkeypatch, test_db_session
):
    """fix(#1758 codex r2): the SSRF validation resolves DNS, and the resolver
    is outside every httpx phase timeout, so it has to sit inside the sign-in
    deadline rather than ahead of it. The caller holds a request transaction
    and the advisory-lock session for the whole call."""
    await _clear_unknown_host_rows(test_db_session)
    ledger_before = await test_db_session.scalar(
        select(func.count()).select_from(ArcGISSignInAttempt)
    )
    monkeypatch.setattr(arcgis_signin, "_DISCOVERY_DEADLINE_SECONDS", 0.2)

    async def _hang(_url: str) -> None:
        await asyncio.sleep(30)

    exchange = _Exchange({})
    with patch(
        "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
        new_callable=AsyncMock,
        side_effect=_hang,
    ):
        with _install(exchange):
            resp = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )

    assert resp.status_code == 504
    assert resp.json()["detail"]["code"] == "network_error"
    assert exchange.requests == []
    # fix(#1758 codex r7): discovery has its own outcomes, because nothing was
    # sent and an unreachable portal must not spend a real account's budget.
    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["discovery_timeout"]
    # fix(#1758 codex r8): and it is uncounted, so the ledger never moved.
    assert (
        await test_db_session.scalar(
            select(func.count()).select_from(ArcGISSignInAttempt)
        )
        == ledger_before
    )


async def test_a_post_cancelled_by_the_deadline_spends_the_resolved_budget(
    client: AsyncClient,
    admin_auth_header: dict,
    allow_ssrf,
    test_db_session,
    monkeypatch,
):
    """fix(#1758 codex r8): a cut-short POST still spent an attempt.

    Discovery resolves, the credential POST goes out, and a portal that drips
    slowly enough eats the rest of the deadline. `asyncio.timeout` converts
    that cancellation at the CONTEXT boundary rather than where it fired, so
    it unwinds past the mint's own handler and past the locks. Charged to the
    synthetic `unknown` bucket, as it was, the resolved account's ledger
    stayed empty and a caller could repeat credential POSTs against a real
    ArcGIS account forever without ever spending the cluster-global budget.
    """
    await _clear_unknown_host_rows(test_db_session)
    monkeypatch.setattr(arcgis_signin, "_MINT_DEADLINE_SECONDS", 0.3)
    token_service_host = f"tokens{uuid.uuid4().hex[:8]}.{_host()}"
    advertised = f"https://{token_service_host}/arcgis/tokens/generateToken"
    posts: list[httpx.Request] = []

    async def _slow_token_service(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json_response(_info_payload(advertised)).build()
        posts.append(request)
        # Longer than the deadline: the request is on the wire and then cut.
        await asyncio.sleep(5)
        return _json_response(_token_payload())

    def factory(timeout=None):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_slow_token_service),
            timeout=10.0,
            follow_redirects=True,
            max_redirects=5,
        )

    with patch("app.modules.catalog.sources.arcgis_signin.make_safe_client", factory):
        statuses = [
            (
                await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)
            ).status_code
            for _ in range(4)
        ]

    # Three cut-short attempts, each of which put a password on the wire, then
    # the budget refusing the fourth.
    assert statuses == [504, 504, 504, 429]
    assert len(posts) == 3

    account_key = signin_account_key(
        _scope(token_service_host, "/arcgis/tokens"), FIXTURE_USERNAME
    )
    rows = await _audit_rows(
        test_db_session, host=_scope(token_service_host, "/arcgis/tokens")
    )
    assert [row.details["result"] for row in rows] == [
        "timeout",
        "timeout",
        "timeout",
        "rate_limited",
    ]
    assert {row.details["account_key"] for row in rows} == {account_key}
    # And the ledger, which is what the cluster-global budget reads.
    ledger = await test_db_session.scalar(
        select(func.count())
        .select_from(ArcGISSignInAttempt)
        .where(ArcGISSignInAttempt.account_key == account_key)
    )
    assert ledger == 3
    # Nothing was charged to the synthetic bucket.
    assert await _audit_rows(test_db_session, host="unknown") == []


async def test_the_deadline_does_not_cover_the_durable_bookkeeping(
    client: AsyncClient,
    admin_auth_header: dict,
    allow_ssrf,
    test_db_session,
    monkeypatch,
):
    """fix(#1758 codex r11): the ledger insert and the commit are not cancellable.

    A single scope around both phases also covered the caller's bookkeeping
    between them. A cancellation landing in the flush, the sweep or the commit
    leaves the request session in a failed transaction, the refusal path then
    runs on an unusable session and 500s, and the row saying a credential POST
    went out is never written. Here the sweep takes far longer than either
    deadline: the sign-in must still return 200 with its ledger row, because
    nothing after the network phases is inside a cancellation scope.
    """
    monkeypatch.setattr(arcgis_signin, "_DISCOVERY_DEADLINE_SECONDS", 0.3)
    monkeypatch.setattr(arcgis_signin, "_MINT_DEADLINE_SECONDS", 0.3)

    real_sweep = signin_guard._sweep_expired_signin_attempts

    async def _slow_sweep(db):
        await asyncio.sleep(0.9)
        await real_sweep(db)

    monkeypatch.setattr(signin_guard, "_sweep_expired_signin_attempts", _slow_sweep)

    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["success"]
    ledger = await test_db_session.scalar(
        select(func.count())
        .select_from(ArcGISSignInAttempt)
        .where(
            ArcGISSignInAttempt.account_key
            == signin_account_key(_scope(), FIXTURE_USERNAME)
        )
    )
    assert ledger == 1


async def test_a_refusal_rolls_back_a_failed_session_and_still_records(
    client: AsyncClient,
    admin_auth_header: dict,
    allow_ssrf,
    test_db_session,
    monkeypatch,
):
    """fix(#1758 codex r11): a broken session must not swallow the outcome.

    Whatever leaves the request transaction failed, the refusal still has to
    land: the row is what says a credential POST went out, and without it the
    budget is never spent. The first audit attempt is made to fail the way a
    poisoned transaction fails; the refusal must roll back and write anyway,
    and the caller must still see the classified 400 rather than a 500.
    """
    real_audit = signin_guard._signin_audit
    calls = 0

    async def _fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sa_exc.PendingRollbackError("this transaction is closed")
        await real_audit(*args, **kwargs)

    monkeypatch.setattr(signin_guard, "_signin_audit", _fail_once)

    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(400, "Unable to generate token.")
            ),
            "self": _json_response({"canSignInArcGIS": True}),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "arcgis_signin_rejected"
    assert calls == 2, "the refusal must retry after rolling back"
    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["invalid_credentials"]


@pytest.mark.parametrize(
    ("first", "second", "why"),
    [
        (
            "https://gis.example.test:443/portal",
            "https://gis.example.test:8443/portal",
            "different https ports are different installations",
        ),
        (
            "https://gis.example.test/portal",
            "https://gis.example.test/portal2",
            "different web adaptors are different installations",
        ),
    ],
    ids=["ports", "web-adaptors"],
)
def test_one_hostname_can_carry_two_account_stores(first, second, why):
    """fix(#1758 codex r11): keyed on the host alone, three attempts against
    one Enterprise portal exhausted and serialized its neighbour."""
    assert arcgis_signin.canonical_token_service_scope(
        f"{first}/sharing/rest/generateToken"
    ) != arcgis_signin.canonical_token_service_scope(
        f"{second}/sharing/rest/generateToken"
    ), why


@pytest.mark.parametrize(
    ("url", "scope"),
    [
        # The scheme-implied port is filled in, so these are one scope.
        (
            "https://gis.example.test/sharing/rest/generateToken",
            "gis.example.test:443/sharing/rest",
        ),
        (
            "https://gis.example.test:443/sharing/rest/generateToken",
            "gis.example.test:443/sharing/rest",
        ),
        # Web-adaptor case is preserved: the server that serves it cares.
        (
            "https://gis.example.test/Portal/sharing/rest/generateToken",
            "gis.example.test:443/Portal/sharing/rest",
        ),
        # The host half still canonicalizes.
        (
            "https://GIS.example.test./sharing/rest/generateToken",
            "gis.example.test:443/sharing/rest",
        ),
        # AGOL is unchanged by any of this.
        (
            "https://www.arcgis.com/sharing/rest/generateToken",
            "www.arcgis.com:443/sharing/rest",
        ),
    ],
)
def test_the_scope_is_the_authority_and_the_web_adaptor_path(url, scope):
    assert arcgis_signin.canonical_token_service_scope(url) == scope


@pytest.mark.parametrize(
    "advertised_path",
    ["/a/../sharing/rest", "/b/../sharing/rest", "/sharing/rest"],
    ids=["dot-a", "dot-b", "plain"],
)
async def test_dot_segments_do_not_buy_a_fresh_budget(
    client: AsyncClient,
    admin_auth_header: dict,
    allow_ssrf,
    test_db_session,
    advertised_path,
):
    """fix(#1758 codex r12): urlsplit kept `/a/../`, httpx removed it.

    So the scope was derived from a spelling the request never used, and a
    caller controlling the portal could rotate `/a/../`, `/b/../`, ... to
    collect a fresh account key, lock and ledger bucket per spelling while
    every POST landed on one ArcGIS account. All three spellings must be one
    scope, and the POST must go where the scope says.
    """
    advertised = f"https://{_host()}{advertised_path}/generateToken"
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload(advertised)),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    # One scope for every spelling, and it is the normalized one.
    rows = await _audit_rows(test_db_session, host=_scope())
    assert [row.details["result"] for row in rows] == ["success"]
    assert rows[0].details["account_key"] == signin_account_key(
        _scope(), FIXTURE_USERNAME
    )
    # And the destination agrees with the scope, which is the whole point of
    # deriving both from one httpx.URL.
    posted = exchange.posts[0].url
    assert f"{posted.host}:{posted.port or 443}{posted.path}" == (
        f"{_scope()}/generateToken"
    )


@pytest.mark.parametrize(
    "advertised_path",
    ["//sharing//rest", "/%2Fsharing/rest"],
    ids=["empty-segments", "encoded-slash"],
)
async def test_a_url_that_still_argues_with_itself_falls_back(
    client: AsyncClient,
    admin_auth_header: dict,
    allow_ssrf,
    test_db_session,
    advertised_path,
):
    """Refused rather than repaired, and the fallback lands on one scope.

    An empty segment survives httpx's normalization and `%2F` decodes into
    one, so both are URLs whose scope and whose destination could still be
    argued about. The conventional endpoint is always available instead, and
    it is the same scope every other spelling reaches.
    """
    advertised = f"https://{_host()}{advertised_path}/generateToken"
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload(advertised)),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"
    rows = await _audit_rows(test_db_session, host=_scope())
    assert [row.details["result"] for row in rows] == ["success"]


@pytest.mark.parametrize("suffix", ["?f=json", "#frag"], ids=["query", "fragment"])
async def test_a_token_service_with_a_query_or_fragment_falls_back(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, suffix
):
    exchange = _Exchange(
        {
            "info": _json_response(
                _info_payload(f"https://{_host()}/other/rest/generateToken{suffix}")
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"


@pytest.mark.parametrize(
    "raw",
    [
        "https://gis.example.test/a/../sharing/rest/generateToken",
        "https://gis.example.test/b/../sharing/rest/generateToken",
        "https://gis.example.test/sharing/rest/generateToken",
        "https://GIS.Example.TEST/sharing/rest/generateToken",
        "HTTPS://gis.example.test/sharing/rest/generateToken",
        "https://gis.example.test./sharing/rest/generateToken",
        "https://gis.example.test:443/sharing/rest/generateToken",
        # RFC 3986 drops `..` that would climb past the root, so this is
        # unambiguous rather than unusable.
        "https://gis.example.test/a/../../sharing/rest/generateToken",
    ],
)
def test_every_spelling_of_one_destination_is_one_scope(raw):
    assert (
        arcgis_signin.canonical_token_service_scope(raw)
        == "gis.example.test:443/sharing/rest"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "https://gis.example.test//sharing//rest/generateToken",
        "https://gis.example.test/%2Fsharing/rest/generateToken",
        "https://gis.example.test/sharing/rest/generateToken?f=json",
        "https://gis.example.test/sharing/rest/generateToken#frag",
    ],
)
def test_a_url_that_cannot_be_pinned_down_is_refused(raw):
    assert arcgis_signin.usable_service_url(raw) is None


@pytest.mark.parametrize("encoding", ["gzip", "br", "zstd", "GZIP"])
async def test_a_compressed_body_is_refused_without_decoding(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, encoding
):
    """fix(#1758 codex r14): a decompression bomb never reaches a decoder.

    `aiter_bytes()` decodes each transport chunk BEFORE yielding it, so a few
    kilobytes of gzip becomes hundreds of megabytes inside the decoder before
    any cap on the output can look at it. Both requests now ask for
    `identity`, and a portal that answers with a content-encoding anyway is
    refused unread.

    The body here is perfectly good JSON that merely CLAIMS to be compressed:
    if the check were absent the sign-in would succeed with a token, so a 502
    is proof the body was never taken at its word.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _stream_response(
                body=json.dumps(_token_payload()).encode(),
                headers={"content-encoding": encoding},
            ),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"
    # And the request said so up front, on both hops.
    assert [r.headers.get("accept-encoding") for r in exchange.requests] == [
        "identity",
        "identity",
    ]


async def test_an_oversized_body_stops_at_the_cap(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, monkeypatch
):
    """The cap bounds RAW transport bytes, and the read stops at it.

    fix(#1758 codex r14): counted in chunks the double actually handed over,
    which is the only way to show the body was not drained. One chunk past
    the cap is inherent to append-then-check; a hundred would mean the cap
    was decorative.
    """
    monkeypatch.setattr(arcgis_signin, "_MAX_RESPONSE_BYTES", 4096)
    chunk_size = 1024
    oversized = _stream_response(body=b"x" * (chunk_size * 200), chunk_size=chunk_size)
    exchange = _Exchange(
        {"info": _json_response(_info_payload()), "generateToken": oversized}
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"
    # 4096 / 1024 = 4 chunks to reach the cap, and at most one more to cross
    # it. Nothing like the 200 the portal offered.
    assert oversized.last_stream is not None
    assert oversized.last_stream.chunks_read <= 5


async def test_an_untrusted_delegate_that_cannot_resolve_still_falls_back(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#1758 codex r14): the delegate check runs before the resolver.

    An untrusted sibling that is private, split-horizon or simply
    unresolvable used to turn a configuration that would fall back cleanly
    into `ssrf_refused` or a discovery network error, because
    `validate_url_for_ssrf` resolved a candidate this instance was never
    going to contact. Only the fallback is resolved here, and it signs in.
    """
    unrelated = "tokens.unrelated-example.test"

    async def _gate(url: str) -> None:
        if unrelated in url:
            raise SSRFResolutionError(f"Could not resolve hostname: {unrelated}")

    exchange = _Exchange(
        {
            "info": _json_response(
                _info_payload(f"https://{unrelated}/arcgis/generateToken")
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with patch(
        "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
        new_callable=AsyncMock,
        side_effect=_gate,
    ):
        with _install(exchange):
            resp = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )

    assert resp.status_code == 200
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"
    assert all(unrelated not in str(r.url) for r in exchange.requests)

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["success"]
    assert rows[0].details["discovery_note"] == "discovery_untrusted_delegate"


async def test_port_zero_is_refused_before_any_budget_is_spent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#1758 codex r15): port zero must not spend the real port's budget.

    Nothing can be reached on port zero, so a sign-in aimed at it fails
    without ArcGIS ever hearing about it. But zero is FALSEY, and the scope
    derivation read that as "no port given", so those failures were filed
    under the victim's real :443 bucket: three of them against a known
    username spent that account's cluster-global budget and returned 429 to
    legitimate sign-ins in every tenant.

    No `allow_ssrf` here on purpose: the refusal has to land before anything
    resolves, let alone connects.
    """
    await _clear_unknown_host_rows(test_db_session)
    ledger_before = await test_db_session.scalar(
        select(func.count()).select_from(ArcGISSignInAttempt)
    )
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        statuses = [
            (
                await client.post(
                    SIGNIN_URL,
                    json={
                        "portal_url": f"https://{_host()}:0",
                        "username": FIXTURE_USERNAME,
                        "password": FIXTURE_SECRET,
                    },
                    headers=admin_auth_header,
                )
            ).status_code
            for _ in range(3)
        ]

    assert statuses == [422, 422, 422]
    assert exchange.requests == []
    # The victim's real scope is untouched: no ledger row, no audit row.
    assert (
        await test_db_session.scalar(
            select(func.count()).select_from(ArcGISSignInAttempt)
        )
        == ledger_before
    )
    assert await _audit_rows(test_db_session) == []
    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["portal_host_invalid"] * 3


def test_port_zero_never_aliases_the_scheme_default():
    """The scope half of the same fix, isolated from the refusal half.

    `:443` and an omitted port are one scope, because httpx drops the default
    port and there is genuinely one destination. `:0` is a third thing and
    must never collapse into either.
    """
    explicit = arcgis_signin.canonical_token_service_scope(
        "https://gis.example.test:443/sharing/rest/generateToken"
    )
    implied = arcgis_signin.canonical_token_service_scope(
        "https://gis.example.test/sharing/rest/generateToken"
    )
    zero = arcgis_signin.canonical_token_service_scope(
        "https://gis.example.test:0/sharing/rest/generateToken"
    )

    assert explicit == implied == "gis.example.test:443/sharing/rest"
    assert zero == "gis.example.test:0/sharing/rest"
    assert len({explicit, implied, zero}) == 2
    # And the canonicalizer refuses it outright, so nothing reaches the scope
    # derivation with a zero port in the first place.
    assert (
        arcgis_signin.usable_service_url(
            "https://gis.example.test:0/sharing/rest/generateToken"
        )
        is None
    )


async def test_a_discovery_redirect_the_ssrf_hook_rejects_falls_back(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1758 codex r16): a rejected discovery hop is a fallback, not a refusal.

    `make_safe_client`'s `_revalidate_redirect` hook runs on EVERY response,
    whether or not redirects are followed, so a 3xx on `/info` whose Location
    is private raises `SSRFError` out of the request before the status can be
    read. Caught only as `httpx.HTTPError`, that escaped as `ssrf_refused`
    for a portal that is merely misconfigured, when discovery had simply
    turned up nothing usable.

    The real hook is installed here rather than the plain stand-in, so the
    exception comes from production code. Its sibling,
    `test_a_redirect_the_ssrf_hook_refuses_still_spends_the_budget`, pins the
    other half: the same rejection on the credential POST still refuses and
    still spends the budget, because by then the password is on the wire.
    """
    exchange = _Exchange(
        {
            "info": _stream_response(
                302, headers={"Location": "http://10.0.0.9/sharing/rest/info"}
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )

    def factory(timeout=None):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(exchange.handle),
            timeout=10.0,
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"response": [_revalidate_redirect]},
        )

    with patch("app.modules.catalog.sources.arcgis_signin.make_safe_client", factory):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 200
    # Straight to the conventional endpoint, and the Location was never fetched.
    assert str(exchange.posts[0].url) == f"{_rest()}/generateToken"
    assert all("10.0.0.9" not in str(request.url) for request in exchange.requests)

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["success"]
    assert "ssrf_blocked" not in {row.details["result"] for row in rows}


def _nested_dot_segment(depth: int) -> str:
    """`..` percent-encoded *depth* times over."""
    segment = ".."
    for _ in range(depth):
        if "%" in segment:
            segment = segment.replace("%", "%25")
        else:
            segment = segment.replace(".", "%2e")
    return segment


@pytest.mark.parametrize("depth", [1, 2, 3, 4, 10, 20])
def test_nested_encodings_normalize_to_one_scope(depth):
    """fix(#1758 codex r17): decode to a fixed point, not for four passes.

    Each pass peels one layer, so a path encoded ten deep still held `%2e%2e`
    when the old ceiling ran out. That passed every check and went on the wire
    as `%252e%252e`, which a reverse proxy and the ArcGIS application then
    decoded back into `..` between them, so `/a/` and `/b/` variants reached
    one endpoint under two scopes and two budgets.
    """
    segment = _nested_dot_segment(depth)
    scopes = {
        arcgis_signin.canonical_token_service_scope(
            f"https://gis.example.test/{prefix}/{segment}/sharing/rest/generateToken"
        )
        for prefix in ("a", "b")
    }
    assert scopes == {"gis.example.test:443/sharing/rest"}


@pytest.mark.parametrize(
    "raw",
    [
        # A separator this module could not resolve and a decoder still might.
        "https://gis.example.test/%2fsharing/rest/generateToken",
        "https://gis.example.test/%5csharing/rest/generateToken",
        # A percent sign that is not a complete escape: two parsers will
        # disagree about it.
        "https://gis.example.test/shar%zzing/rest/generateToken",
        "https://gis.example.test/sharing%/rest/generateToken",
    ],
)
def test_an_unresolved_separator_is_refused_rather_than_guessed_at(raw):
    assert arcgis_signin.usable_service_url(raw) is None


async def test_a_refusal_is_never_retried(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    """One POST and only one. A retry loop here locks a real ArcGIS account."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(400, "Unable to generate token.")
            ),
            "self": _json_response({"canSignInArcGIS": True}),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 400
    assert len(exchange.posts) == 1


# ---------------------------------------------------------------------------
# The error table
# ---------------------------------------------------------------------------


async def test_a_rejected_signin_maps_to_one_collapsed_code(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(400, "Unable to generate token.", ["Invalid username."])
            ),
            "self": _json_response({"canSignInArcGIS": True}),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "arcgis_signin_rejected"
    assert detail["field"] == "credential"
    assert "capitalisation" in detail["message"]

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["invalid_credentials"]


async def test_a_locked_account_is_collapsed_for_the_caller_and_kept_in_the_audit(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """The caller sees the same message. Only the operator sees which it was."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(
                    400,
                    "Unable to generate token.",
                    ["This account has been locked after too many attempts."],
                )
            ),
            "self": _json_response({"canSignInArcGIS": True}),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "arcgis_signin_rejected"

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["account_locked"]


@pytest.mark.parametrize(
    "detail_text",
    [
        "This user signs in with SAML.",
        "Enterprise login is required for this organisation.",
        "Multifactor authentication is enabled for this account.",
        "Sign in through your identity provider.",
    ],
)
async def test_a_federated_refusal_maps_to_the_sso_code(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, detail_text
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(400, "Unable to generate token.", [detail_text])
            ),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "arcgis_sso_account"
    assert "Paste a token or API key instead." in detail["message"]
    # The provider's own sentence never reaches the caller.
    assert detail_text not in json.dumps(resp.json())


async def test_an_org_that_disables_builtin_signin_maps_to_the_sso_code(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(400, "Unable to generate token.")
            ),
            "self": _json_response({"canSignInArcGIS": False}),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "arcgis_sso_account"
    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["sso_account"]


async def test_a_cleartext_portal_is_refused_before_anything_is_sent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#1758 codex r1): a password must never go out over http.

    Refused before the SSRF check as well as before the POST, so a cleartext
    portal URL does not even cost a DNS lookup. No `allow_ssrf` here on
    purpose: the refusal has to land without the SSRF gate being reached.
    """
    await _clear_unknown_host_rows(test_db_session)
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(
            SIGNIN_URL,
            json={
                "portal_url": _portal().replace("https://", "http://", 1),
                "username": FIXTURE_USERNAME,
                "password": FIXTURE_SECRET,
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "arcgis_portal_not_https"
    assert detail["field"] == "url"
    assert "https" in detail["message"]
    assert exchange.requests == []

    # Phase one, so there is no destination host to bucket it under.
    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["portal_not_https"]


async def test_a_cleartext_token_service_is_refused_after_discovery(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """An https portal that names an http token service gets no password."""
    await _clear_unknown_host_rows(test_db_session)
    exchange = _Exchange(
        {
            "info": _json_response(
                # A TRUSTED delegate over http: an untrusted one never gets
                # as far as being judged on its scheme.
                _info_payload(f"http://tokens.{_host()}/arcgis/generateToken")
            ),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "arcgis_portal_not_https"
    # Discovery happened; the POST did not.
    assert len(exchange.requests) == 1
    assert exchange.posts == []

    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["token_service_not_https"]


async def test_a_private_portal_is_refused_by_policy(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    await _clear_unknown_host_rows(test_db_session)
    exchange = _Exchange({})
    with patch(
        "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
        new_callable=AsyncMock,
        side_effect=SSRFError(
            "URLs targeting private/internal networks are not allowed"
        ),
    ):
        with _install(exchange):
            resp = await client.post(
                SIGNIN_URL,
                json={
                    "portal_url": "https://10.0.0.9/portal",
                    "username": FIXTURE_USERNAME,
                    "password": FIXTURE_SECRET,
                },
                headers=admin_auth_header,
            )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "ssrf_refused"
    assert detail["field"] == "url"
    assert exchange.requests == []
    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["ssrf_blocked"]


async def test_a_portal_that_does_not_resolve_is_a_network_error(
    client: AsyncClient, admin_auth_header: dict
):
    with patch(
        "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
        new_callable=AsyncMock,
        side_effect=SSRFResolutionError("Could not resolve hostname"),
    ):
        with _install(_Exchange({})):
            resp = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"


async def test_an_unreachable_portal_is_a_network_error(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": httpx.ConnectError("connection refused"),
            "generateToken": httpx.ConnectError("connection refused"),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"


async def test_a_portal_that_times_out_reports_a_gateway_timeout(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": httpx.ReadTimeout("timed out"),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 504
    assert resp.json()["detail"]["code"] == "network_error"


async def test_a_sign_in_page_instead_of_an_answer_is_a_network_error(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _stream_response(
                body=b"<html>Sign in</html>", headers={"content-type": "text/html"}
            ),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"
    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["unreadable_response"]


async def test_an_oversized_answer_is_not_read_to_the_end(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, monkeypatch
):
    monkeypatch.setattr(arcgis_signin, "_MAX_RESPONSE_BYTES", 128)
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response({"token": "x" * 4096}),
        }
    )
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"


# ---------------------------------------------------------------------------
# The abuse controls
# ---------------------------------------------------------------------------


async def test_signin_requires_authentication(client: AsyncClient):
    resp = await client.post(SIGNIN_URL, json=_body())
    assert resp.status_code == 401


async def test_signin_requires_create_layers(
    client: AsyncClient, viewer_auth_header: dict
):
    """The same permission probe_service_url requires; a viewer has no reason
    to reach a door that spends a third party's lockout budget."""
    resp = await client.post(SIGNIN_URL, json=_body(), headers=viewer_auth_header)
    assert resp.status_code == 403


async def test_a_viewer_never_reaches_the_portal(
    client: AsyncClient, viewer_auth_header: dict, allow_ssrf
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        await client.post(SIGNIN_URL, json=_body(), headers=viewer_auth_header)
    assert exchange.requests == []


def test_the_two_rate_limit_keys_are_distinct_and_carry_what_they_claim():
    class _State:
        arcgis_signin_user_id = "11111111-1111-1111-1111-111111111111"
        arcgis_signin_portal_host = "portal.example.test"

    class _Request:
        state = _State()
        client = None
        headers: dict = {}

    request = _Request()
    assert sources_router._signin_user_key(request) == (
        "user:11111111-1111-1111-1111-111111111111"
    )
    assert sources_router._signin_portal_key(request) == (
        "user:11111111-1111-1111-1111-111111111111:portal:portal.example.test"
    )


def test_both_limits_are_below_the_five_that_locks_an_arcgis_account():
    for value in (
        sources_router._ARCGIS_SIGNIN_USER_LIMIT,
        sources_router._ARCGIS_SIGNIN_PORTAL_LIMIT,
    ):
        assert value == "3/15minutes"


async def test_the_per_process_limiter_refuses_the_fourth_attempt_and_resets(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, monkeypatch
):
    """The cheap first layer, on its own.

    The shared counter is raised out of the way so the refusal can only be
    SlowAPI's, and resetting its storage is the only way to move a fifteen
    minute window inside a test.
    """
    monkeypatch.setattr(signin_guard, "_ARCGIS_SIGNIN_ATTEMPT_LIMIT", 100)
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    limiter.enabled = True
    limiter._storage.reset()
    try:
        with _install(exchange):
            statuses = [
                (
                    await client.post(
                        SIGNIN_URL, json=_body(), headers=admin_auth_header
                    )
                ).status_code
                for _ in range(4)
            ]
            assert statuses == [200, 200, 200, 429]
            assert len(exchange.posts) == 3

            limiter._storage.reset()
            again = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )
            assert again.status_code == 200
    finally:
        limiter.enabled = False
        limiter._storage.reset()


async def test_the_per_portal_limit_binds_on_its_own(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, monkeypatch
):
    """Raise the other two numbers so only the per-portal limit can refuse.

    Both SlowAPI keys carry the user id, so at equal numbers the per-user
    limit always trips first and the per-portal one is unobservable. This is
    the test that proves it is wired at all.
    """
    monkeypatch.setattr(sources_router, "_ARCGIS_SIGNIN_USER_LIMIT", "100/15minutes")
    monkeypatch.setattr(signin_guard, "_ARCGIS_SIGNIN_ATTEMPT_LIMIT", 100)
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    limiter.enabled = True
    limiter._storage.reset()
    try:
        with _install(exchange):
            statuses = [
                (
                    await client.post(
                        SIGNIN_URL, json=_body(), headers=admin_auth_header
                    )
                ).status_code
                for _ in range(4)
            ]
    finally:
        limiter.enabled = False
        limiter._storage.reset()

    assert statuses == [200, 200, 200, 429]


async def test_the_advisory_lock_is_held_by_one_caller_at_a_time(
    client: AsyncClient, test_db_session
):
    """The lock itself, against the real database rather than a stand-in.

    fix(#1758 codex r1): a process-local set was worth nothing on a two-worker
    install, so the guard is a PostgreSQL advisory lock. A second session
    asking for the same key must be refused while the first holds it, and one
    account must not lock another.
    """
    from app.core.db import async_session

    user_scope = f"user:{uuid.uuid4()}:host:{_scope()}"
    account_scope = f"account:{signin_account_key(_scope(), FIXTURE_USERNAME)}"
    other_account = (
        f"account:{signin_account_key(_scope('other.example.test'), FIXTURE_USERNAME)}"
    )

    async def _try(session, user, account) -> bool:
        async with signin_guard._signin_locks(session, user, account) as held:
            return held

    async with async_session() as holder:
        async with signin_guard._signin_locks(
            holder, user_scope, account_scope
        ) as first:
            assert first
            # Either scope alone being held is enough to refuse, and the
            # asker is a different session, which is the only thing a
            # cross-process lock can be tested with.
            async with async_session() as other:
                assert await _try(other, user_scope, other_account) is False
            async with async_session() as other:
                assert (
                    await _try(
                        other, f"user:{uuid.uuid4()}:host:{_scope()}", account_scope
                    )
                    is False
                )
            # A different caller and a different account is a free pair.
            async with async_session() as other:
                assert await _try(
                    other, f"user:{uuid.uuid4()}:host:{_scope()}", other_account
                )

    # fix(#1758 codex r10): the holder's TRANSACTION is what held them, so
    # both are free once its session is closed and rolled back.
    async with async_session() as after:
        assert await _try(after, user_scope, account_scope)


async def test_a_signin_holds_exactly_one_pooled_connection(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    """fix(#1758 codex r10): one connection per sign-in, counted at the pool.

    A dedicated lock session cost a second connection, and it was checked out
    FIRST: thirteen concurrent sign-ins for distinct scopes could each hold a
    lock connection and then queue for a request connection the other twelve
    were holding, stalling unrelated traffic until the 30-second pool timeout.
    Both locks now ride the request's own transaction, so the count is one.

    Counted at the pool rather than at the session factory, because the
    factory is not what the pool runs out of.

    fix(#1758): counted as PEAK CONCURRENT connections, not as cumulative
    checkout events. The first version summed `checkout` and asserted 1, which
    conflated "how many connections did this request hold at once" with "how
    many times did it acquire one". Those differ whenever a connection is
    released and re-acquired in sequence, which is legitimate and does happen
    here: `_signin_audit` commits, its rollback-and-retry path on a poisoned
    transaction acquires again, and the harness has contention retries of its
    own in `_RetryingAsyncEngine` and `_acquire_test_session_with_retry`. A
    single session that commits and then runs one more statement already
    scores 2 cumulative while never holding more than one. That made the
    assertion red on a loaded runner with nothing wrong, first seen in
    merge-queue run 33648625488 on an unrelated frontend-only PR.

    Peak concurrency is the property the paragraph above actually names, and
    it is what a second lock session would break: that session held its
    connection WHILE the request held its own. Sequential re-acquisition
    cannot reach 2, so this is a sharper assertion rather than a weaker one.
    """
    from sqlalchemy import event

    import app.core.db as db_module

    live = 0
    peak = 0

    def _acquired(*_args) -> None:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)

    def _released(*_args) -> None:
        nonlocal live
        live = max(0, live - 1)

    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "checkout", _acquired)
    event.listen(sync_engine, "checkin", _released)
    try:
        with _install(exchange):
            resp = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )
    finally:
        event.remove(sync_engine, "checkout", _acquired)
        event.remove(sync_engine, "checkin", _released)

    assert resp.status_code == 200
    assert peak == 1, (
        f"a sign-in held {peak} pooled connections at once; both advisory "
        "locks must ride the request's own session"
    )


async def test_concurrent_signins_hold_no_pooled_connection_across_the_mint(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    """fix(#1775): the acceptance criterion. No connection is held across the mint.

    The test above pins ONE sign-in at a peak of one connection. This one pins
    the other half: how many of those connections are held AT ONCE, while the
    credential POSTs are in flight. Before reserve-then-settle the request
    transaction was open from `require_permission` through discovery, both
    advisory locks and the mint, for up to the 45-second network budget, so
    N concurrent sign-ins for distinct scopes held N connections for the whole
    of it and 13 of them could take a 10+3 production pool and time out
    unrelated API requests. That is what the removed `asyncio.Semaphore(4)`
    bounded rather than fixed.

    Five sign-ins, each against its own portal so each resolves its own token
    service and no two contend on a lock or a budget. Every mint blocks on one
    event; when all five are inside it the pool is sampled. Sampled at the
    POOL, not at the session factory, because the pool is what production runs
    out of, and by checkout-minus-checkin so a connection released and
    re-acquired in sequence — which reserve-then-settle does exactly once, on
    purpose — reads as one at a time rather than as two (see #1786).
    """
    from sqlalchemy import event

    import app.core.db as db_module

    signins = 5
    live = 0
    peak = 0
    in_mint = 0
    all_minting = asyncio.Event()
    finish_mints = asyncio.Event()

    def _acquired(*_args) -> None:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)

    def _released(*_args) -> None:
        nonlocal live
        live = max(0, live - 1)

    async def _blocking_mint(_self, _username, _password):
        nonlocal in_mint
        in_mint += 1
        if in_mint == signins:
            all_minting.set()
        await finish_mints.wait()
        return arcgis_signin.MintedToken(
            token=FIXTURE_TOKEN,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=60),
        )

    portals = [
        f"https://c{uuid.uuid4().hex}.signin-fixture.test" for _ in range(signins)
    ]
    exchange = _Exchange({"info": _json_response(_info_payload())})
    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "checkout", _acquired)
    event.listen(sync_engine, "checkin", _released)
    try:
        with (
            _install(exchange),
            patch.object(arcgis_signin.PortalSignIn, "mint", _blocking_mint),
        ):
            calls = [
                asyncio.create_task(
                    client.post(
                        SIGNIN_URL,
                        json={
                            "portal_url": portal,
                            "username": FIXTURE_USERNAME,
                            "password": FIXTURE_SECRET,
                        },
                        headers=admin_auth_header,
                    )
                )
                for portal in portals
            ]
            try:
                async with asyncio.timeout(30):
                    await all_minting.wait()
                # Every credential POST is on the wire and none has answered.
                held_while_minting = live
                finish_mints.set()
                responses = await asyncio.gather(*calls)
            finally:
                finish_mints.set()
                for call in calls:
                    call.cancel()
    finally:
        event.remove(sync_engine, "checkout", _acquired)
        event.remove(sync_engine, "checkin", _released)

    assert [resp.status_code for resp in responses] == [200] * signins
    assert held_while_minting == 0, (
        f"{held_while_minting} pooled connections were held while {signins} "
        "credential POSTs were in flight; the reservation must commit and "
        "give its connection back before the mint"
    )
    # The positive control: the counter was wired to a pool that was actually
    # used, so the zero above is a measurement rather than a dead listener.
    assert peak >= 1


async def test_a_signin_cancelled_mid_mint_is_already_counted(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1775): the second defect. A cancelled POST must not be a free attempt.

    `CancelledError` is not an `Exception`, so it passes straight through
    `PortalSignIn.mint`'s handler and the route's `except ArcGISSignInError`.
    Under write-at-settle that lost both the audit row and the ledger row for
    a password that had already gone to ArcGIS, and Esri counts what GeoLens
    then did not: cancellation plus retry could walk an account past the five
    failures that lock it. The attempt is now committed BEFORE the POST, so
    the count survives the cancellation whatever else does.

    Cancelled from outside, which is what uvicorn does to an in-flight handler
    on shutdown, rather than by a deadline — the deadlines were already fixed
    in #1758 round 11 and are not what this covers.
    """
    entered_mint = asyncio.Event()
    never = asyncio.Event()

    async def _hanging_mint(_self, _username, _password):
        entered_mint.set()
        await never.wait()
        raise AssertionError("unreachable: the wait above is never released")

    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        with patch.object(arcgis_signin.PortalSignIn, "mint", _hanging_mint):
            call = asyncio.create_task(
                client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)
            )
            async with asyncio.timeout(30):
                await entered_mint.wait()
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call

        account_key = signin_account_key(_scope(), FIXTURE_USERNAME)
        ledger = await test_db_session.scalar(
            select(func.count())
            .select_from(ArcGISSignInAttempt)
            .where(ArcGISSignInAttempt.account_key == account_key)
        )
        # The reservation, committed before the password went out.
        assert ledger == 1
        # And the operator-facing half, written by the shielded finaliser. Its
        # own outcome, because GeoLens does not know whether ArcGIS counted
        # the POST and must not claim either way.
        rows = await _audit_rows(test_db_session)
        assert [row.details["result"] for row in rows] == ["cancelled"]
        assert rows[0].details["account_key"] == account_key

        # The budget moved: two attempts left, and the fourth is refused. This
        # is the half that a lost ledger row silently took away.
        for _ in range(2):
            assert (
                await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)
            ).status_code == 200
        refused = await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)

    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"
    assert [row.details["result"] for row in await _audit_rows(test_db_session)] == [
        "cancelled",
        "success",
        "success",
        "rate_limited",
    ]
    ledger = await test_db_session.scalar(
        select(func.count())
        .select_from(ArcGISSignInAttempt)
        .where(ArcGISSignInAttempt.account_key == account_key)
    )
    # Three counted attempts and no more: the refusal spends nothing.
    assert ledger == 3


async def test_both_advisory_locks_are_released_when_the_body_raises(
    client: AsyncClient,
):
    """fix(#1758 codex r6): one transaction holds both, so both come back together.

    fix(#1758 codex r10): and that transaction is the request's, so the
    release point is the commit or rollback that ends it rather than the exit
    of a context manager. Pinned in both directions here: still held while the
    transaction is open, both free once it is not.
    """
    from app.core.db import async_session

    user_scope = f"user:{uuid.uuid4()}:host:{_scope()}"
    account_scope = f"account:{signin_account_key(_scope(), FIXTURE_USERNAME)}"

    async def _try(session, user, account) -> bool:
        async with signin_guard._signin_locks(session, user, account) as held:
            return held

    async with async_session() as holder:
        with pytest.raises(RuntimeError):
            async with signin_guard._signin_locks(
                holder, user_scope, account_scope
            ) as held:
                assert held
                raise RuntimeError("boom")

        # The unwind did not release them: the transaction is still open.
        async with async_session() as probe:
            assert await _try(probe, user_scope, f"account:{uuid.uuid4().hex}") is False

    # Now it is closed, and each scope is free on its own rather than the
    # pair only being free together.
    async with async_session() as after:
        assert await _try(after, user_scope, f"account:{uuid.uuid4().hex}")
    async with async_session() as after:
        assert await _try(after, f"user:{uuid.uuid4()}:host:{_scope()}", account_scope)


async def test_the_account_lock_scope_is_the_account_and_not_the_geolens_caller(
    client: AsyncClient, admin_auth_header: dict, editor_auth_header: dict, allow_ssrf
):
    """fix(#1758 codex r3): keyed by GeoLens user, two colleagues could run
    concurrent mints against one ArcGIS account and each read the counter
    before the other had written a row. The account scope both callers hand
    the lock must therefore be identical, while the user-portal scope in front
    of it must differ per caller."""
    seen: list[tuple[str, str]] = []

    @contextlib.asynccontextmanager
    async def _record(_db, user_scope, account_scope):
        seen.append((user_scope, account_scope))
        yield False

    exchange = _Exchange({})
    with patch("app.modules.catalog.sources.signin_guard._signin_locks", _record):
        with _install(exchange):
            for headers in (admin_auth_header, editor_auth_header):
                resp = await client.post(SIGNIN_URL, json=_body(), headers=headers)
                assert resp.status_code == 409

    assert len(seen) == 2
    user_scopes = [pair[0] for pair in seen]
    account_scopes = [pair[1] for pair in seen]
    # fix(#1758 codex r5): the ORDER is the deadlock argument, and fix(#1758
    # codex r6) made it the ARGUMENT order, so pin which scope is which.
    assert all(scope.startswith("user:") for scope in user_scopes)
    assert all(scope.startswith("account:") for scope in account_scopes)
    # One account, so one account scope, whoever is asking.
    assert account_scopes[0] == account_scopes[1]
    assert (
        account_scopes[0] == f"account:{signin_account_key(_scope(), FIXTURE_USERNAME)}"
    )
    # Two different callers, two different user-portal scopes, one portal.
    assert user_scopes[0] != user_scopes[1]
    assert all(scope.endswith(f":host:{_scope()}") for scope in user_scopes)


async def test_two_spellings_of_one_portal_share_one_budget(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1758 codex r5): one destination, one budget, however it is spelled.

    httpx sends the Unicode and the punycode form to the same place, and the
    trailing root dot and the capitals change nothing either. Before
    canonicalization each spelling took its own lock and its own ledger
    bucket, so a caller had three attempts per spelling instead of three per
    portal.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    unicode_host = f"b\u00fccher{uuid.uuid4().hex[:8]}.example"
    punycode_host = idna.encode(unicode_host, uts46=True).decode("ascii")
    spellings = [
        f"https://{unicode_host}",
        f"https://{punycode_host}",
        f"https://{punycode_host.upper()}",
        f"https://{punycode_host}.",
    ]

    with _install(exchange):
        statuses = [
            (
                await client.post(
                    SIGNIN_URL,
                    json={
                        "portal_url": spelling,
                        "username": FIXTURE_USERNAME,
                        "password": FIXTURE_SECRET,
                    },
                    headers=admin_auth_header,
                )
            ).status_code
            for spelling in spellings
        ]

    # Three attempts for the portal, not three for each way of writing it.
    assert statuses == [200, 200, 200, 429]
    rows = await _audit_rows(test_db_session, host=_scope(punycode_host))
    assert [row.details["result"] for row in rows] == [
        "success",
        "success",
        "success",
        "rate_limited",
    ]
    # One canonical host and one account key across all four spellings.
    assert {row.details["token_service_host"] for row in rows} == {
        _scope(punycode_host)
    }
    assert len({row.details["account_key"] for row in rows}) == 1
    # And the outbound requests went to the canonical host too.
    assert all(punycode_host in str(request.url) for request in exchange.requests)


async def test_the_budget_follows_the_token_service_not_the_typed_address(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1758 codex r7): the budget belongs to the destination.

    `authInfo.tokenServicesUrl` may name a host other than the portal, so the
    scope has to be the address that will actually receive the password
    rather than the one the caller typed. Four spellings of one portal, all
    delegating to one token service, must spend one budget under the TOKEN
    SERVICE's scope, with nothing at all booked against the portal's own.

    fix(#1758 codex r13): the four are spellings of one host rather than four
    separate hostnames, because a delegate must now be a subdomain of the
    portal and no one delegate can be a subdomain of four different hosts.
    Four unrelated portals pointing at one victim's token service is exactly
    what the delegate bound now refuses outright, and
    `test_a_token_service_on_an_unrelated_host_is_not_followed` covers that.
    """
    token_service_host = f"tokens.{_host()}"
    advertised = f"https://{token_service_host}/arcgis/tokens/generateToken"
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload(advertised)),
            "generateToken": _json_response(_token_payload()),
        }
    )
    spellings = [
        f"https://{_host()}",
        f"https://{_host()}/",
        f"https://{_host().upper()}",
        f"https://{_host()}/sharing/rest",
    ]

    with _install(exchange):
        statuses = [
            (
                await client.post(
                    SIGNIN_URL,
                    json={
                        "portal_url": spelling,
                        "username": FIXTURE_USERNAME,
                        "password": FIXTURE_SECRET,
                    },
                    headers=admin_auth_header,
                )
            ).status_code
            for spelling in spellings
        ]

    assert statuses == [200, 200, 200, 429]
    assert len(exchange.posts) == 3
    # Every POST went to the one destination, whichever spelling was typed.
    assert all(str(request.url) == advertised for request in exchange.posts)

    delegate_scope = _scope(token_service_host, "/arcgis/tokens")
    rows = await _audit_rows(test_db_session, host=delegate_scope)
    assert [row.details["result"] for row in rows] == [
        "success",
        "success",
        "success",
        "rate_limited",
    ]
    # One bucket, keyed on the destination rather than on the portal.
    assert len({row.details["account_key"] for row in rows}) == 1
    assert await _audit_rows(test_db_session, host=_scope()) == []


async def test_a_discovery_failure_takes_no_lock_and_writes_no_ledger_row(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Phase one is credential-free, so its failures cost nobody a budget.

    The lock is proven untaken by watching the guard's own lock helper; the
    ledger is proven untouched by counting its rows either side of the
    refusal.

    fix(#1758): watches `_signin_locks` rather than counting calls to
    `app.core.db.async_session`. That proxy dated from before the locks moved
    onto the request session, by which point it no longer observed locking at
    all: it counted every call to a PROCESS-GLOBAL factory, so anything else
    in the worker that opened a session during the request was counted as a
    lock this sign-in took. `get_db` itself calls that factory, as do the
    ingest and embedding task paths. That made the assertion red on a loaded
    runner with nothing wrong, in merge-queue runs 33649640369 and
    33649761185 on two frontend-only PRs.

    Watching the helper the handler actually calls is both narrower and
    truer to the sentence being asserted, and it cannot be reached by
    anything outside this request.
    """
    await _clear_unknown_host_rows(test_db_session)

    locks_taken = 0
    real_locks = signin_guard._signin_locks

    @contextlib.asynccontextmanager
    async def _counting_locks(db, user_scope, account_scope):
        nonlocal locks_taken
        locks_taken += 1
        async with real_locks(db, user_scope, account_scope) as held:
            yield held

    before = await test_db_session.scalar(
        select(func.count()).select_from(ArcGISSignInAttempt)
    )
    # A portal whose name does not resolve. Note that a transport failure on
    # the discovery GET is deliberately NOT a discovery failure: the
    # conventional `/generateToken` is the documented fallback, so the sign-in
    # goes on to try it and any failure there is the mint's.
    exchange = _Exchange({})
    with patch.object(signin_guard, "_signin_locks", _counting_locks):
        with patch(
            "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
            new_callable=AsyncMock,
            side_effect=SSRFResolutionError("Could not resolve hostname"),
        ):
            with _install(exchange):
                resp = await client.post(
                    SIGNIN_URL, json=_body(), headers=admin_auth_header
                )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "network_error"
    assert exchange.requests == []
    assert locks_taken == 0, "a discovery failure must not take a lock"

    after = await test_db_session.scalar(
        select(func.count()).select_from(ArcGISSignInAttempt)
    )
    assert after == before

    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["discovery_unreachable"]


async def test_an_ipv4_shorthand_shares_the_budget_with_its_dotted_quad(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """`127.1` and `127.0.0.1` reach one destination, so they are one bucket."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        statuses = [
            (
                await client.post(
                    SIGNIN_URL,
                    json={
                        "portal_url": spelling,
                        "username": FIXTURE_USERNAME,
                        "password": FIXTURE_SECRET,
                    },
                    headers=admin_auth_header,
                )
            ).status_code
            for spelling in (
                "https://198.51.100.9",
                "https://198.51.100.9",
                # inet_aton's three-part form: 198.51.(100 * 256 + 9).
                "https://198.51.25609",
                "https://198.51.100.9",
            )
        ]

    assert statuses == [200, 200, 200, 429]
    rows = await _audit_rows(test_db_session, host=_scope("198.51.100.9"))
    assert len(rows) == 4


async def test_a_host_that_does_not_canonicalize_is_refused_before_any_request(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """An unbucketable host is an unlimited one, so it is refused outright."""
    await _clear_unknown_host_rows(test_db_session)
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp = await client.post(
            SIGNIN_URL,
            json={
                # A label over the 63-octet limit: accepted by pydantic's
                # HttpUrl, refused by IDNA, which is the gap this closes.
                "portal_url": f"https://{'a' * 70}.example",
                "username": FIXTURE_USERNAME,
                "password": FIXTURE_SECRET,
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "arcgis_portal_host_invalid"
    assert detail["field"] == "url"
    assert exchange.requests == []

    rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in rows] == ["portal_host_invalid"]
    # The lock is never reached, so no ledger row is written either.


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("EXAMPLE.test", "example.test"),
        ("example.test.", "example.test"),
        ("b\u00fccher.example", "xn--bcher-kva.example"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("127.1", "127.0.0.1"),
        ("0x7f.0.0.1", "127.0.0.1"),
        ("127.0.0.1", "127.0.0.1"),
        ("[2001:0db8::0001]", "2001:db8::1"),
        ("2001:DB8::1", "2001:db8::1"),
    ],
)
def test_canonical_host_collapses_the_spellings_of_one_destination(spelling, canonical):
    assert arcgis_signin.canonical_host(spelling) == canonical


@pytest.mark.parametrize(
    "spelling", ["", " ", "..", "exa mple.test", "-bad.example", "a" * 300]
)
def test_canonical_host_refuses_what_it_cannot_reduce(spelling):
    with pytest.raises(ArcGISSignInError) as caught:
        arcgis_signin.canonical_host(spelling)
    assert caught.value.code == "arcgis_portal_host_invalid"
    assert caught.value.status_code == 422


def test_the_non_raising_host_helper_answers_unknown_for_the_rate_limit_key():
    """The SlowAPI key function runs before the handler and must not raise."""
    assert portal_host("https://EXAMPLE.test./sharing/rest") == "example.test"
    assert portal_host("https://xn--0.example") == "unknown"
    assert portal_host("not a url at all") == "unknown"


def test_the_account_key_is_a_digest_and_not_the_username():
    key = signin_account_key("portal.example.test", FIXTURE_USERNAME)
    assert len(key) == 64 and all(c in "0123456789abcdef" for c in key)
    assert FIXTURE_USERNAME not in key
    # Not a bare hash of the obvious inputs: the digest is keyed, so knowing
    # the host and the username is not enough to recompute it.
    for guess in (
        FIXTURE_USERNAME,
        f"portal.example.test{FIXTURE_USERNAME}",
        f"portal.example.test:{FIXTURE_USERNAME}",
    ):
        assert key != hashlib.sha256(guess.encode()).hexdigest()


def test_the_account_key_separates_portals_and_folds_username_case():
    assert signin_account_key("a.example.test", FIXTURE_USERNAME) != (
        signin_account_key("b.example.test", FIXTURE_USERNAME)
    )
    assert signin_account_key("a.example.test", FIXTURE_USERNAME) != (
        signin_account_key("a.example.test", "someone-else")
    )
    # ArcGIS sign-in is case-insensitive, so two spellings are one budget.
    assert signin_account_key("a.example.test", "  Fixture.User  ") == (
        signin_account_key("a.example.test", "fixture.user")
    )
    # And the length prefixes stop a boundary shift from colliding.
    assert signin_account_key("ab.test", "cd") != signin_account_key("ab.tes", "tcd")


async def test_a_signin_while_one_is_in_flight_is_refused_before_the_portal(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """Parallel attempts all arrive before any counter has moved.

    The lock is held by the request that got there first, which a
    single-request test cannot reproduce, so the endpoint's half is driven by
    a stand-in that reports the lock as taken. The lock's own half is the two
    tests above, which use the real database.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )

    @contextlib.asynccontextmanager
    async def _lock_taken(_db, _user_scope, _account_scope):
        yield False

    with patch("app.modules.catalog.sources.signin_guard._signin_locks", _lock_taken):
        with _install(exchange):
            resp = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "arcgis_signin_in_progress"
    # fix(#1758 codex r7): discovery runs before the lock, so its
    # credential-free GET has happened; the credential POST has not.
    assert exchange.posts == []

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == ["concurrent_attempt"]


async def test_the_shared_counter_refuses_the_fourth_attempt_in_the_window(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """The cross-worker limit, with the per-process limiter left disabled.

    fix(#1758 codex r1): the SlowAPI counters are per uvicorn worker and a
    stock install runs two, so three attempts were really six. This drives the
    endpoint with the in-memory limiter off, exactly as a fourth request
    arriving at the OTHER worker would, and the refusal can only come from the
    audit-row count.
    """
    assert limiter.enabled is False  # pin the premise: no in-memory counter
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        statuses = [
            (
                await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)
            ).status_code
            for _ in range(4)
        ]

    assert statuses == [200, 200, 200, 429]
    assert len(exchange.posts) == 3
    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == [
        "success",
        "success",
        "success",
        "rate_limited",
    ]


async def test_one_caller_serializes_across_accounts_on_one_portal(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """fix(#1758 codex r5): the per-user budget was racy across accounts.

    Signing in to different usernames on one portal took different ACCOUNT
    locks, so concurrent attempts all read the same pre-attempt count and all
    passed a limit of three. A second lock keyed on (caller, portal) now sits
    in front of the account lock, so one caller's attempts against one portal
    serialize however many accounts they name.

    The real advisory lock is held here, not a stand-in: the point is that a
    lock taken for one account blocks a concurrent attempt at a different one.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        first = await client.post(
            SIGNIN_URL, json=_body(username="account-one"), headers=admin_auth_header
        )
        assert first.status_code == 200
        rows = await _audit_rows(test_db_session)
        caller_id = rows[0].user_id

        from app.core.db import async_session

        async with (
            async_session() as holder,
            signin_guard._signin_locks(
                holder,
                f"user:{caller_id}:host:{_scope()}",
                f"account:{signin_account_key(_scope(), 'someone-else')}",
            ) as held,
        ):
            assert held
            blocked = await client.post(
                SIGNIN_URL,
                json=_body(username="account-two"),
                headers=admin_auth_header,
            )

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "arcgis_signin_in_progress"
    # It stopped at the outer lock, so the portal never heard about account two.
    assert len(exchange.posts) == 1

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == [
        "success",
        "concurrent_attempt",
    ]
    # A different account, so the refusal is the caller-and-portal lock's doing
    # rather than the account lock's.
    assert rows[0].details["account_key"] != rows[1].details["account_key"]
    assert rows[1].details["account_key"] == signin_account_key(_scope(), "account-two")


async def test_two_geolens_users_share_one_budget_for_one_arcgis_account(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    allow_ssrf,
    test_db_session,
):
    """fix(#1758 codex r3): the lockout belongs to the ArcGIS account.

    Esri locks after five failed sign-ins in fifteen minutes and counts them
    per account, so a budget scoped to the GeoLens caller lets two colleagues
    put six attempts against one account and lock it. Two callers, one
    account, one budget of three.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        first = [
            (
                await client.post(SIGNIN_URL, json=_body(), headers=admin_auth_header)
            ).status_code
            for _ in range(2)
        ]
        second = [
            (
                await client.post(SIGNIN_URL, json=_body(), headers=editor_auth_header)
            ).status_code
            for _ in range(2)
        ]

    assert first == [200, 200]
    # The second caller gets the one attempt left, then the same refusal.
    assert second == [200, 429]
    assert len(exchange.posts) == 3

    rows = await _audit_rows(test_db_session)
    assert [row.details["result"] for row in rows] == [
        "success",
        "success",
        "success",
        "rate_limited",
    ]
    assert len({row.details["account_key"] for row in rows}) == 1


async def test_one_user_still_cannot_walk_many_accounts_on_one_portal(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    """The per-GeoLens-user budget stays beside the account budget.

    The account budget alone would let one caller take three attempts against
    every account on a portal in turn, which is the enumeration the per-user
    limit exists to stop.
    """
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        statuses = [
            (
                await client.post(
                    SIGNIN_URL,
                    json=_body(username=f"account-{index}"),
                    headers=admin_auth_header,
                )
            ).status_code
            for index in range(4)
        ]

    assert statuses == [200, 200, 200, 429]
    rows = await _audit_rows(test_db_session)
    # Four different accounts, so only the per-user budget can have refused.
    assert len({row.details["account_key"] for row in rows}) == 4


async def test_a_refusal_geolens_made_itself_does_not_spend_the_budget(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A rate-limited or policy refusal never reached ArcGIS, so it must not
    count, and a refusal that counted itself would hold the caller over the
    limit for another fifteen minutes on every retry."""
    await _clear_unknown_host_rows(test_db_session)
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    http_portal = {
        "portal_url": _portal().replace("https://", "http://", 1),
        "username": FIXTURE_USERNAME,
        "password": FIXTURE_SECRET,
    }
    with _install(exchange):
        for _ in range(4):
            refused = await client.post(
                SIGNIN_URL, json=http_portal, headers=admin_auth_header
            )
            assert refused.status_code == 422

        with patch(
            "app.modules.catalog.sources.arcgis_signin.validate_url_for_ssrf",
            new_callable=AsyncMock,
        ):
            allowed = await client.post(
                SIGNIN_URL, json=_body(), headers=admin_auth_header
            )

    assert allowed.status_code == 200
    refused_rows = await _audit_rows(test_db_session, host="unknown")
    assert [row.details["result"] for row in refused_rows] == ["portal_not_https"] * 4


async def test_the_uncounted_set_names_only_refusals_geolens_made_itself():
    """Pin the criterion, not just the membership.

    Every uncounted outcome must be one where nothing was sent to ArcGIS. The
    set is an exclusion list on purpose, so a new outcome counts by default.
    """
    assert arcgis_signin.UNCOUNTED_SIGNIN_RESULTS == {
        "concurrent_attempt",
        "rate_limited",
        "ssrf_blocked",
        "portal_not_https",
        "token_service_not_https",
        "portal_host_invalid",
        "discovery_unreachable",
        "discovery_timeout",
    }


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class _ListHandler(logging.Handler):
    """Captures the fully rendered line for every record it receives."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


async def _post_with_captured_logs(client, headers, body) -> tuple[object, list[str]]:
    """Run one sign-in through the real logging pipeline and keep every line.

    ``caplog`` sees zero structlog records in this repo, so this attaches an
    explicit handler to the stdlib root logger and gives it the formatter
    ``setup_logging()`` installed, exactly as the #1746 redaction tests do.
    """
    with configured_logging(json_logs=True, log_level="DEBUG", production=True):
        root = logging.getLogger()
        capture = _ListHandler()
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        try:
            resp = await client.post(SIGNIN_URL, json=body, headers=headers)
        finally:
            root.removeHandler(capture)
    return resp, capture.lines


async def test_a_successful_signin_leaks_nothing_into_logs_or_the_audit_row(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )
    with _install(exchange):
        resp, lines = await _post_with_captured_logs(client, admin_auth_header, _body())

    assert resp.status_code == 200
    assert resp.json()["token"] == FIXTURE_TOKEN  # pin the premise
    assert lines, "the capture handler saw nothing, so it proves nothing"
    blob = "\n".join(lines)
    assert FIXTURE_SECRET not in blob
    assert FIXTURE_TOKEN not in blob
    assert FIXTURE_USERNAME not in blob

    rows = await _audit_rows(test_db_session)
    assert len(rows) == 1
    recorded = json.dumps(rows[0].details)
    assert rows[0].details == {
        "token_service_host": _scope(),
        "result": "success",
        "account_key": signin_account_key(_scope(), FIXTURE_USERNAME),
    }
    assert FIXTURE_SECRET not in recorded
    assert FIXTURE_TOKEN not in recorded
    assert FIXTURE_USERNAME not in recorded


async def test_a_refused_signin_leaks_nothing_into_logs_or_the_audit_row(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, test_db_session
):
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(
                _error_payload(400, "Unable to generate token.", ["Invalid username."])
            ),
            "self": _json_response({"canSignInArcGIS": True}),
        }
    )
    with _install(exchange):
        resp, lines = await _post_with_captured_logs(client, admin_auth_header, _body())

    assert resp.status_code == 400
    assert lines, "the capture handler saw nothing, so it proves nothing"
    blob = "\n".join(lines)
    assert FIXTURE_SECRET not in blob
    assert FIXTURE_USERNAME not in blob
    # Provider prose about somebody's account stays out of the log too.
    assert "Invalid username." not in blob

    rows = await _audit_rows(test_db_session)
    assert len(rows) == 1
    assert FIXTURE_SECRET not in json.dumps(rows[0].details)
    assert FIXTURE_USERNAME not in json.dumps(rows[0].details)


async def test_a_transport_failure_leaks_nothing_into_logs(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf
):
    """The one path that logs an exception type rather than a classification."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": httpx.ProtocolError("bad chunk"),
        }
    )
    with _install(exchange):
        resp, lines = await _post_with_captured_logs(client, admin_auth_header, _body())

    assert resp.status_code == 502
    blob = "\n".join(lines)
    assert FIXTURE_SECRET not in blob
    assert FIXTURE_USERNAME not in blob


async def test_the_error_that_crosses_the_boundary_carries_only_a_code(allow_ssrf):
    """No password in the string, and no chained cause holding the request."""
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": httpx.ConnectError("connection refused"),
        }
    )
    with _install(exchange):
        with pytest.raises(ArcGISSignInError) as caught:
            await mint_portal_token(_portal(), FIXTURE_USERNAME, FIXTURE_SECRET)

    exc = caught.value
    assert str(exc) == "network_error"
    assert exc.__cause__ is None
    for rendered in (str(exc), repr(exc), json.dumps(exc.message)):
        assert FIXTURE_SECRET not in rendered
        assert FIXTURE_USERNAME not in rendered


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"portal_url": SAMPLE_PORTAL, "username": FIXTURE_USERNAME},
        {"portal_url": SAMPLE_PORTAL, "password": FIXTURE_SECRET},
        {"username": FIXTURE_USERNAME, "password": FIXTURE_SECRET},
        {"portal_url": "ftp://portal.example.test", "username": "a", "password": "b"},
        {"portal_url": SAMPLE_PORTAL, "username": "", "password": FIXTURE_SECRET},
    ],
)
async def test_an_incomplete_body_is_refused_before_any_outbound_request(
    client: AsyncClient, admin_auth_header: dict, body
):
    exchange = _Exchange({})
    with _install(exchange):
        resp = await client.post(SIGNIN_URL, json=body, headers=admin_auth_header)
    assert resp.status_code == 422
    assert exchange.requests == []


async def test_a_portal_url_carrying_credentials_is_refused(
    client: AsyncClient, admin_auth_header: dict
):
    resp = await client.post(
        SIGNIN_URL,
        json={
            "portal_url": f"https://someone:{uuid.uuid4().hex}@portal.example.test",
            "username": FIXTURE_USERNAME,
            "password": FIXTURE_SECRET,
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
