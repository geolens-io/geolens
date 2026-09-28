"""An anonymous page on any origin can read a public COPC or 3D Tiles file.

The wildcard reaches only uncredentialed reads the route served, so a private
dataset's 404 carries none, and a credentialed read keeps the allowlist policy.
The preflight is answered by path, the same for a public, private or unknown id.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.pointcloud import pointcloud_attempt_key
from app.core.tiles3d import tileset_prefix
from app.platform.storage.local import LocalStorageProvider
from tests.factories import get_user_id
from tests.test_pointcloud_serving import _COPC, make_pointcloud  # noqa: F401
from tests.test_tiles3d_serving import _ROOT, make_tileset  # noqa: F401

_FOREIGN_ORIGIN = "https://foreign-asset-cors.example.org"
_ALLOWED_ORIGIN = "https://allowed-asset-cors.example.com"
_GLB = b"glTF" + bytes(range(64))

_TARGETS = ["copc", "tileset", "content"]


@pytest.fixture(autouse=True)
def allow_one_origin(monkeypatch):
    """Stubbed so no lookup fills the module's 30 s origins cache across workers."""

    async def _allow(_self, origin):
        return origin == _ALLOWED_ORIGIN

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _allow
    )


@pytest.fixture
def storage(tmp_path, monkeypatch) -> LocalStorageProvider:
    provider = LocalStorageProvider(base_dir=str(tmp_path))
    for module in ("router_pointcloud", "router_tiles3d"):
        monkeypatch.setattr(
            f"app.modules.catalog.datasets.api.{module}.get_storage",
            lambda: provider,
        )
    return provider


@pytest.fixture
def publish(make_pointcloud, make_tileset, storage):  # noqa: F811
    """Store one target's file and return its URL."""

    async def publish(target: str, *, visibility: str = "public") -> str:
        if target == "copc":
            dataset_id, attempt = await make_pointcloud(visibility=visibility)
            await storage.put(pointcloud_attempt_key(dataset_id, attempt), _COPC)
            return f"/datasets/{dataset_id}/copc/{attempt}/data.copc.laz"
        dataset_id = await make_tileset(visibility=visibility)
        prefix = f"{tileset_prefix(dataset_id)}a1/"
        await storage.put(f"{prefix}tileset.json", _ROOT)
        await storage.put(f"{prefix}tiles/0.glb", _GLB)
        path = "tileset.json" if target == "tileset" else "tiles/0.glb"
        return f"/datasets/{dataset_id}/tiles3d/{path}"

    return publish


def _listed(value: str | None) -> set[str]:
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


def _assert_public_answer(resp) -> None:
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resp.headers
    assert {"etag", "content-range", "accept-ranges"} <= _listed(
        resp.headers.get("access-control-expose-headers")
    )


def _preflight_headers(method: str = "GET") -> dict[str, str]:
    return {
        "Origin": _FOREIGN_ORIGIN,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "range, if-range",
    }


@pytest.mark.parametrize("target", _TARGETS)
async def test_an_anonymous_foreign_page_reads_a_public_file(
    client: AsyncClient, publish, target
) -> None:
    url = await publish(target)

    resp = await client.get(url, headers={"Origin": _FOREIGN_ORIGIN})

    assert resp.status_code == 200
    _assert_public_answer(resp)


async def test_an_anonymous_foreign_page_reads_a_range_and_heads_a_public_copc(
    client: AsyncClient, publish
) -> None:
    url = await publish("copc")

    ranged = await client.get(
        url, headers={"Origin": _FOREIGN_ORIGIN, "Range": "bytes=0-15"}
    )
    head = await client.head(url, headers={"Origin": _FOREIGN_ORIGIN})
    revalidated = await client.get(
        url,
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "If-None-Match": ranged.headers["etag"],
        },
    )

    assert ranged.status_code == 206
    assert ranged.content == _COPC[:16]
    assert head.status_code == 200
    assert revalidated.status_code == 304
    for resp in (ranged, head, revalidated):
        _assert_public_answer(resp)


@pytest.mark.parametrize("target", _TARGETS)
async def test_the_range_preflight_is_answered_alike_for_any_id(
    client: AsyncClient, publish, target
) -> None:
    """A private or unknown id gets the public id's preflight, so it reveals nothing."""
    public = await publish(target)
    private = await publish(target, visibility="private")
    unknown = public.replace(public.split("/")[2], str(uuid.uuid4()), 1)

    answers = [
        await client.options(url, headers=_preflight_headers())
        for url in (public, private, unknown)
    ]

    for resp in answers:
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in resp.headers
        assert {"range", "if-range"} <= _listed(
            resp.headers.get("access-control-allow-headers")
        )
        assert "get" in _listed(resp.headers["access-control-allow-methods"])
    policies = {
        tuple(
            sorted(
                (name, value)
                for name, value in resp.headers.items()
                if name.startswith("access-control-")
            )
        )
        for resp in answers
    }
    assert len(policies) == 1


