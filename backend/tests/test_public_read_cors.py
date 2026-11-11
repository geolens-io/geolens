"""An anonymous page on any origin can read the public stories, maps, rows,
aggregates and capabilities.

``DynamicCORSMiddleware`` answers these native reads with the same
credential-free wildcard it gives the standards routes and search. What these
tests hold:

- the anonymous answer carries ``*`` and never ``Allow-Credentials``, and the
  aggregate preflight (a JSON POST) is answered instead of refused with 405;
- a request carrying a credential gets no wildcard, and an allow-listed origin
  keeps the credentialed policy;
- the wildcard covers only the read method of each path, so the writes that
  share ``/maps/{id}`` and ``/stories/{id}`` stay outside it;
- a private map, story or dataset answers exactly as an unknown id does.
"""

import uuid

from fastapi.routing import APIRoute, iter_route_contexts
import pytest
from httpx import AsyncClient

from app.api.main import app
from app.api.middleware.cors import _PUBLIC_READ_PATHS
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from tests.test_dataset_aggregate import points, private_points  # noqa: F401

pytestmark = pytest.mark.anyio

_FOREIGN_ORIGIN = "https://foreign-public-read.example.org"
_ALLOWED_ORIGIN = "https://allowed-public-read.example.com"
_COUNT = {"op": "count"}
# Fixed, since parametrize ids must match across xdist workers.
_SOME_ID = "6f1c0d52-8a43-4c1e-9b7a-2d5e3f4a1b90"


@pytest.fixture(autouse=True)
def allow_one_origin(monkeypatch):
    """Stubbed so no lookup fills the module's 30 s origins cache across workers."""

    async def _allow(_self, origin):
        return origin == _ALLOWED_ORIGIN

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _allow
    )


