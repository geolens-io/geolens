"""Cancelling a service preview stops its ogrinfo child before anything it uses goes away."""

import asyncio
import contextlib

import pytest

from app.modules.catalog.sources import preview

pytestmark = pytest.mark.anyio


class _BlockedOgrinfo:
    """An ogrinfo whose output never arrives, recording how it is stopped."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.returncode: int | None = None
        self.communicating = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        self.communicating.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable: nothing releases the wait")

    def kill(self) -> None:
        self.events.append("kill")

    async def wait(self) -> int:
        # Long enough for a second cancellation to land while it is pending.
        await asyncio.sleep(0.05)
        self.events.append("wait")
        self.returncode = -9
        return self.returncode


async def test_cancelling_a_preview_reaps_ogrinfo_before_its_inputs_are_removed(
    monkeypatch,
):
    """The child is killed and awaited first, even if a second cancel lands mid-reap."""
    events: list[str] = []
    ogrinfo = _BlockedOgrinfo(events)

    async def spawn(*_args, **_kwargs):
        return ogrinfo

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(
        preview, "_remove_quietly", lambda _path: events.append("remove_inputs")
    )
    real_proxy = preview.service_egress_proxy

    @contextlib.asynccontextmanager
    async def recording_proxy(**kwargs):
        async with real_proxy(**kwargs) as egress:
            try:
                yield egress
            finally:
                events.append("close_proxy")

    monkeypatch.setattr(preview, "service_egress_proxy", recording_proxy)

    request = asyncio.create_task(
        preview.run_service_preview("WFS:https://wfs.preview-cancel.test/ows", "layer")
    )
    async with asyncio.timeout(10):
        await ogrinfo.communicating.wait()
    request.cancel()
    await asyncio.sleep(0)
    request.cancel()

    with pytest.raises(asyncio.CancelledError):
        await request

    assert events[:2] == ["kill", "wait"]
    assert set(events[2:]) == {"close_proxy", "remove_inputs"}
