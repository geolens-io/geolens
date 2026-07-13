"""Contract tests for provider-neutral data-serving extension hooks."""

from __future__ import annotations

import gzip
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request


def _reset_registry() -> None:
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry()
    yield
    _reset_registry()


@pytest.mark.asyncio
async def test_community_default_is_typed_and_has_no_serving_overrides():
    from app.platform.extensions import get_data_serving_extension
    from app.platform.extensions.defaults import DefaultDataServingExtension
    from app.platform.extensions.protocols import DataServingExtension

    extension = get_data_serving_extension()

    assert isinstance(extension, DefaultDataServingExtension)
    assert isinstance(extension, DataServingExtension)
    assert (
        await extension.prepare_table_for_read(
            table_name="roads",
            tenant_id="tenant-1",
        )
        is None
    )
    assert extension.get_tile_concurrency_limiter("tenant-1") is None
    assert extension.get_tile_cache_control() is None


class _Limiter:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    async def acquire(self) -> bool:
        self.acquired += 1
        return True

    def release(self) -> None:
        self.released += 1


class _RejectingLimiter(_Limiter):
    async def acquire(self) -> bool:
        self.acquired += 1
        return False


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeTileConnection:
    def transaction(self) -> _AsyncContext:
        return _AsyncContext(None)


class _FakeTilePool:
    def __init__(self) -> None:
        self.acquire_count = 0
        self.connection = _FakeTileConnection()

    def acquire(self) -> _AsyncContext:
        self.acquire_count += 1
        return _AsyncContext(self.connection)


class _HostedServingExtension:
    def __init__(
        self,
        *,
        expected_tenant_id: str = "tenant-1",
        cache_control: str = "public, max-age=300",
    ) -> None:
        self.limiter = _Limiter()
        self.prepared: list[tuple[str, str]] = []
        self.expected_tenant_id = expected_tenant_id
        self.cache_control = cache_control
        self.limiter_requests: list[str] = []

    async def prepare_table_for_read(self, *, table_name: str, tenant_id: str):
        from app.platform.extensions.protocols import TableReadinessResult

        self.prepared.append((table_name, tenant_id))
        return TableReadinessResult(status="warming", job_id="job-123")

    def get_tile_concurrency_limiter(self, tenant_id: str):
        self.limiter_requests.append(tenant_id)
        assert tenant_id == self.expected_tenant_id
        return self.limiter

    def get_tile_cache_control(self) -> str:
        return self.cache_control


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "expected_media_type"),
    [
        ("app.processing.tiles.router", "application/json"),
        ("app.standards.ogc.router", "application/json"),
    ],
)
async def test_read_paths_dispatch_warming_through_registered_extension(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    expected_media_type: str,
):
    import importlib

    import app.platform.extensions as ext_mod

    serving = _HostedServingExtension()
    ext_mod._extensions["data_serving"] = serving
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "is_multi_tenant", lambda: True)

    response = await module._check_cold_rehydrate(
        "roads",
        "cold",
        "tenant-1",
    )

    assert response is not None
    assert response.status_code == 202
    assert response.media_type == expected_media_type
    assert json.loads(response.body) == {"status": "warming", "job_id": "job-123"}
    assert serving.prepared == [("roads", "tenant-1")]


@pytest.mark.asyncio
async def test_hot_table_skips_registered_preparation(monkeypatch: pytest.MonkeyPatch):
    import app.platform.extensions as ext_mod
    from app.processing.tiles import router

    serving = _HostedServingExtension()
    ext_mod._extensions["data_serving"] = serving
    monkeypatch.setattr(router, "is_multi_tenant", lambda: True)

    assert await router._check_cold_rehydrate("roads", "published", "tenant-1") is None
    assert serving.prepared == []


def test_tile_controls_dispatch_through_registered_extension():
    import app.platform.extensions as ext_mod
    from app.processing.tiles.router import _get_tile_serving_controls

    serving = _HostedServingExtension()
    ext_mod._extensions["data_serving"] = serving

    limiter, cache_control = _get_tile_serving_controls("tenant-1")

    assert limiter is serving.limiter
    assert cache_control == "public, max-age=300"


@pytest.mark.parametrize("empty", [False, True])
def test_hosted_cache_override_never_publicizes_private_tiles(empty: bool):
    from app.processing.tiles.router import _serving_tile_headers

    override = "public, max-age=300"

    private_headers = _serving_tile_headers("private", 60, override, empty=empty)
    public_headers = _serving_tile_headers("public", 60, override, empty=empty)

    assert private_headers["Cache-Control"] == "private, max-age=60"
    assert public_headers["Cache-Control"] == override
    assert ("Content-Encoding" in private_headers) is (not empty)


