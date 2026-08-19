"""fix(#1602): a CORS response has to declare that it varies by ``Origin``.

``DynamicCORSMiddleware`` writes two origin-dependent policies. The
credentialed one echoes the caller's origin into
``Access-Control-Allow-Origin``; the anonymous one answers ``*``. Neither said
``Vary: Origin``, so the body and the policy were cacheable under a key that
did not include the input the policy was derived from.

It is not a leak on a default deployment: the shipped ``frontend/nginx.conf``
serves ``location /api/`` with ``proxy_cache off``, and a browser fails closed
when a cached policy does not name its own origin. The header is for the
operator who fronts the API with a caching CDN, where a stored
``Access-Control-Allow-Origin: https://a.example`` replayed to
``https://b.example`` is a policy one origin never earned.

Both policies carry it, including the wildcard. ``*`` does not strictly need
it — the answer is the same for every origin — but the two policies share a
cache. A path that answers one origin with ``*`` and another with an echoed
origin is exactly the case the header disambiguates, and a cache cannot know
which writer produced the entry it holds.

What these tests pin, beyond "the header is present":

- the merge. ``standard_response_headers`` already sets ``Vary:
  Accept-Language`` on the search and standards responses. Overwriting it
  would cost content negotiation its cache key, which is a bug traded for a
  bug, so ``Origin`` is appended to what the route set and each token appears
  once.
- the silence. A response the middleware writes no policy onto must not gain
  ``Vary: Origin``: a request with no ``Origin`` header, and a native route
  answering an origin outside the allow-list. Each of those is paired with the
  positive case on the same route, so a rename that makes the header vanish
  everywhere cannot pass the absence assertion for free.
"""

import pytest
from starlette.responses import Response

from app.api.middleware.cors import DynamicCORSMiddleware, _merge_vary_origin

_FOREIGN_ORIGIN = "https://cors-1602.example.org"
_ALLOWED_ORIGIN = "https://allowed-1602.example.com"


@pytest.fixture
def deny_all_origins(monkeypatch):
    """Force every origin outside the allow-list.

    Stubbed rather than written through settings for the reason
    ``test_ogc_discovery.py`` spells out: a real lookup populates
    ``cors._origins_cache``, a module global with a 30s TTL and no write
    invalidation, and under ``pytest -n 4`` that cache outlives the test.
    """

    async def _deny(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed",
        _deny,
    )


@pytest.fixture
def allow_one_origin(monkeypatch):
    async def _allow(_self, origin):
        return origin == _ALLOWED_ORIGIN

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed",
        _allow,
    )


def _vary_tokens(response) -> list[str]:
    """Every ``Vary`` token across every ``Vary`` field-line, lowercased.

    Reads all field-lines rather than ``headers["vary"]`` so that emitting a
    second ``Vary`` header instead of extending the first cannot pass as a
    merge: a duplicate is legal HTTP and would still be counted here, which is
    what makes the "exactly once" assertions meaningful.
    """
    return [
        token.strip().lower()
        for line in response.headers.get_list("vary")
        for token in line.split(",")
        if token.strip()
    ]


# ---------------------------------------------------------------------------
# (a) the credentialed policy
# ---------------------------------------------------------------------------


async def test_the_credentialed_policy_varies_by_origin(client, allow_one_origin):
    """The response that echoes an origin is the one a cache must key on."""
    response = await client.get("/health", headers={"Origin": _ALLOWED_ORIGIN})

    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "origin" in _vary_tokens(response), dict(response.headers)


