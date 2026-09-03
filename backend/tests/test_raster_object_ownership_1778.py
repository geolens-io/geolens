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
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
        ):
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
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
        ):
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


class TestIdenticalReplacementKeepsTheLiveAsset:
    """fix(#1778 codex r1): a re-upload of the file the dataset already serves.

    The replacement converts to the same COG and hashes to the same
    ``asset_sha256``, so the three keys the replace tail intends to write are
    the three keys the live ``RasterAsset`` names. Before this, recording them
    as unpublished handed both stale-job passes permission to delete the served
    COG and its quicklooks after a crash, even one before the first put.
    """

    LIVE = [
        "rasters/dataset-1/samehash/source.cog.tif",
        "rasters/dataset-1/samehash/quicklook_256.png",
        "rasters/dataset-1/samehash/quicklook_512.png",
    ]

    @staticmethod
    def _session_double() -> tuple:
        session = AsyncMock()
        maker = MagicMock()
        maker.return_value.__aenter__ = AsyncMock(return_value=session)
        maker.return_value.__aexit__ = AsyncMock(return_value=False)
        return session, maker

    @pytest.mark.asyncio
    async def test_the_live_keys_are_never_recorded_as_unpublished(self) -> None:
        from app.processing.ingest.tasks_raster_common import (
            record_unpublished_storage_keys,
        )

        session, maker = self._session_double()
        with patch("app.core.db.async_session", maker):
            await record_unpublished_storage_keys(
                uuid.uuid4(),
                uuid.uuid4(),
                keys=list(self.LIVE),
                already_published=self.LIVE,
                job_id="j",
                task="reupload_raster",
            )

        # Nothing left to record, so no write at all.
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_genuinely_new_key_is_still_recorded(self) -> None:
        from app.processing.ingest.tasks_raster_common import (
            UNPUBLISHED_STORAGE_KEYS_FIELD,
            record_unpublished_storage_keys,
        )

        session, maker = self._session_double()
        fresh = "rasters/dataset-1/newhash/source.cog.tif"
        with patch("app.core.db.async_session", maker):
            await record_unpublished_storage_keys(
                uuid.uuid4(),
                uuid.uuid4(),
                keys=[fresh, *self.LIVE],
                already_published=self.LIVE,
                job_id="j",
                task="reupload_raster",
            )

        session.execute.assert_awaited_once()
        stmt = session.execute.await_args.args[0]
        recorded = stmt.compile().params["unpublished_patch"]
        assert recorded == {UNPUBLISHED_STORAGE_KEYS_FIELD: [fresh]}

    @pytest.mark.asyncio
    async def test_the_reaper_refuses_a_key_a_live_row_names(self) -> None:
        """The second half: it holds whatever the job row says.

        A job row written before the exclusion existed still names the live
        keys, and this is the pass that has to refuse them.
        """
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        orphan = "rasters/dataset-1/deadhash/source.cog.tif"
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set(self.LIVE)),
            ),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys(
                (*self.LIVE, orphan)
            )

        assert (reaped, skipped, failures) == (1, 3, 0)
        assert [call.args[0] for call in storage.delete.await_args_list] == [orphan]

    @pytest.mark.asyncio
    async def test_an_unreadable_catalog_deletes_nothing(self) -> None:
        """Leaking an object is recoverable; deleting a served raster is not."""
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(side_effect=RuntimeError("catalog unreadable")),
            ),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys(
                tuple(self.LIVE)
            )

        assert (reaped, skipped, failures) == (0, 3, 0)
        storage.delete.assert_not_awaited()

    def test_every_site_that_records_intended_keys_states_the_exclusion(self) -> None:
        """Enumerated rather than assumed: two writers, both answering."""
        found = set()
        for module in sorted((APP / "processing").rglob("*.py")):
            text = module.read_text()
            if "await record_unpublished_storage_keys(" not in text:
                continue
            rel = str(module.relative_to(APP))
            found.add(rel)
            assert text.count("await record_unpublished_storage_keys(") == text.count(
                "already_published="
            ), rel
        assert found == {
            "processing/ingest/tasks_raster.py",
            "processing/ingest/tasks_raster_replace.py",
        }, found


class TestLiveReferenceQuery:
    """The survivor check against a real catalog, not a double.

    The reaper's refusal is only as good as this query, and it spans four
    columns across two tables, so it is worth running rather than mocking.
    """

    @pytest.mark.anyio
    async def test_it_finds_every_column_that_names_an_object(
        self, test_db_session
    ) -> None:
        from app.modules.catalog.datasets.domain.models import Dataset, Record
        from app.platform.jobs.sweep import _live_referenced_storage_keys
        from app.processing.raster.models import DatasetAsset, RasterAsset

        record = Record(
            title="live raster",
            visibility="private",
            record_status="published",
            record_type="raster_dataset",
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=f"ds_{uuid.uuid4().hex[:12]}",
            srid=4326,
            source_format="geotiff",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()
        base = f"rasters/{dataset.id}/livehash"
        original = f"originals/{dataset.id}/livehash"
        test_db_session.add(
            RasterAsset(
                dataset_id=dataset.id,
                asset_uri=f"{base}/source.cog.tif",
                quicklook_256_uri=f"{base}/quicklook_256.png",
                quicklook_512_uri=f"{base}/quicklook_512.png",
                storage_backend="local",
            )
        )
        test_db_session.add(
            DatasetAsset(
                dataset_id=dataset.id,
                key="archived_original:livehash",
                href=original,
                media_type="image/tiff",
                roles=["archive"],
            )
        )
        await test_db_session.commit()

        orphan = f"rasters/{dataset.id}/deadhash/source.cog.tif"
        live = await _live_referenced_storage_keys(
            (
                f"{base}/source.cog.tif",
                f"{base}/quicklook_256.png",
                f"{base}/quicklook_512.png",
                original,
                orphan,
            )
        )

        assert live == {
            f"{base}/source.cog.tif",
            f"{base}/quicklook_256.png",
            f"{base}/quicklook_512.png",
            original,
        }
        assert orphan not in live


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