@pytest.mark.asyncio
async def test_rejected_tile_limiter_never_queries_or_releases(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.processing.tiles import router as tile_router

    limiter = _RejectingLimiter()
    pool = _FakeTilePool()
    query = AsyncMock(return_value=b"unreachable")
    monkeypatch.setattr(tile_router, "get_tile_pool", lambda: pool)

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/tiles/data.roads/0/0/0.pbf",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1234),
            "scheme": "http",
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        await tile_router._acquire_and_serve_tile(
            request=request,
            table_name="roads",
            z=0,
            x=0,
            y=0,
            tid="tenant-1",
            schema="data_t_tenant_1",
            query_callable=query,
            tile_cache=None,
            cache_key="roads",
            cache_ttl=60,
            base_headers={},
            tenant_sem=limiter,
        )

    assert exc_info.value.status_code == 429
    assert limiter.acquired == 1
    assert limiter.released == 0
    assert pool.acquire_count == 0
    query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("tile_kind", ["vector", "cluster"])
@pytest.mark.parametrize("cache_hit", [False, True])
@pytest.mark.parametrize("cache_scope", ["public", "private"])
async def test_hosted_tile_endpoints_share_cache_policy_and_limit_only_db_misses(
    monkeypatch: pytest.MonkeyPatch,
    tile_kind: str,
    cache_hit: bool,
    cache_scope: str,
):
    """Vector and cluster endpoints must apply one hosted serving contract."""
    import app.platform.extensions as ext_mod
    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user
    from app.processing.tiles import router as tile_router

    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000123")
    table_name = f"hosted_{tile_kind}"
    cache_ttl = 47
    cache_override = "public, max-age=777"

    serving = _HostedServingExtension(
        expected_tenant_id=str(tenant_id),
        cache_control=cache_override,
    )
    ext_mod._extensions["data_serving"] = serving

    meta = tile_router._DatasetMeta(
        dataset_id=uuid.uuid4(),
        record_id=uuid.uuid4(),
        table_name=table_name,
        visibility="public" if cache_scope == "public" else "private",
        record_status="published",
        created_by=uuid.uuid4(),
        record_type="vector_dataset",
        geometry_type="Point",
        column_info=[],
        tile_cache_ttl=cache_ttl,
        tile_columns=None,
    )
    cache = SimpleNamespace(
        get=AsyncMock(return_value=gzip.compress(b"cached-mvt") if cache_hit else None),
        set=AsyncMock(),
    )
    pool = _FakeTilePool()
    vector_query = AsyncMock(return_value=b"vector-mvt")
    cluster_query = AsyncMock(return_value=b"cluster-mvt")

    monkeypatch.setattr(
        tile_router, "_resolve_dataset_meta", AsyncMock(return_value=meta)
    )
    monkeypatch.setattr(
        tile_router,
        "_authorize_vector_tile_request",
        AsyncMock(return_value=cache_scope),
    )
    monkeypatch.setattr(tile_router, "_require_tile_tenant_context", lambda: tenant_id)
    monkeypatch.setattr(tile_router, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tile_router, "get_tile_cache", lambda: cache)
    monkeypatch.setattr(tile_router, "get_tile_pool", lambda: pool)
    monkeypatch.setattr(tile_router, "set_tenant_role_for_tile_request", AsyncMock())
    monkeypatch.setattr(tile_router, "get_tile", vector_query)
    monkeypatch.setattr(tile_router, "get_cluster_tile", cluster_query)

    app = FastAPI()
    app.include_router(tile_router.router)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_optional_user] = lambda: None
    transport = ASGITransport(app=app)
    path = (
        f"/tiles/data.{table_name}/0/0/0.pbf"
        if tile_kind == "vector"
        else f"/tiles/clusters/data.{table_name}/0/0/0.pbf"
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 200
    expected_cache_control = (
        cache_override if cache_scope == "public" else f"private, max-age={cache_ttl}"
    )
    assert response.headers["Cache-Control"] == expected_cache_control
    assert serving.limiter_requests == [str(tenant_id)]

    expected_limit_count = 0 if cache_hit else 1
    assert serving.limiter.acquired == expected_limit_count
    assert serving.limiter.released == expected_limit_count
    assert pool.acquire_count == expected_limit_count

    selected_query = vector_query if tile_kind == "vector" else cluster_query
    other_query = cluster_query if tile_kind == "vector" else vector_query
    assert selected_query.await_count == expected_limit_count
    other_query.assert_not_awaited()
    assert cache.set.await_count == expected_limit_count
