"""A prefix is deleted a page at a time with bounded deletes, and a dataset's reap outlives its request."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

import app.platform.storage.local as local_storage
from app.modules.catalog.datasets.api import router as datasets_router
from app.modules.catalog.datasets.domain.service_lifecycle import DatasetDeletion
from app.platform.storage import provider as storage_provider
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.provider import StoredObject
from app.platform.storage.reap import (
    MAX_DELETES_IN_FLIGHT,
    PrefixDeleteError,
    delete_prefix,
)


class _RecordingStorage:
    """Serves fixed pages and records each page read, each delete and the peak in flight."""

    def __init__(self, pages: list[list[str]], failing: frozenset[str] = frozenset()):
        self.pages = pages
        self.failing = failing
        self.events: list[tuple[str, object]] = []
        self.in_flight = 0
        self.peak = 0

    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        now = datetime.now(timezone.utc)
        for number, keys in enumerate(self.pages):
            self.events.append(("page", number))
            yield [StoredObject(key=key, last_modified=now) for key in keys]

    async def delete(self, key: str) -> None:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(0)
            if key in self.failing:
                raise OSError("delete refused")
            self.events.append(("deleted", key))
        finally:
            self.in_flight -= 1

    def deleted(self) -> set[str]:
        return {key for kind, key in self.events if kind == "deleted"}


class _HeldStorage:
    """Holds every delete until released, and signals once all expected deletes land."""

    def __init__(self, inner, expected: int) -> None:
        self.inner = inner
        self.expected = expected
        self.count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.emptied = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def delete(self, key: str) -> None:
        self.started.set()
        await self.release.wait()
        await self.inner.delete(key)
        self.count += 1
        if self.count == self.expected:
            self.emptied.set()


def _install(storage, monkeypatch):
    monkeypatch.setattr(storage_provider, "get_storage", lambda: storage)
    return storage


async def test_a_prefix_over_several_pages_is_emptied(tmp_path, monkeypatch):
    """Every object under the prefix goes, across page boundaries, and a neighbour stays."""
    monkeypatch.setattr(local_storage, "_OBJECT_PAGE_SIZE", 3)
    storage = _install(LocalStorageProvider(base_dir=str(tmp_path)), monkeypatch)
    prefix = f"tiles3d/{uuid.uuid4()}/"
    keys = [f"{prefix}a1/tileset.json"] + [
        f"{prefix}a1/tiles/{z}/{x}.glb" for z in range(3) for x in range(4)
    ]
    neighbour = f"tiles3d/{uuid.uuid4()}/a1/tileset.json"
    for key in (*keys, neighbour):
        await storage.put(key, b"{}")
    assert len([page async for page in storage.iter_object_pages(prefix)]) > 1

    assert await delete_prefix(prefix, tenant_id=None) == len(keys)

    assert await storage.list(prefix) == []
    assert await storage.exists(neighbour)


async def test_deletes_stay_bounded_and_finish_a_page_before_the_next(monkeypatch):
    """At most the limit of deletes run at once, and a page is done before the next is read."""
    pages = [[f"p{page}/k{index}" for index in range(40)] for page in range(3)]
    storage = _install(_RecordingStorage(pages), monkeypatch)

    assert await delete_prefix("tiles3d/x/", tenant_id=None) == 120

    assert storage.peak == MAX_DELETES_IN_FLIGHT
    for number in (1, 2):
        read_at = storage.events.index(("page", number))
        done_before = {
            key for kind, key in storage.events[:read_at] if kind == "deleted"
        }
        assert set(pages[number - 1]) <= done_before


async def test_a_failed_delete_does_not_stop_the_walk(monkeypatch):
    """The walk deletes everything it can, then reports how many deletes failed."""
    storage = _install(
        _RecordingStorage([["a", "b"], ["c", "d"]], failing=frozenset({"b"})),
        monkeypatch,
    )

    with pytest.raises(PrefixDeleteError, match="1 of 4 deletes") as raised:
        await delete_prefix("tiles3d/x/", tenant_id=None)

    assert storage.deleted() == {"a", "c", "d"}
    assert isinstance(raised.value.__cause__, OSError)


async def test_a_reap_outlives_its_cancelled_request(tmp_path, monkeypatch):
    """Cancelling the request after its commit does not stop the reap."""
    inner = LocalStorageProvider(base_dir=str(tmp_path))
    prefix = f"tiles3d/{uuid.uuid4()}/"
    keys = [f"{prefix}a1/tiles/{index}.glb" for index in range(20)]
    for key in keys:
        await inner.put(key, b"{}")
    storage = _install(_HeldStorage(inner, expected=len(keys)), monkeypatch)
    deletion = DatasetDeletion(
        table_name="tileset", storage_prefixes=(prefix,), tenant_id=None
    )

    request = asyncio.create_task(datasets_router._reap_after_commit(deletion))
    await asyncio.wait_for(storage.started.wait(), timeout=5)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    storage.release.set()

    await asyncio.wait_for(storage.emptied.wait(), timeout=5)
    await asyncio.gather(*datasets_router._reaps_in_flight)
    assert await inner.list(prefix) == []
