"""fix(#1596): the anonymous wildcard has to cover catalog search too.

``DynamicCORSMiddleware`` answers an origin outside ``CORS_ALLOWED_ORIGINS``
with a credential-free wildcard policy, but only for paths
``standards_api_path()`` classifies. ``GET /search/datasets/`` is the native
route behind the same query engine as ``/collections/datasets/items``, it is
anonymous-readable by design, and a browser page on another origin got no CORS
headers at all — so the OGC Records alias worked cross-origin and the native
search did not.

The classifier stays where it is. It is shared with the error and OpenAPI
contracts, and widening it would move ``/search`` onto the OGC error shape as a
side effect. The middleware carries its own explicit list instead.

Two properties these tests exist to hold:

- the widening is narrow. ``/search/saved/`` sits under the same router prefix
  and requires an authenticated user, and ``/maps/`` answers a stranger with a
  200 and still stays outside the wildcard. The list is an allow-list, not
  "whatever an anonymous caller happens to be able to read".
- the preflight tells the truth. #1470 was a preflight advertising ``HEAD`` on
  routes that answered ``405``. Search answers ``GET`` and nothing else, so its
  ``Access-Control-Allow-Methods`` says ``GET, OPTIONS`` and a preflight asking
  for ``HEAD`` or ``POST`` is refused rather than promised.
"""

from fastapi.routing import APIRoute, iter_route_contexts
import pytest
from starlette.requests import Request

from app.api.main import app
from app.api.middleware.cors import _PUBLIC_SEARCH_PATHS, DynamicCORSMiddleware
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_current_user,
)

_FOREIGN_ORIGIN = "https://cors-1596.example.org"
_ALLOWED_ORIGIN = "https://allowed-1596.example.com"


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


