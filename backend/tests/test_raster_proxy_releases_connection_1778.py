"""The raster proxy hands its API-pool connection back before Titiler (#1778).

``_resolve_raster_meta`` caches its snapshot under the REQUEST's ``v`` (#1329),
and ``_meta_cache_version_segment`` accepts any ASCII digit run of length 1 to
10, so a caller varying ``v`` misses that cache on every request and pays the
``db.execute``. The note at the key derivation priced that as one extra indexed
read. It was not: ``get_db`` yields one session for the whole request and only
rolls back on an exception, so the transaction that read opens is held until the
response is written, and ``raster_tile_proxy`` then awaits Titiler for up to
three attempts at a 30s timeout plus 0.5s and 1.0s of backoff. The connection is
one of ``db_pool_size + db_max_overflow`` per uvicorn worker, and once they are
all parked on an upstream fetch every other request in that worker waits out
``db_pool_timeout`` and then errors: login, search, the admin UI.

``/api/tiles/raster-proxy/...`` reaches this anonymously on any public raster,
which is why the vector path's fix(#1451) remedy applies here too. That one
states the same reasoning at ``_assert_dataset_still_registered`` and is pinned
by ``test_tile_cached_authz_liveness_1451.py``; this is its raster twin.

Order is the whole property, so order is what these tests read.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.processing.tiles import router as tile_router

pytestmark = pytest.mark.anyio


def _row(dataset_id: uuid.UUID) -> dict:
    """One catalog row in the shape `_resolve_raster_meta` reads."""
    return {
        "visibility": "public",
        "record_status": "published",
        "created_by": uuid.uuid4(),
        "record_type": "raster_dataset",
        "asset_uri": "rasters/probe.tif",
        "storage_backend": "local",
        "band_count": 1,
        "dtype": "uint8",
        "is_dem": False,
        "band_info": None,
        "nodata": None,
        "tile_cache_version": 1,
    }


class _RecordingSession:
    """A session that logs when it is queried and when it lets its connection go."""

    def __init__(self, events: list[str], row: dict) -> None:
        self._events = events
        self._row = row

    async def execute(self, *_args, **_kwargs):
        self._events.append("db.execute")
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(one_or_none=lambda: self._row)
        )

    async def rollback(self) -> None:
        self._events.append("db.rollback")


async def _fetch_tile(version: str | None) -> tuple[list[str], int]:
    """Serve one raster tile through the proxy, returning the event log."""
    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user_fail_open

    dataset_id = uuid.uuid4()
    events: list[str] = []
    session = _RecordingSession(events, _row(dataset_id))

    class _Upstream:
        async def get(self, _url):
            events.append("titiler.get")
            return SimpleNamespace(
                status_code=200,
                content=b"png",
                headers={"content-type": "image/png"},
            )

    app = FastAPI()
    app.include_router(tile_router.router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_optional_user_fail_open] = lambda: None

    path = f"/tiles/raster-proxy/{dataset_id}/1/2/3.png"
    if version is not None:
        path = f"{path}?v={version}"

    with patch.object(tile_router, "_titiler_client", _Upstream()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)

    return events, response.status_code


async def test_the_connection_is_released_before_the_upstream_fetch():
    """A cache-busting `v` reads the catalog, then lets go, then goes upstream."""
    events, status_code = await _fetch_tile("4294967295")

    assert status_code == 200, events
    assert events == ["db.execute", "db.rollback", "titiler.get"], (
        "the rollback must sit between the catalog read and the Titiler round "
        f"trip, or the pool connection is held across it. Got {events}"
    )


async def test_an_unversioned_request_releases_too():
    """The `?v=` shape is the cheap way in, not the only one.

    Any first request for a dataset misses `_raster_meta_cache` and pays the
    same read, so the release cannot be conditional on the parameter.
    """
    events, status_code = await _fetch_tile(None)

    assert status_code == 200, events
    assert events.index("db.rollback") < events.index("titiler.get"), events


async def test_the_release_is_in_the_shared_resolver_not_the_proxy():
    """Every caller of the resolver inherits it, including a future third one.

    ``raster_auth_check`` is a mounted route in its own right and
    ``raster_tile_proxy`` calls it in-process; putting the rollback in
    ``_resolve_raster_access`` covers both without either having to remember.
    """
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(tile_router._resolve_raster_access))
    rollbacks = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "rollback"
    ]
    assert rollbacks, (
        "_resolve_raster_access must release the connection itself. A call site "
        "cannot release what it did not know was taken."
    )
