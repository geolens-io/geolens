"""A declined guard stops the shared orphan scan before any page is handled."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import app.platform.jobs.orphan_scan as orphan_scan
from app.platform.storage.provider import StoredObject

pytestmark = pytest.mark.anyio

PREFIX = "orphan-scan-guard-test/"


class FakeStorage:
    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        yield [
            StoredObject(key=f"{PREFIX}one", last_modified=datetime.now(timezone.utc))
        ]


async def _run(*, db) -> tuple[orphan_scan.ScanProgress | None, list[list[str]]]:
    handled: list[list[str]] = []

    async def handle_page(storage, prefix, page, last_examined):
        handled.append([obj.key for obj in page])
        return True, page[-1].key

    async def guard() -> bool:
        return False

    orphan_scan._scan_cursors.pop(PREFIX, None)
    with patch("app.platform.storage.get_storage", return_value=FakeStorage()):
        progress = await orphan_scan.reconcile_orphan_objects(
            prefix=PREFIX,
            lock_name="orphan-scan-guard-test",
            handle_page=handle_page,
            max_objects=10,
            db=db,
            guard=guard,
        )
    return progress, handled


async def test_a_declined_guard_skips_the_walk_without_a_session() -> None:
    progress, handled = await _run(db=None)
    assert progress is None
    assert handled == []


async def test_a_declined_guard_skips_the_walk_inside_a_session(
    test_db_session,
) -> None:
    progress, handled = await _run(db=test_db_session)
    assert progress is None
    assert handled == []
