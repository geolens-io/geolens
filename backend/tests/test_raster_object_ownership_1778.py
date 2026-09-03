"""Codebase audit 2026-08-30, pre-commit raster objects (tracked in #1778).

Two findings that share one subject, the ownership of an object written
before the transaction that would publish it:

- The COG, VRT and quicklook puts registered their key AFTER the write, so a
  cancelled put that had already completed (both storage providers drain the
  worker thread before re-raising) left an object nothing could name.
- Objects written under ``rasters/`` and ``originals/`` before the terminal
  commit had no out-of-process reaper, unlike the VRT generation prefix.
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _source(rel: str) -> str:
    return (APP / rel).read_text()


class TestRegisterBeforeWrite:
    """Every ``written_storage_keys.append`` precedes the put it describes."""

    # (module, key expression) for each managed object a raster tail writes
    # before its terminal commit.
    SITES = [
        ("processing/ingest/tasks_raster.py", "_storage_cog_key"),
        ("processing/ingest/tasks_raster.py", "_storage_ql256_key"),
        ("processing/ingest/tasks_raster.py", "_storage_ql512_key"),
        ("processing/ingest/tasks_raster_replace.py", "_storage_cog_key"),
        ("processing/ingest/tasks_raster_replace.py", "_storage_ql256_key"),
        ("processing/ingest/tasks_raster_replace.py", "_storage_ql512_key"),
        ("processing/ingest/tasks_vrt.py", "_storage_vrt_key"),
        ("processing/ingest/tasks_vrt.py", "_storage_ql256_key"),
        ("processing/ingest/tasks_vrt.py", "_storage_ql512_key"),
        ("processing/ingest/tasks_vrt.py", "next_vrt_physical_key"),
        ("processing/ingest/tasks_vrt.py", "next_ql256_physical_key"),
        ("processing/ingest/tasks_vrt.py", "next_ql512_physical_key"),
    ]

    @pytest.mark.parametrize("module,key", SITES)
    def test_key_is_registered_before_its_put(self, module: str, key: str) -> None:
        lines = _source(module).splitlines()
        appends = [
            i
            for i, line in enumerate(lines)
            if f"written_storage_keys.append({key})" in line
        ]
        puts = [i for i, line in enumerate(lines) if f"storage.put({key}" in line]
        assert len(appends) == 1, f"{module}: {key} registered {len(appends)} times"
        assert len(puts) == 1, f"{module}: {key} put {len(puts)} times"
        assert appends[0] < puts[0], (
            f"{module}: {key} is registered after its put. A cancelled put can "
            "have completed on the provider, and CancelledError is a "
            "BaseException, so nothing below the put runs and the finished "
            "object is left with no reference."
        )


class TestUnpublishedStorageKeys:
    def test_both_raster_tails_record_their_keys_before_phase_2(self) -> None:
        """The write has to precede the phase-2 session, not sit inside it.

        Phase 2's first statements dirty the ingest_jobs row, so a second
        session writing that row while phase 2 held it would block until phase
        2 ended, and phase 2 would be waiting on the write.
        """
        for module in (
            "processing/ingest/tasks_raster.py",
            "processing/ingest/tasks_raster_replace.py",
        ):
            lines = _source(module).splitlines()
            record = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if "await record_unpublished_storage_keys(" in line
                ),
                None,
            )
            assert record is not None, f"{module} never records its keys"
            phase2 = next(i for i, line in enumerate(lines) if 'phase="phase2"' in line)
            assert record < phase2, f"{module} records its keys inside phase 2"

    @pytest.mark.parametrize(
        "metadata,expected",
        [
            (None, ()),
            ({}, ()),
            ({"unpublished_storage_keys": "rasters/x/y"}, ()),
            ({"unpublished_storage_keys": [1, None]}, ()),
            # Only the two managed prefixes, and no traversal: the value comes
            # out of a schemaless JSONB blob and drives a delete.
            ({"unpublished_storage_keys": ["staging/a/b"]}, ()),
            ({"unpublished_storage_keys": ["rasters/../secrets"]}, ()),
            (
                {"unpublished_storage_keys": ["rasters/a/b.tif", "originals/a/c"]},
                ("rasters/a/b.tif", "originals/a/c"),
            ),
        ],
    )
    def test_only_managed_keys_are_read_back(self, metadata, expected) -> None:
        from app.platform.jobs.sweep import unpublished_storage_keys_from_metadata

        assert unpublished_storage_keys_from_metadata(metadata) == expected

    @pytest.mark.asyncio
    async def test_the_post_commit_reap_deletes_them(self) -> None:
        from app.platform.jobs.sweep import (
            StaleCleanupOutcome,
            _reap_committed_staged_paths,
        )

        outcome = StaleCleanupOutcome(
            pending_failed=0,
            running_failed=1,
            vrt_assets_recovered=0,
            vrt_generations_failed=0,
            terminal_jobs_purged=0,
            staged_paths_considered=0,
            local_files_reaped=0,
            storage_objects_reaped=0,
            staged_paths_skipped=0,
            staged_cleanup_failures=0,
            _unpublished_storage_keys=(
                "rasters/d/abc/source.cog.tif",
                "originals/d/abc",
            ),
        )
        storage = MagicMock()
        storage.delete = AsyncMock()
        with patch("app.platform.storage.get_storage", return_value=storage):
            result = await _reap_committed_staged_paths(outcome)

        assert result.storage_objects_reaped == 2
        assert {call.args[0] for call in storage.delete.await_args_list} == {
            "rasters/d/abc/source.cog.tif",
            "originals/d/abc",
        }

    @pytest.mark.asyncio
    async def test_fail_stale_jobs_carries_them_out_of_a_running_row(self) -> None:
        """The keys reach the outcome, and only after the settling commit."""
        from app.platform.jobs.sweep import fail_stale_jobs

        keys = ["rasters/d/abc/source.cog.tif", "rasters/d/abc/quicklook_256.png"]
        mock_db = _mock_db_for_fail_stale(
            running_rows=[
                (uuid.uuid4(), {"unpublished_storage_keys": keys}, None),
            ]
        )
        storage = MagicMock()
        storage.delete = AsyncMock()
        with patch("app.platform.storage.get_storage", return_value=storage):
            outcome = await fail_stale_jobs(mock_db, detailed=True)

        assert outcome._unpublished_storage_keys == tuple(keys)
        assert {call.args[0] for call in storage.delete.await_args_list} == set(keys)

    @pytest.mark.asyncio
    async def test_a_rolled_back_settle_deletes_nothing(self) -> None:
        from app.platform.jobs.sweep import fail_stale_jobs

        mock_db = _mock_db_for_fail_stale(
            running_rows=[
                (
                    uuid.uuid4(),
                    {"unpublished_storage_keys": ["rasters/d/abc/source.cog.tif"]},
                    None,
                ),
            ]
        )
        mock_db.commit.side_effect = RuntimeError("commit failed")
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            pytest.raises(RuntimeError, match="commit failed"),
        ):
            await fail_stale_jobs(mock_db, detailed=True)

        storage.delete.assert_not_awaited()


def _mock_db_for_fail_stale(*, running_rows: list) -> AsyncMock:
    """A session double for ``fail_stale_jobs`` with real running-row metadata.

    The peer helper in ``test_vrt_stale_sweep_gap002`` hands every job row a
    ``None`` metadata blob, which is exactly the column these findings read, so
    this states the same execute() ordering with the rows filled in. Ordering,
    top to bottom: unbound pending UPDATE, bound pending UPDATE, running
    UPDATE, childless fan-out UPDATE, VRT generation UPDATE, two RasterAsset
    UPDATEs, two refresh-run UPDATEs, the retention purge DELETE, and the
    post-expiry presigned SELECT.
    """
    results = []

    unbound = MagicMock()
    unbound.all.return_value = []
    results.append(unbound)

    bound = MagicMock()
    bound.all.return_value = []
    results.append(bound)

    running = MagicMock()
    running.all.return_value = list(running_rows)
    results.append(running)

    fanout = MagicMock()
    fanout.scalars.return_value = []
    results.append(fanout)

    generations = MagicMock()
    generations.all.return_value = []
    results.append(generations)

    for _ in range(4):
        result = MagicMock()
        result.scalars.return_value = []
        results.append(result)

    purge = MagicMock()
    purge.all.return_value = []
    results.append(purge)

    post_expiry = MagicMock()
    post_expiry.all.return_value = []
    results.append(post_expiry)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=results)
    mock_db.commit = AsyncMock()
    return mock_db