async def test_the_credentialed_preflight_varies_by_origin(client, allow_one_origin):
    """The preflight is a separate response written by the same policy.

    It is answered by the middleware itself rather than by a route, so it has
    no ``Vary`` of its own to merge into and would be the easiest of the four
    writers to miss.
    """
    preflight = await client.options(
        "/datasets/",
        headers={
            "Origin": _ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert "origin" in _vary_tokens(preflight), dict(preflight.headers)


# ---------------------------------------------------------------------------
# (b) the anonymous wildcard policy
# ---------------------------------------------------------------------------


async def test_the_wildcard_policy_varies_by_origin(client, deny_all_origins):
    """``*`` shares a cache with the echoed-origin answer, so it says so too."""
    response = await client.get("/conformance", headers={"Origin": _FOREIGN_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    assert "origin" in _vary_tokens(response), dict(response.headers)


async def test_the_wildcard_preflight_varies_by_origin(client, deny_all_origins):
    preflight = await client.options(
        "/collections",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Accept",
        },
    )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "origin" in _vary_tokens(preflight), dict(preflight.headers)


# ---------------------------------------------------------------------------
# (c) the merge with a Vary the route already set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy_fixture, origin, expected_allow_origin",
    [
        ("deny_all_origins", _FOREIGN_ORIGIN, "*"),
        ("allow_one_origin", _ALLOWED_ORIGIN, _ALLOWED_ORIGIN),
    ],
    ids=["wildcard", "credentialed"],
)
async def test_an_existing_vary_keeps_its_tokens_and_gains_origin_once(
    client, request, policy_fixture, origin, expected_allow_origin
):
    """``/search/datasets/`` sets ``Vary: Accept-Language`` before we get here.

    ``standard_response_headers`` sets it so a cache does not serve a French
    body to an English caller. Replacing that value with ``Origin`` would fix
    the CORS variance by breaking the language variance, and a cache would
    then hand the wrong translation to a caller on the right origin — the same
    class of defect one layer over. Both tokens survive, once each.
    """
    request.getfixturevalue(policy_fixture)
    response = await client.get(
        "/search/datasets/?q=subway", headers={"Origin": origin}
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == expected_allow_origin

    tokens = _vary_tokens(response)
    assert "accept-language" in tokens, tokens
    assert tokens.count("origin") == 1, tokens
    assert tokens.count("accept-language") == 1, tokens
    assert len(response.headers.get_list("vary")) == 1, response.headers.get_list(
        "vary"
    )


async def test_the_route_sets_a_vary_this_test_is_not_inventing(
    client, deny_all_origins
):
    """The vacuity guard for the merge test above.

    If ``/search/datasets/`` ever stops setting ``Vary: Accept-Language``, the
    merge assertions still pass while proving nothing about merging. Read the
    route's own answer without an ``Origin`` header, where the middleware never
    runs, and confirm there is something to merge into.

    ``Accept-Encoding`` is in here too — ``GZipMiddleware`` adds its own token
    through the same header — which is the second reason not to assert an
    exact value anywhere in this file: the ``Vary`` on a response is written by
    more than one component, and only ``Origin`` belongs to this fix.
    """
    response = await client.get("/search/datasets/?q=subway")

    assert response.status_code == 200, response.text
    tokens = _vary_tokens(response)
    assert "accept-language" in tokens, dict(response.headers)
    assert "origin" not in tokens, dict(response.headers)


# ---------------------------------------------------------------------------
# (d) the counterfactual: no policy written, no Vary: Origin
# ---------------------------------------------------------------------------


async def test_a_disallowed_origin_on_a_native_route_gains_nothing(
    client, allow_one_origin
):
    """No CORS headers, so nothing that varies by origin, so no ``Vary``.

    ``/maps/`` answers a stranger with a 200 and stays outside the anonymous
    wildcard allow-list, which makes it the route where "no policy" is a real
    state rather than an error page. The allowed origin is asserted on the
    same path in the same test so the absence below cannot pass because the
    header vanished everywhere.
    """
    denied = await client.get("/maps/", headers={"Origin": _FOREIGN_ORIGIN})
    assert denied.status_code == 200
    assert "access-control-allow-origin" not in denied.headers
    assert "origin" not in _vary_tokens(denied), dict(denied.headers)

    allowed = await client.get("/maps/", headers={"Origin": _ALLOWED_ORIGIN})
    assert allowed.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert "origin" in _vary_tokens(allowed), dict(allowed.headers)


async def test_a_request_with_no_origin_header_gains_nothing(client, allow_one_origin):
    """Not a CORS request at all: the middleware returns before either writer."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "origin" not in _vary_tokens(response), dict(response.headers)


# ---------------------------------------------------------------------------
# the merge itself, at the unit the routes cannot reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "existing, expected",
    [
        pytest.param(None, "Origin", id="absent"),
        pytest.param("", "Origin", id="empty"),
        pytest.param("Accept-Language", "Accept-Language, Origin", id="one-token"),
        pytest.param(
            "Accept-Language, Accept-Encoding",
            "Accept-Language, Accept-Encoding, Origin",
            id="two-tokens",
        ),
        # Idempotent, and case-insensitively so: field names are
        # case-insensitive, and a second "origin" is noise a cache has to parse.
        pytest.param("Origin", "Origin", id="already-there"),
        pytest.param("origin", "origin", id="already-there-lowercased"),
        pytest.param(
            "Accept-Language, ORIGIN",
            "Accept-Language, ORIGIN",
            id="already-there-mixed-case",
        ),
        # Whitespace and empty members are legal on the wire (RFC 9110 allows
        # the empty list element); neither may become an empty emitted token.
        pytest.param("  Accept-Language  ", "Accept-Language, Origin", id="padded"),
        pytest.param(
            ",Accept-Language,,", "Accept-Language, Origin", id="empty-members"
        ),
        # ``*`` already says "do not reuse this for another request". Appending
        # to it would be a syntax error against the Vary grammar, which is
        # ``#field-name / "*"`` — the two are alternatives, not a list.
        pytest.param("*", "*", id="star"),
    ],
)
def test_merge_vary_origin(existing, expected):
    response = Response()
    if existing is not None:
        response.headers["Vary"] = existing

    _merge_vary_origin(response)

    assert response.headers.getlist("Vary") == [expected]


def test_merge_vary_origin_collapses_duplicate_field_lines():
    """Two ``Vary`` lines are one header; the merge must not leave a stray.

    Starlette's ``MutableHeaders.__setitem__`` removes the duplicates when it
    writes, so this is a property of the write rather than something the merge
    does by hand — pinned because reading only the first line and setting it
    back would silently drop the second.
    """
    response = Response()
    response.headers.append("Vary", "Accept-Language")
    response.headers.append("Vary", "Accept-Encoding")

    _merge_vary_origin(response)

    assert response.headers.getlist("Vary") == [
        "Accept-Language, Accept-Encoding, Origin"
    ]


def test_both_policy_writers_merge_the_vary():
    """Neither writer may be the one that forgot.

    Called directly rather than through a route because the two writers share
    no call site: ``_set_cors_headers`` answers the credentialed path and
    ``_set_public_cors_headers`` the anonymous one, and a fix applied to one of
    them passes every request-level test that happens to exercise the other.
    """
    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/conformance",
        "query_string": b"",
        "headers": Headers({}).raw,
    }

    credentialed = Response()
    credentialed.headers["Vary"] = "Accept-Language"
    DynamicCORSMiddleware._set_cors_headers(credentialed, _ALLOWED_ORIGIN)
    assert credentialed.headers.getlist("Vary") == ["Accept-Language, Origin"]

    public = Response()
    public.headers["Vary"] = "Accept-Language"
    DynamicCORSMiddleware._set_public_cors_headers(
        public, Request(scope), "GET, OPTIONS"
    )
    assert public.headers.getlist("Vary") == ["Accept-Language, Origin"]
