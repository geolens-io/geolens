"""HEAD on a map's style.json and on /health answers with GET's status and headers and no body."""

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

_FOREIGN_ORIGIN = "https://foreign-head-style.example.org"


@pytest.fixture(autouse=True)
def deny_origins(monkeypatch):
    """Stubbed so no lookup fills the module's 30 s origins cache across workers."""

    async def _deny(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _deny
    )


async def _map(client: AsyncClient, headers: dict, visibility: str) -> str:
    created = await client.post(
        "/maps/", json={"name": f"head-map-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    if visibility != "private":
        updated = await client.put(
            f"/maps/{map_id}", json={"visibility": visibility}, headers=headers
        )
        assert updated.status_code == 200, updated.text
    return map_id


def _assert_head_matches(head, get) -> None:
    assert head.status_code == get.status_code
    assert head.content == b""
    for name in ("content-type", "content-length", "cache-control"):
        assert head.headers.get(name) == get.headers.get(name), name


async def test_a_public_style_answers_head_like_get(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    map_id = await _map(client, admin_auth_header, "public")

    head = await client.head(f"/maps/{map_id}/style.json")
    get = await client.get(f"/maps/{map_id}/style.json")

    assert get.status_code == 200
    assert get.json()["version"] == 8
    _assert_head_matches(head, get)
    assert int(head.headers["content-length"]) > 0


async def test_a_private_style_refuses_head_as_it_refuses_get(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    viewer_auth_header: dict,
) -> None:
    """Each caller, credential or not, gets the GET status on HEAD; only the owner reads."""
    map_id = await _map(client, editor_auth_header, "private")
    created = await client.post(
        "/auth/api-keys", json={"name": "style head"}, headers=editor_auth_header
    )
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    url = f"/maps/{map_id}/style.json"
    cases = [
        (url, {}, {}),
        (url, viewer_auth_header, {}),
        (url, {"Authorization": f"Bearer {uuid.uuid4().hex}"}, {}),
        (url, {"X-Api-Key": uuid.uuid4().hex}, {}),
        (url, {}, {"api_key": uuid.uuid4().hex}),
        (url, {"X-Embed-Token": uuid.uuid4().hex}, {}),
        (url, editor_auth_header, {}),
        (url, {"X-Api-Key": key}, {}),
        (f"/maps/{uuid.uuid4()}/style.json", {}, {}),
    ]

    statuses = []
    for path, headers, params in cases:
        head = await client.head(path, headers=headers, params=params)
        get = await client.get(path, headers=headers, params=params)
        assert head.status_code == get.status_code, (headers, params, get.text)
        assert head.content == b""
        statuses.append(get.status_code)

    assert statuses[0] == statuses[1] == statuses[-1] == 404
    assert statuses[2] == statuses[3] == statuses[4] == 401
    assert statuses[6] == statuses[7] == 200


async def test_a_foreign_page_may_head_a_public_style(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    map_id = await _map(client, admin_auth_header, "public")
    url = f"/maps/{map_id}/style.json"

    preflight = await client.options(
        url,
        headers={"Origin": _FOREIGN_ORIGIN, "Access-Control-Request-Method": "HEAD"},
    )
    head = await client.head(url, headers={"Origin": _FOREIGN_ORIGIN})

    assert preflight.status_code == head.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    methods = {
        m.strip() for m in preflight.headers["access-control-allow-methods"].split(",")
    }
    assert methods == {"GET", "HEAD", "OPTIONS"}
    assert head.headers["access-control-allow-origin"] == "*"


async def test_health_answers_head_like_get(client: AsyncClient) -> None:
    head = await client.head("/health")
    get = await client.get("/health")

    assert head.status_code != 405
    assert head.status_code == get.status_code
    assert head.content == b""
    assert head.headers["content-type"] == get.headers["content-type"]
    assert int(head.headers["content-length"]) > 0