async def test_anonymous_search_is_readable_from_a_foreign_origin(
    client, deny_all_origins
):
    """The reported case: a browser page elsewhere calls catalog search."""
    response = await client.get(
        "/search/datasets/?q=subway", headers={"Origin": _FOREIGN_ORIGIN}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("path", _PUBLIC_SEARCH_PATHS)
async def test_every_listed_search_path_answers_the_wildcard(
    client, deny_all_origins, path
):
    response = await client.get(path, headers={"Origin": _FOREIGN_ORIGIN})
    assert response.status_code == 200, path
    assert response.headers["access-control-allow-origin"] == "*", path
    assert "access-control-allow-credentials" not in response.headers, path


async def test_search_preflight_is_answered(client, deny_all_origins):
    preflight = await client.options(
        "/search/datasets/",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Accept",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in preflight.headers
    assert preflight.headers["access-control-allow-headers"] == "Accept"


async def test_search_preflight_advertises_only_what_the_route_answers(
    client, deny_all_origins
):
    """fix(#1470) again, on the new surface: no promise the route will refuse.

    Search is registered ``GET``-only. FastAPI's ``APIRoute`` does not add HEAD
    alongside GET the way starlette's plain ``Route`` does, and the derived-HEAD
    pass in ``api/main.py`` is keyed on ``standards_api_path``, so HEAD and POST
    both 405 here. The preflight has to say so instead of inviting them.
    """
    preflight = await client.options(
        "/search/datasets/",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    methods = {
        method.strip()
        for method in preflight.headers["access-control-allow-methods"].split(",")
    }
    assert methods == {"GET", "OPTIONS"}

    for refused in ("HEAD", "POST"):
        # What the route does with it...
        direct = await client.request(refused, "/search/datasets/")
        assert direct.status_code == 405, refused
        # ...is what the preflight has to predict.
        preflight = await client.options(
            "/search/datasets/",
            headers={
                "Origin": _FOREIGN_ORIGIN,
                "Access-Control-Request-Method": refused,
            },
        )
        assert "access-control-allow-origin" not in preflight.headers, refused


async def test_search_exposes_the_headers_it_sets(client, deny_all_origins):
    """``Link`` is unreadable to JavaScript unless it is named here.

    ``standard_response_headers`` sets ``Vary``, ``Content-Language`` and
    ``Link`` on the search response. ``Content-Language`` is CORS-safelisted;
    ``Link`` carries the next/prev pagination hrefs and is not, so a client
    paginating cross-origin needs it exposed.
    """
    response = await client.get(
        "/search/datasets/?q=subway", headers={"Origin": _FOREIGN_ORIGIN}
    )
    exposed = {
        header.strip().lower()
        for header in response.headers["access-control-expose-headers"].split(",")
    }
    assert "link" in exposed
    assert "content-language" in exposed


@pytest.mark.parametrize(
    "credential",
    [
        {"Authorization": "Bearer not-a-real-token"},
        {"X-Api-Key": "not-a-real-key"},
        {"Cookie": "session=not-a-real-session"},
    ],
)
async def test_a_credential_bearing_search_gets_no_wildcard(
    client, deny_all_origins, credential
):
    response = await client.get(
        "/search/datasets/?q=subway",
        headers={"Origin": _FOREIGN_ORIGIN, **credential},
    )
    assert "access-control-allow-origin" not in response.headers


async def test_a_query_string_credential_gets_no_wildcard(client, deny_all_origins):
    response = await client.get(
        "/search/datasets/?q=subway&api_key=not-a-real-key",
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "path,expected_status",
    [
        # Shares the router prefix with the listed paths and is authenticated,
        # so a prefix match over ``/search`` would have swept it in.
        ("/search/saved/", 401),
        ("/datasets/", 401),
        # The sharp one: anonymous-readable, 200 to a stranger, and still no
        # wildcard. The list is an allow-list, not "whatever anonymous can read".
        ("/maps/", 200),
    ],
)
async def test_the_widening_stops_at_the_listed_paths(
    client, deny_all_origins, path, expected_status
):
    response = await client.get(path, headers={"Origin": _FOREIGN_ORIGIN})
    # Pinned so a rename cannot turn this into a 404 that passes for free.
    assert response.status_code == expected_status, path
    assert "access-control-allow-origin" not in response.headers, path


async def test_an_allowed_origin_keeps_the_credentialed_policy(
    client, allow_one_origin
):
    response = await client.get(
        "/search/datasets/?q=subway", headers={"Origin": _ALLOWED_ORIGIN}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_an_allowed_origin_keeps_the_credentialed_policy_with_a_token(
    client, allow_one_origin, admin_auth_header
):
    """An allow-listed origin is unaffected by the credential exclusion."""
    response = await client.get(
        "/search/datasets/?q=subway",
        headers={"Origin": _ALLOWED_ORIGIN, **admin_auth_header},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


# --- path normalization ---


def _scope(path: str, *, root_path: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": root_path,
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.parametrize(
    "root_path,raw,expected",
    [
        ("", "/search/datasets/", "/search/datasets/"),
        ("/api", "/api/search/datasets/", "/search/datasets/"),
        ("/api/", "/api/search/datasets/", "/search/datasets/"),
        ("/api", "/api", "/"),
    ],
)
def test_root_path_is_stripped_before_the_list_is_read(root_path, raw, expected):
    """The list holds app-relative paths, so a mounted deployment has to match.

    Whether ``/api`` is stripped by the proxy or carried as an ASGI
    ``root_path`` is the operator's choice, and the reported URL
    (``/api/search/datasets/``) is the mounted form.
    """
    request = _scope(raw, root_path=root_path)
    assert DynamicCORSMiddleware._request_path(request) == expected


def test_a_mounted_deployment_still_earns_the_wildcard():
    request = _scope("/api/search/datasets/", root_path="/api")
    assert DynamicCORSMiddleware._anonymous_public_methods(request) == "GET, OPTIONS"


def test_a_mounted_standards_path_keeps_its_own_method_set():
    """The two surfaces are resolved separately and must not swap policies."""
    request = _scope("/api/collections", root_path="/api")
    assert (
        DynamicCORSMiddleware._anonymous_public_methods(request)
        == "GET, HEAD, POST, OPTIONS"
    )


# --- structural guard on the list itself ---


def _dependency_calls(dependant) -> set:
    calls = {dependant.call}
    for child in dependant.dependencies:
        calls |= _dependency_calls(child)
    return calls


def _routes_for_path(path: str) -> list:
    return [
        ctx.route
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute) and ctx.path == path
    ]


@pytest.mark.parametrize("path", _PUBLIC_SEARCH_PATHS)
def test_listed_paths_are_get_only_and_anonymous(path):
    """A path earns the wildcard only by being a real, GET-only, open route.

    Fails toward reporting: an entry that matches nothing in the route table is
    a failure, not a silent pass, so a typo or a route rename cannot leave a
    dead string in the list looking healthy.
    """
    routes = _routes_for_path(path)
    assert routes, f"{path} is in _PUBLIC_SEARCH_PATHS but matches no route"

    for route in routes:
        assert route.methods <= {"GET", "HEAD", "OPTIONS"}, (
            f"{path} answers {sorted(route.methods)}; the wildcard is read-only"
        )
        requires_auth = _dependency_calls(route.dependant) & {
            get_current_active_user,
            get_current_user,
        }
        assert not requires_auth, (
            f"{path} requires an authenticated user via "
            f"{[dep.__name__ for dep in requires_auth]}"
        )