async def _public_map(client: AsyncClient, admin: dict, visibility="public") -> str:
    created = await client.post(
        "/maps/", json={"name": f"cors-map-{uuid.uuid4().hex[:8]}"}, headers=admin
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    if visibility != "private":
        updated = await client.put(
            f"/maps/{map_id}", json={"visibility": visibility}, headers=admin
        )
        assert updated.status_code == 200, updated.text
    return map_id


async def _published_story(
    client: AsyncClient, admin: dict, visibility="public"
) -> str:
    created = await client.post("/stories/", json={"title": "CORS"}, headers=admin)
    assert created.status_code == 201, created.text
    story = created.json()
    chapter = {
        "id": str(uuid.uuid4()),
        "title": "One",
        "blocks": [
            {
                "id": str(uuid.uuid4()),
                "type": "markdown",
                "v": 1,
                "config": {"text": "Hello"},
            }
        ],
    }
    saved = await client.put(
        f"/stories/{story['id']}/draft",
        json={
            "revision": story["revision"],
            "document": {"version": 1, "chapters": [chapter]},
        },
        headers=admin,
    )
    assert saved.status_code == 200, saved.text
    if visibility != "private":
        widened = await client.patch(
            f"/stories/{story['id']}", json={"visibility": visibility}, headers=admin
        )
        assert widened.status_code == 200, widened.text
    published = await client.post(
        f"/stories/{story['id']}/publish",
        json={"revision": saved.json()["revision"]},
        headers=admin,
    )
    assert published.status_code == 200, published.text
    return story["id"]


@pytest.fixture
async def public_ids(client: AsyncClient, admin_auth_header: dict, points) -> dict:  # noqa: F811
    return {
        "map": await _public_map(client, admin_auth_header),
        "story": await _published_story(client, admin_auth_header),
        "dataset": str(points.id),
    }


_READS = [
    "/capabilities/",
    "/stories/",
    "/stories/{story}",
    "/maps/{map}",
    "/maps/{map}/style.json",
    "/datasets/{dataset}/rows/",
    "/datasets/{dataset}/rows",
    # What an exported style's "sprite" entry makes MapLibre fetch.
    "/maps/sprites/geolens.json",
    "/maps/sprites/geolens.png",
    "/maps/sprites/geolens@2x.json",
    "/maps/sprites/geolens@2x.png",
]


async def _call(client: AsyncClient, path: str, headers: dict):
    if path.rstrip("/").endswith("/aggregate"):
        return await client.post(path, json=_COUNT, headers=headers)
    return await client.get(path, headers=headers)


_ALL = [*_READS, "/datasets/{dataset}/aggregate/", "/datasets/{dataset}/aggregate"]


def _listed(value: str | None) -> set[str]:
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


@pytest.mark.parametrize("template", _ALL)
async def test_an_anonymous_foreign_page_reads_it(
    client: AsyncClient, public_ids, template
):
    path = template.format(**public_ids)

    resp = await _call(client, path, {"Origin": _FOREIGN_ORIGIN})

    assert resp.status_code == 200, resp.text
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resp.headers
    assert "origin" in _listed(resp.headers.get("vary"))


@pytest.mark.parametrize(
    "credential",
    [
        {"Authorization": "Bearer not-a-real-token"},
        {"Cookie": "session=not-a-real-session"},
        {"X-Embed-Token": "not-a-real-token"},
    ],
    ids=["bearer", "cookie", "embed"],
)
@pytest.mark.parametrize("template", _ALL)
async def test_a_credential_gets_no_wildcard(
    client: AsyncClient, public_ids, template, credential
):
    path = template.format(**public_ids)

    resp = await _call(client, path, {"Origin": _FOREIGN_ORIGIN, **credential})

    assert "access-control-allow-origin" not in resp.headers, resp.status_code


@pytest.mark.parametrize("template", _ALL)
async def test_a_query_string_credential_gets_no_wildcard(
    client: AsyncClient, public_ids, template
):
    path = template.format(**public_ids) + "?api_key=not-a-real-key"

    resp = await _call(client, path, {"Origin": _FOREIGN_ORIGIN})

    assert "access-control-allow-origin" not in resp.headers, resp.status_code


@pytest.mark.parametrize("template", _ALL)
async def test_an_allowed_origin_with_a_token_keeps_the_credentialed_policy(
    client: AsyncClient, admin_auth_header: dict, public_ids, template
):
    path = template.format(**public_ids)

    resp = await _call(client, path, {"Origin": _ALLOWED_ORIGIN, **admin_auth_header})

    assert resp.status_code == 200, resp.text
    assert resp.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"


def _preflight(method: str, headers: str | None = None) -> dict[str, str]:
    preflight = {"Origin": _FOREIGN_ORIGIN, "Access-Control-Request-Method": method}
    if headers is not None:
        preflight["Access-Control-Request-Headers"] = headers
    return preflight


@pytest.mark.parametrize("suffix", ["aggregate/", "aggregate"])
async def test_the_aggregate_preflight_is_answered_anonymously(
    client: AsyncClient,
    points,  # noqa: F811
    suffix,
):
    """The reported 405: a JSON POST from another origin needs this preflight."""
    path = f"/datasets/{points.id}/{suffix}"

    preflight = await client.options(path, headers=_preflight("POST", "content-type"))
    posted = await client.post(
        path,
        json=_COUNT,
        headers={"Origin": _FOREIGN_ORIGIN, "Content-Type": "application/json"},
    )

    assert preflight.status_code == 200, preflight.text
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in preflight.headers
    assert _listed(preflight.headers["access-control-allow-methods"]) == {
        "post",
        "options",
    }
    assert _listed(preflight.headers["access-control-allow-headers"]) == {
        "content-type"
    }
    assert posted.status_code == 200, posted.text
    assert posted.json()["result"] == {"count": 8}
    assert posted.headers["access-control-allow-origin"] == "*"


@pytest.mark.parametrize(
    "requested", ["content-type, authorization", "content-type, x-embed-token"]
)
async def test_a_credentialed_aggregate_preflight_gets_no_wildcard(
    client: AsyncClient,
    points,  # noqa: F811
    requested,
):
    resp = await client.options(
        f"/datasets/{points.id}/aggregate/", headers=_preflight("POST", requested)
    )

    assert "access-control-allow-origin" not in resp.headers


async def test_an_allowed_origin_aggregate_preflight_keeps_the_credentialed_policy(
    client: AsyncClient,
    points,  # noqa: F811
):
    resp = await client.options(
        f"/datasets/{points.id}/aggregate/",
        headers={
            "Origin": _ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, authorization",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize(
    "template, method",
    [
        ("/maps/{map}", "PUT"),
        ("/maps/{map}", "DELETE"),
        ("/stories/{story}", "PATCH"),
        ("/stories/{story}", "DELETE"),
        ("/stories/", "POST"),
        ("/datasets/{dataset}/rows/", "POST"),
        ("/datasets/{dataset}/rows", "POST"),
        ("/datasets/{dataset}/aggregate/", "GET"),
        ("/maps/{map}", "HEAD"),
    ],
)
async def test_the_wildcard_covers_only_the_read_method(
    client: AsyncClient, public_ids, template, method
):
    path = template.format(**public_ids)

    resp = await client.options(path, headers=_preflight(method, "content-type"))

    assert "access-control-allow-origin" not in resp.headers, method


@pytest.mark.parametrize(
    "path",
    [
        # Same router prefixes, not listed.
        "/maps/",
        "/stories/frame-hosts/",
        f"/maps/{_SOME_ID}/share/",
        f"/stories/{_SOME_ID}/draft",
        f"/datasets/{_SOME_ID}",
        # A non-canonical id fails closed.
        f"/maps/{_SOME_ID.replace('-', '')}",
    ],
)
async def test_the_widening_stops_at_the_listed_paths(client: AsyncClient, path):
    resp = await client.get(path, headers={"Origin": _FOREIGN_ORIGIN})

    assert "access-control-allow-origin" not in resp.headers, resp.status_code


async def test_a_private_id_answers_as_an_unknown_one(
    client: AsyncClient,
    admin_auth_header: dict,
    private_points,  # noqa: F811
):
    """The wildcard lets a page read the 404 too, so it must say nothing more."""
    private = {
        "map": await _public_map(client, admin_auth_header, "private"),
        "story": await _published_story(client, admin_auth_header, "private"),
        "dataset": str(private_points.id),
    }
    unknown = {key: str(uuid.uuid4()) for key in private}
    for template in [t for t in _ALL if "{" in t]:
        answers = []
        for ids in (private, unknown):
            resp = await _call(
                client, template.format(**ids), {"Origin": _FOREIGN_ORIGIN}
            )
            answers.append(
                (
                    resp.status_code,
                    resp.headers.get("access-control-allow-origin"),
                    resp.json().get("detail"),
                )
            )
        assert answers[0] == answers[1], template
        assert answers[0][0] == 404, template


# --- structural guard on the list itself ---


def _dependency_calls(dependant) -> set:
    calls = {dependant.call}
    for child in dependant.dependencies:
        calls |= _dependency_calls(child)
    return calls


@pytest.mark.parametrize(
    "pattern, allow_methods",
    _PUBLIC_READ_PATHS,
    ids=[pattern.pattern for pattern, _ in _PUBLIC_READ_PATHS],
)
def test_listed_paths_are_open_routes_on_the_advertised_method(pattern, allow_methods):
    """A path earns the wildcard only on a real route that needs no sign-in.

    An entry that matches no route is a failure, so a rename can't leave a dead
    pattern in the list looking healthy.
    """
    advertised = _listed(allow_methods) - {"options"}
    sample_id = str(uuid.uuid4())
    routes = []
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute):
            continue
        concrete = ctx.path
        for name in route.param_convertors:
            concrete = concrete.replace("{" + name + "}", sample_id)
        if pattern.fullmatch(concrete) and {m.lower() for m in route.methods} & (
            advertised
        ):
            routes.append(route)

    assert routes, f"{pattern.pattern} matches no {sorted(advertised)} route"
    for route in routes:
        requires_auth = _dependency_calls(route.dependant) & {
            get_current_active_user,
            get_current_user,
        }
        assert not requires_auth, (
            f"{route.path} requires an authenticated user via "
            f"{[dep.__name__ for dep in requires_auth]}"
        )
