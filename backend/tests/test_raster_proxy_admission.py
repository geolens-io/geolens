"""Uncached raster renders share a per-process budget; only unsent requests retry."""

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.processing.tiles import admission
from app.processing.tiles import router as tiles
from tests.test_raster_proxy_releases_connection_1778 import _RecordingSession, _row


class _Titiler:
    """Answers each call from ``outcomes`` in turn, recording every URL."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []

    async def get(self, url):
        self.urls.append(url)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


_PNG = SimpleNamespace(
    status_code=200, content=b"png", headers={"content-type": "image/png"}
)


@pytest.fixture(autouse=True)
def raster_budget(monkeypatch):
    """A one-slot raster budget and empty statistics caches for each test."""
    budget = admission._RenderBudget(1)
    monkeypatch.setattr(admission, "_raster_renders", budget)
    tiles._band_stats_cache.clear()
    tiles._band_stats_failures.clear()
    return budget


@pytest.fixture
def proxy(monkeypatch):
    """Return ``fetch(titiler, query="", visibility="public") -> response``."""
    from app.core.dependencies import get_db
    from app.modules.auth.dependencies import get_optional_user_fail_open

    async def fetch(titiler, query: str = "", visibility: str = "public"):
        row = {**_row(uuid.uuid4()), "visibility": visibility}
        app = FastAPI()
        app.include_router(tiles.router)
        app.dependency_overrides[get_db] = lambda: _RecordingSession([], row)
        app.dependency_overrides[get_optional_user_fail_open] = lambda: None
        monkeypatch.setattr(tiles, "_titiler_client", titiler)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                f"/tiles/raster-proxy/{uuid.uuid4()}/1/2/3.png{query}"
            )

    return fetch


@pytest.fixture
async def raster_budget_full(raster_budget):
    """Every raster slot is taken and the queue admits no one."""
    raster_budget.max_waiters = 0
    await raster_budget.slots.acquire()
    yield raster_budget
    raster_budget.slots.release()


@pytest.mark.parametrize("query", ["", "?stretch=percentile"])
async def test_a_full_budget_answers_429_without_calling_titiler(
    proxy, raster_budget_full, query
):
    titiler = _Titiler(_PNG)
    response = await proxy(titiler, query)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert response.headers["Cache-Control"] == "no-store"
    assert titiler.urls == [], "neither the statistics scan nor the render may run"


async def test_a_refused_request_does_not_queue_for_a_slot(proxy, raster_budget_full):
    titiler = _Titiler(_PNG)
    response = await proxy(titiler, visibility="private")

    assert response.status_code == 404
    assert titiler.urls == []


async def test_a_raster_render_does_not_take_a_vector_slot(proxy, monkeypatch):
    vector = admission._RenderBudget(1)
    vector.max_waiters = 0
    await vector.slots.acquire()
    monkeypatch.setattr(admission, "_vector_renders", vector)

    response = await proxy(_Titiler(_PNG))

    assert response.status_code == 200
    assert not admission._raster_renders.slots.locked()


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.WriteTimeout("write timed out"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
)
async def test_a_failure_after_the_request_was_sent_is_not_retried(proxy, error):
    titiler = _Titiler(error, _PNG)
    response = await proxy(titiler)

    assert response.status_code == 503
    assert len(titiler.urls) == 1
    assert not admission._raster_renders.slots.locked()


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.PoolTimeout("pool timed out"),
    ],
)
async def test_a_failure_before_the_request_was_sent_is_retried(proxy, error):
    titiler = _Titiler(error, _PNG)
    response = await proxy(titiler)

    assert response.status_code == 200
    assert len(titiler.urls) == 2


async def test_connect_failures_still_end_in_503(proxy):
    titiler = _Titiler(httpx.ConnectError("connection refused"))
    response = await proxy(titiler)

    assert response.status_code == 503
    assert len(titiler.urls) == 3


_STATS = SimpleNamespace(
    status_code=200,
    json=lambda: {"b1": {"percentile_2": 1.0, "percentile_98": 9.0}},
)


async def test_tiles_awaiting_one_statistics_scan_hold_no_slot(proxy, monkeypatch):
    """Only the shared scan holds a slot, so a second tile does not queue behind it."""
    monkeypatch.setattr(admission, "_SLOT_WAIT_SECONDS", 0.5)
    urls: list[str] = []

    class _SlowScan:
        async def get(self, url):
            urls.append(url)
            if "/statistics" in url:
                await asyncio.sleep(1.5)
                return _STATS
            return _PNG

    responses = await asyncio.gather(
        proxy(_SlowScan(), "?stretch=percentile"),
        proxy(_SlowScan(), "?stretch=percentile"),
    )

    assert [r.status_code for r in responses] == [200, 200]
    assert sum("/statistics" in url for url in urls) == 1


async def test_a_busy_budget_fails_the_scan_without_remembering_it(
    raster_budget_full, monkeypatch
):
    monkeypatch.setattr(
        "app.platform.storage.titiler_url._managed_prefix", lambda: "/data/"
    )
    titiler = _Titiler(_STATS)
    monkeypatch.setattr(tiles, "_titiler_client", titiler)

    with pytest.raises(tiles.HTTPException) as raised:
        await tiles._fetch_band_statistics("/data/busy.tif", 2.0, 98.0)

    assert raised.value.status_code == 429
    assert titiler.urls == []
    assert not tiles._band_stats_failures, "a busy budget must not pin the fallback"