@pytest.mark.parametrize("header", ["If-None-Match", "If-Match"])
@pytest.mark.parametrize("target", ["copc", "content"])
async def test_a_conditional_read_passes_the_preflight(
    client: AsyncClient, publish, target, header
) -> None:
    """Both routes honour these validators, so a page that sets one must be let through."""
    url = await publish(target)

    resp = await client.options(
        url,
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": header.lower(),
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert header.lower() in _listed(resp.headers.get("access-control-allow-headers"))


async def test_a_throttled_copc_read_is_readable_and_the_same_for_any_id(
    client: AsyncClient, publish, monkeypatch
) -> None:
    """The limit refuses before the dataset is read, so the 429 names no dataset."""
    from app.modules.catalog.datasets.api.router_pointcloud import _WHOLE_FILE_LIMIT
    from app.platform import ratelimit
    from tests.test_ogc_features_filter import _freeze_rate_limit_window

    _freeze_rate_limit_window(monkeypatch)
    monkeypatch.setattr(ratelimit, "get_cached_global_rate_limit", lambda: 1)
    public = await publish("copc")
    private = await publish("copc", visibility="private")
    unknown = public.replace(public.split("/")[2], str(uuid.uuid4()), 1)
    headers = {"Origin": _FOREIGN_ORIGIN}
    ratelimit.limiter.enabled = True
    ratelimit.limiter._storage.reset()
    try:
        for _ in range(int(_WHOLE_FILE_LIMIT.split("/")[0])):
            assert (await client.get(public, headers=headers)).status_code == 200
        refused = [
            await client.get(url, headers=headers) for url in (public, private, unknown)
        ]
    finally:
        ratelimit.limiter.enabled = False
        ratelimit.limiter._storage.reset()

    for resp in refused:
        assert resp.status_code == 429
        assert int(resp.headers["retry-after"]) > 0
        assert resp.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in resp.headers
        assert "retry-after" in _listed(resp.headers["access-control-expose-headers"])
    per_request = {"x-request-id", "date"}
    answers = {
        (
            resp.content,
            tuple(
                sorted(
                    (name, value)
                    for name, value in resp.headers.items()
                    if name not in per_request
                )
            ),
        )
        for resp in refused
    }
    assert len(answers) == 1


async def test_the_preflight_offers_head_only_where_the_route_serves_it(
    client: AsyncClient, publish
) -> None:
    copc = await client.options(
        await publish("copc"), headers=_preflight_headers("HEAD")
    )
    tileset = await client.options(
        await publish("tileset"), headers=_preflight_headers("HEAD")
    )

    assert copc.status_code == 200
    assert copc.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-origin" not in tileset.headers


@pytest.mark.parametrize("target", _TARGETS)
async def test_a_private_file_gets_no_wildcard(
    client: AsyncClient, publish, target
) -> None:
    url = await publish(target, visibility="private")

    resp = await client.get(url, headers={"Origin": _FOREIGN_ORIGIN})

    assert resp.status_code == 404
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize("target", _TARGETS)
async def test_a_bearer_read_keeps_the_allowlist_policy(
    client: AsyncClient, admin_auth_header: dict, publish, target
) -> None:
    url = await publish(target)

    foreign = await client.get(
        url, headers={**admin_auth_header, "Origin": _FOREIGN_ORIGIN}
    )
    allowed = await client.get(
        url, headers={**admin_auth_header, "Origin": _ALLOWED_ORIGIN}
    )

    assert foreign.status_code == allowed.status_code == 200
    assert "access-control-allow-origin" not in foreign.headers
    assert allowed.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("credential", ["api_key", "cookie"])
@pytest.mark.parametrize("target", _TARGETS)
async def test_other_credentials_get_no_wildcard(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    publish,
    target,
    credential,
) -> None:
    """A read the route still serves gets no wildcard once it carries a credential."""
    url = await publish(target)
    headers = {"Origin": _FOREIGN_ORIGIN}
    params = {}
    if credential == "cookie":
        headers["Cookie"] = "session=not-a-real-session"
    else:
        created = await client.post(
            "/admin/api-keys/",
            json={
                "user_id": str(await get_user_id(test_db_session, "admin")),
                "name": "asset cors reader",
            },
            headers=admin_auth_header,
        )
        assert created.status_code == 201
        params["api_key"] = created.json()["key"]

    resp = await client.get(url, headers=headers, params=params)

    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize("target", _TARGETS)
async def test_a_failed_precondition_is_readable_only_on_a_public_file(
    client: AsyncClient, publish, target
) -> None:
    headers = {"Origin": _FOREIGN_ORIGIN, "If-Match": '"stale"'}

    public = await client.get(await publish(target), headers=headers)
    private = await client.get(
        await publish(target, visibility="private"), headers=headers
    )

    assert public.status_code == 412
    _assert_public_answer(public)
    assert private.status_code == 404
    assert "access-control-allow-origin" not in private.headers


async def test_an_unsatisfiable_range_is_readable_only_on_a_public_copc(
    client: AsyncClient, publish
) -> None:
    headers = {"Origin": _FOREIGN_ORIGIN, "Range": f"bytes={len(_COPC)}-"}

    public = await client.get(await publish("copc"), headers=headers)
    private = await client.get(
        await publish("copc", visibility="private"), headers=headers
    )

    assert public.status_code == 416
    assert public.headers["content-range"] == f"bytes */{len(_COPC)}"
    _assert_public_answer(public)
    assert private.status_code == 404
    assert "access-control-allow-origin" not in private.headers


@pytest.mark.parametrize("target", _TARGETS)
async def test_a_storage_failure_is_readable_only_on_a_public_file(
    client: AsyncClient, publish, storage, target
) -> None:
    public_url = await publish(target)
    private_url = await publish(target, visibility="private")

    async def unreadable(*_args):
        raise OSError("unreadable")
        yield  # an async generator, like every provider's stream methods

    # Ranged, so the COPC read goes through get_range_stream; the tileset
    # route reads whole files through get_stream.
    storage.get_range_stream = unreadable
    storage.get_stream = unreadable
    headers = {"Origin": _FOREIGN_ORIGIN, "Range": "bytes=0-9"}
    public = await client.get(public_url, headers=headers)
    private = await client.get(private_url, headers=headers)

    assert public.status_code == 502
    assert public.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in public.headers
    assert private.status_code == 404
    assert "access-control-allow-origin" not in private.headers
