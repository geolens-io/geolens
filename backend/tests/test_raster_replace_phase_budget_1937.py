"""Raster replace's failure write bounds its wait on the job row, and contention keeps its own code.

DB tests need the test database.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from sqlalchemy import select

import app.core.db as db_module
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
)
from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_raster_replace
from app.processing.ingest.tasks_raster_replace import RasterReplaceError
from tests.test_replacement_post_commit import (
    _fresh_scalar,
    replace as replace,
    storage as storage,
)

pytestmark = pytest.mark.anyio

# Short enough that a held row outlasts it in under a second.
_TEST_BUDGET_MS = 400


class TestRasterRefreshErrorCode:
    """Pure mapping — no DB."""

    def test_a_contended_catalog_row_maps_to_its_own_code(self) -> None:
        code = tasks_raster_replace._raster_refresh_error_code(
            CatalogLockConflict("held")
        )
        assert code == CATALOG_LOCK_CONFLICT_CODE, (
            "a lock-contention failure reports as a bad raster, sending the "
            "reader to inspect a file that was never the problem"
        )

    def test_everything_else_keeps_its_path_code(self) -> None:
        assert (
            tasks_raster_replace._raster_refresh_error_code(RuntimeError("gdal"))
            == "raster_refresh_failed"
        )


async def test_a_failure_write_past_its_budget_leaves_the_replace_own_error(
    replace, monkeypatch
) -> None:
    """A failure write held past the shared budget gives up, and the replace raises its own error."""
    monkeypatch.setattr(
        "app.platform.jobs.heartbeat.JOB_ERROR_WRITE_TIMEOUT_MS", _TEST_BUDGET_MS
    )
    replacement = await replace("raster")
    holder = db_module.async_session()
    loop = asyncio.get_running_loop()
    held_at: list[float] = []

    async def _hold_the_job_row_then_fail(*args, **kwargs):
        await holder.execute(
            select(IngestJob.id)
            .where(IngestJob.id == replacement.job_id)
            .with_for_update()
        )
        held_at.append(loop.time())
        raise RasterReplaceError("the conversion failed")

    monkeypatch.setattr(
        tasks_raster_replace, "_convert_and_verify_cog", _hold_the_job_row_then_fail
    )
    sent = AsyncMock()
    try:
        with (
            patch("app.platform.notifications.events.emit_event_safe", new=sent),
            structlog.testing.capture_logs() as logs,
        ):
            with pytest.raises(RasterReplaceError, match="the conversion failed"):
                await asyncio.wait_for(replacement.run(), timeout=20)
        waited = loop.time() - held_at[0]
    finally:
        await holder.rollback()
        await holder.close()

    # The default budget is 10 s, so an exit well inside it shows this one held.
    assert waited < 5, f"the replace waited {waited:.1f}s on the held job row"

    expired = [e for e in logs if e["event"] == "job_error_write_timeout"]
    assert [e["budget_ms"] for e in expired] == [_TEST_BUDGET_MS]
    assert (
        await _fresh_scalar(
            select(IngestJob.status).where(IngestJob.id == replacement.job_id)
        )
        == "running"
    )
    sent.assert_not_awaited()
