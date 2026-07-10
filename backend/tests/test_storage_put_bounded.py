"""fix(#435): large-file paths must stay bounded and must not block the event loop.

`LocalStorageProvider.put()` called `data.read()` on the event-loop thread before its
thread handoff, so a COG, VRT, or archived original passed as an open file handle was
fully materialized as one `bytes` object — the raster, VRT, and original-file ingest
paths all do exactly that, and those artifacts can exceed the 2 GB container limit.
"""

import asyncio
import time
from pathlib import Path

import pytest

from app.platform.storage.local import LocalStorageProvider


class _RecordingReader:
    """Minimal file-like object that records every `read(size)` it is asked for.

    Deliberately not a `BufferedReader`: that would internally chunk a `read(-1)`
    into buffer-sized `readinto` calls and hide the whole-stream slurp this test
    exists to catch.
    """

    def __init__(self, total: int) -> None:
        self._remaining = total
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        if size is None or size < 0:
            size = self._remaining
        n = min(size, self._remaining)
        self._remaining -= n
        return b"\x00" * n


async def test_put_streams_a_file_handle_in_bounded_chunks(tmp_path: Path) -> None:
    provider = LocalStorageProvider(str(tmp_path))
    total = 8 * 1024 * 1024  # 8 MiB
    reader = _RecordingReader(total)

    path = await provider.put("big.bin", reader)

    assert Path(path).stat().st_size == total
    assert -1 not in reader.requested_sizes, (
        "put() called read() with no size — the whole payload was materialized as "
        "one bytes object before the thread handoff"
    )
    assert max(reader.requested_sizes) <= 1024 * 1024
    assert len(reader.requested_sizes) > 1


async def test_put_still_accepts_raw_bytes(tmp_path: Path) -> None:
    provider = LocalStorageProvider(str(tmp_path))

    path = await provider.put("small.bin", b"hello")

    assert Path(path).read_bytes() == b"hello"


async def test_put_does_not_stall_the_event_loop(tmp_path: Path) -> None:
    """A concurrent ticker keeps ticking while a blocking read is in flight."""
    provider = LocalStorageProvider(str(tmp_path))
    ticks = 0
    stop = False

    async def _ticker() -> None:
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(0.001)

    class _SlowReader:
        """Blocks inside read(), the way a real disk or network read would.

        Both access patterns take ~100ms in total: five 20ms sized reads, or one
        whole-stream `read(-1)`. Only the loop-thread variant starves the ticker.
        """

        def __init__(self) -> None:
            self._chunks = 5

        def read(self, size: int = -1) -> bytes:
            if size is None or size < 0:
                time.sleep(0.02 * self._chunks)
                data = b"\x00" * (1024 * self._chunks)
                self._chunks = 0
                return data
            if self._chunks == 0:
                return b""
            self._chunks -= 1
            time.sleep(0.02)
            return b"\x00" * 1024

    task = asyncio.create_task(_ticker())
    await asyncio.sleep(0.005)
    ticks_before = ticks

    await provider.put("slow.bin", _SlowReader())

    stop = True
    await task

    # ~100ms of blocking work against a 1ms ticker. Off the loop thread this yields
    # dozens of ticks; on it, essentially none. 10 is a wide margin against CI jitter.
    assert ticks - ticks_before >= 10, (
        f"the event loop ticked only {ticks - ticks_before} times during a ~100ms "
        "blocking read — put() is still reading on the loop thread"
    )


async def test_put_rejects_traversal_before_touching_the_filesystem(
    tmp_path: Path,
) -> None:
    """SEC-026 containment still runs before the thread handoff."""
    provider = LocalStorageProvider(str(tmp_path))

    with pytest.raises(ValueError):
        await provider.put("../escape.bin", b"x")
