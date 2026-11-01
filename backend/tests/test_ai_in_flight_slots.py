"""A user under a daily AI token cap holds at most two gated AI requests at once."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.persistent_config import MAX_AI_TOKENS_PER_USER_PER_DAY
from app.processing.ai import router as ai_router

CHAT_BODY = {
    "message": "Make the layer red",
    "map_id": "test-map-id",
    "layers": [],
}


class _HeldStreams:
    """A stubbed chat stream that stays open until released."""

    def __init__(self) -> None:
        self.entered = 0
        self.release = asyncio.Event()

    async def stream(self, *args, **kwargs):
        self.entered += 1
        await self.release.wait()
        yield {"type": "done", "explanation": "ok"}

    async def wait_for_entered(self, count: int) -> None:
        async with asyncio.timeout(5):
            while self.entered < count:
                await asyncio.sleep(0.01)


def _patch_cap(monkeypatch, cap: int) -> None:
    async def _fake_get(_db):
        return cap

    monkeypatch.setattr(MAX_AI_TOKENS_PER_USER_PER_DAY, "get", _fake_get)


def _stub_chat(held: _HeldStreams):
    return (
        patch("app.processing.ai.router._check_ai_available", new_callable=AsyncMock),
        patch(
            "app.processing.ai.router._validate_chat_layers",
            new_callable=AsyncMock,
            return_value=([], None, True),
        ),
        patch("app.processing.ai.router.stream_chat_edit", side_effect=held.stream),
    )


def _start_stream(client: AsyncClient, headers: dict) -> asyncio.Task:
    return asyncio.create_task(
        client.post("/ai/chat/stream/", json=CHAT_BODY, headers=headers)
    )


@pytest.mark.anyio
async def test_capped_user_is_refused_past_two_requests_in_flight(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    _patch_cap(monkeypatch, 10**12)
    held = _HeldStreams()
    a, b, c = _stub_chat(held)
    with a, b, c:
        first = _start_stream(client, admin_auth_header)
        second = _start_stream(client, admin_auth_header)
        try:
            await held.wait_for_entered(2)
            # A request let through would wait on the held stream; the timeout
            # turns that into a failure instead of a hang.
            async with asyncio.timeout(5):
                refused = await client.post(
                    "/ai/chat/stream/", json=CHAT_BODY, headers=admin_auth_header
                )
                # The slots are shared by every gated route, not counted per route.
                metadata = await client.post(
                    "/ai/metadata/summary/",
                    json={"dataset_id": "00000000-0000-0000-0000-000000000000"},
                    headers=admin_auth_header,
                )
        finally:
            held.release.set()
        assert refused.status_code == 429
        assert "in progress" in refused.json()["detail"]
        assert metadata.status_code == 429
        assert (await first).status_code == 200
        assert (await second).status_code == 200

        # Finished requests give their slots back.
        again = await client.post(
            "/ai/chat/stream/", json=CHAT_BODY, headers=admin_auth_header
        )
        assert again.status_code == 200


@pytest.mark.anyio
async def test_aborted_streams_release_their_slots(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    _patch_cap(monkeypatch, 10**12)
    held = _HeldStreams()
    a, b, c = _stub_chat(held)
    with a, b, c:
        me = await client.get("/auth/me/", headers=admin_auth_header)
        keys = [
            f"ai:in_flight:{me.json()['id']}:{slot}"
            for slot in range(ai_router._MAX_AI_REQUESTS_IN_FLIGHT)
        ]
        cache = ai_router.get_cache()

        tasks = [_start_stream(client, admin_auth_header) for _ in range(2)]
        try:
            await held.wait_for_entered(2)
            for key in keys:
                assert await cache.get(key) is not None
        finally:
            for task in tasks:
                task.cancel()
        for task in tasks:
            with pytest.raises(asyncio.CancelledError):
                await task

        for key in keys:
            assert await cache.get(key) is None

        held.release.set()
        resp = await client.post(
            "/ai/chat/stream/", json=CHAT_BODY, headers=admin_auth_header
        )
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_uncapped_requests_take_no_slot(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    _patch_cap(monkeypatch, 0)

    def _no_cache():
        raise AssertionError("an uncapped request must not touch the cache")

    monkeypatch.setattr(ai_router, "get_cache", _no_cache)
    held = _HeldStreams()
    a, b, c = _stub_chat(held)
    with a, b, c:
        tasks = [_start_stream(client, admin_auth_header) for _ in range(3)]
        await held.wait_for_entered(3)
        held.release.set()
        for task in tasks:
            assert (await task).status_code == 200
