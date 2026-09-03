"""Codebase audit 2026-08-30, pre-commit raster objects (tracked in #1778).

Two findings that share one subject, the ownership of an object written
before the transaction that would publish it:

- The COG, VRT and quicklook puts registered their key AFTER the write, so a
  cancelled put that had already completed (both storage providers drain the
  worker thread before re-raising) left an object nothing could name.
- Objects written under ``rasters/`` and ``originals/`` before the terminal
  commit had no out-of-process reaper, unlike the VRT generation prefix.
"""

import ast
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
                attempt_scope="dataset-1",
                job_id="j",
                task="reupload_raster",
            )

        # Nothing left to record, so no write at all.
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_genuinely_new_key_is_still_recorded(self) -> None:
        from app.processing.ingest.tasks_raster_common import (
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
                attempt_scope="dataset-1",
                job_id="j",
                task="reupload_raster",
            )

        session.execute.assert_awaited_once()
        stmt = session.execute.await_args.args[0]
        # fix(#1778 codex r9): the bind is the array the attempt appends; the
        # field name reaches the statement through jsonb_build_object, because
        # the value now concatenates onto whatever the row already names.
        recorded = stmt.compile().params["unpublished_patch"]
        assert recorded == [fresh]

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
        """Enumerated rather than assumed: three writers, all answering.

        fix(#1778 codex r4): `ingest_vrt` joined the set. Its keys sit under a
        dataset id it generates per task invocation, so its answer is the empty
        one, but it still has to give it.
        """
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
            "processing/ingest/tasks_vrt.py",
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


class TestAttemptScopedReplaceKeys:
    """fix(#1778 codex r3): the reaper's TOCTOU against a re-admitted replace.

    `fail_stale_jobs` commits once, and that commit settles the dead attempt
    AND releases the dataset's active-run reservation through the refresh-run
    sweep. The post-commit cleanup then runs with the door open: a replacement
    can be admitted, and while the reaper is between its survivor snapshot and
    its delete, that new attempt can write objects no row names yet. With keys
    derived from dataset id plus content hash alone, a retry of the same upload
    derived the SAME keys, so the reaper deleted the new attempt's bytes and
    the new attempt then committed a `RasterAsset` pointing at nothing.

    Closed by the key layout rather than by ordering, which is what the VRT
    publish path already does with `generations/{generation_id}/`. Ordering
    fixes here would have had to survive every future caller of the reaper; a
    key two attempts cannot both name has no window to order around.
    """

    DATASET = uuid.UUID("11111111-1111-1111-1111-111111111111")
    SHA = "b" * 64

    def _keys(self, attempt: uuid.UUID) -> list[str]:
        from app.processing.ingest.tasks_raster_common import (
            attempt_scoped_raster_base_key,
        )

        base = attempt_scoped_raster_base_key(self.DATASET, attempt, self.SHA)
        return [
            f"{base}/source.cog.tif",
            f"{base}/quicklook_256.png",
            f"{base}/quicklook_512.png",
        ]

    def test_two_attempts_of_the_same_upload_share_no_key(self) -> None:
        """Identical dataset, identical bytes, identical conversion."""
        first = self._keys(uuid.uuid4())
        second = self._keys(uuid.uuid4())
        assert set(first).isdisjoint(second)

    def test_the_key_still_carries_the_content_hash(self) -> None:
        """Invariant 10 rests on it: a replacement cannot overwrite in place."""
        for key in self._keys(uuid.uuid4()):
            assert self.SHA in key
            assert key.startswith(f"rasters/{self.DATASET}/")

    @pytest.mark.asyncio
    async def test_a_replacement_admitted_mid_reap_keeps_its_objects(self) -> None:
        """The review's scenario, end to end through the reaper.

        The stale attempt's keys are reaped and the newly admitted attempt's
        survive, even though nothing references either set at snapshot time.
        """
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        stale = self._keys(uuid.uuid4())
        admitted_mid_reap = self._keys(uuid.uuid4())

        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            # Neither set is referenced yet: the stale attempt rolled back and
            # the new one has not committed its pointer.
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys(
                tuple(stale)
            )

        assert (reaped, skipped, failures) == (3, 0, 0)
        deleted = {call.args[0] for call in storage.delete.await_args_list}
        assert deleted == set(stale)
        assert deleted.isdisjoint(admitted_mid_reap)

    @pytest.mark.asyncio
    async def test_a_key_outside_this_attempt_is_never_recorded(self) -> None:
        """The rule the recorded set must satisfy for the reaper to be safe.

        A future writer that derives a key two attempts can both name gets it
        dropped here rather than discovering the collision from a deleted
        raster.
        """
        from app.processing.ingest.tasks_raster_common import (
            record_unpublished_storage_keys,
        )

        attempt = uuid.uuid4()
        mine = self._keys(attempt)
        shared = f"rasters/{self.DATASET}/{self.SHA}/source.cog.tif"

        session = AsyncMock()
        maker = MagicMock()
        maker.return_value.__aenter__ = AsyncMock(return_value=session)
        maker.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.db.async_session", maker):
            await record_unpublished_storage_keys(
                uuid.uuid4(),
                attempt,
                keys=[*mine, shared],
                already_published=(),
                attempt_scope=str(attempt),
                job_id="j",
                task="reupload_raster",
            )

        session.execute.assert_awaited_once()
        stmt = session.execute.await_args.args[0]
        recorded = stmt.compile().params["unpublished_patch"]
        assert recorded == mine

    def test_the_replace_tail_derives_both_key_sets_from_the_one_helper(
        self,
    ) -> None:
        """Recording one prefix and writing another would be silent."""
        source = _source("processing/ingest/tasks_raster_replace.py")
        # Exactly two calls: the durable record and the put block. A third
        # would mean a third derivation to keep in step.
        assert source.count("attempt_scoped_raster_base_key(") == 2
        assert 'rasters/{dataset_uuid}/{asset_sha256}"' not in source
        assert 'rasters/{dataset.id}/{asset_sha256}"' not in source

    def test_the_first_ingest_tail_is_fenced_by_its_generated_dataset_id(
        self,
    ) -> None:
        """Its keys need no attempt segment, and this is why."""
        source = _source("processing/ingest/tasks_raster.py")
        lines = source.splitlines()
        generated = next(
            i
            for i, line in enumerate(lines)
            if "planned_dataset_id = uuid.uuid4()" in line
        )
        used = next(
            i
            for i, line in enumerate(lines)
            if i > generated and '_base_key = f"rasters/{planned_dataset_id}/' in line
        )
        scoped = next(
            i
            for i, line in enumerate(lines)
            if i > used and "attempt_scope=str(planned_dataset_id)" in line
        )
        assert generated < used < scoped


# (module path relative to backend/app, enclosing function) ->
# (expected put count, the durable owner that can name the key without this
# process). A site not listed here must call `record_unpublished_storage_keys`
# in the same function, before its puts. Counts are exact in both directions:
# a new put inside an already-justified function has to be argued for on its
# own rather than riding the existing entry, which is the rule
# `test_rule2_structural`'s allowlists follow for the same reason.
PUT_SITES_WITH_ANOTHER_OWNER: dict[tuple[str, str], tuple[int, str]] = {
    ("processing/ingest/tasks_vrt.py", "regenerate_vrt"): (
        3,
        "generation-scoped keys, rebuilt from the durable VrtGeneration row by "
        "_stale_generation_storage_keys in the job sweep (feat(#1267)) - the "
        "mechanism this finding's recorder was modelled on",
    ),
    ("processing/ingest/tasks_common.py", "_archive_original_file"): (
        1,
        "originals/{dataset_id}/: the first-ingest tail records it as intent "
        "(archived_original_uri under a dataset id it generates), and the "
        "replace tail deliberately does not, because the same content-derived "
        "key can already hold an earlier upload's archive that a live "
        "dataset_assets row names - archive_lossy_original's own pre-write "
        "probe is what decides that one",
    ),
    ("processing/ingest/tasks_common.py", "_generate_quicklook"): (
        1,
        "vectors/{dataset_id}/quicklook_256.png, written after the vector "
        "dataset row is committed, so delete_dataset's vectors/ prefix reap "
        "owns it (fix(#430 BA-17))",
    ),
    ("processing/ingest/service.py", "save_upload_file"): (
        2,
        "staging/: owned by the staging reconciler and the presigned-staging "
        "sweep, which start from the objects rather than from a row",
    ),
    ("processing/ingest/router.py", "_put_staging_object"): (
        1,
        "staging/: same two owners as save_upload_file",
    ),
    ("processing/export/artifact_cache.py", "_write"): (
        1,
        "the export artifact cache, reaped by its own TTL sweep",
    ),
}


class TestEveryPutSiteHasAnOwner:
    """fix(#1778 codex r4): no object may be written with nothing able to name it.

    The finding this file exists for is a key that outlives the process that
    could have deleted it. `written_storage_keys` is a local list, so any put
    before the terminal commit is one SIGKILL away from an orphan whose prefix
    embeds an id the rollback took away. `record_unpublished_storage_keys` is
    the answer for the three ingest tails; every other put site needs an owner
    that can reconstruct the key from something durable, and this is where that
    claim is written down instead of assumed.
    """

    @staticmethod
    def _put_sites() -> dict[tuple[str, str], int]:
        sites: dict[tuple[str, str], int] = {}
        for module in sorted((APP / "processing").rglob("*.py")):
            rel = str(module.relative_to(APP))
            stack: list[str] = []

            def walk(node: ast.AST) -> None:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        stack.append(child.name)
                        walk(child)
                        stack.pop()
                        continue
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "put"
                        and stack
                    ):
                        sites[(rel, stack[-1])] = sites.get((rel, stack[-1]), 0) + 1
                    walk(child)

            walk(ast.parse(module.read_text()))
        return sites

    @staticmethod
    def _records_intent(rel: str) -> set[str]:
        """Functions in one module that record their intended keys."""
        recording: set[str] = set()
        stack: list[str] = []

        def walk(node: ast.AST) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stack.append(child.name)
                    walk(child)
                    stack.pop()
                    continue
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "record_unpublished_storage_keys"
                    and stack
                ):
                    recording.add(stack[-1])
                walk(child)

        walk(ast.parse((APP / rel).read_text()))
        return recording

    def test_no_put_site_is_left_without_an_owner(self) -> None:
        unowned = []
        for (rel, func), count in sorted(self._put_sites().items()):
            if (rel, func) in PUT_SITES_WITH_ANOTHER_OWNER:
                continue
            if func in self._records_intent(rel):
                continue
            unowned.append(f"{rel}::{func} ({count} put(s))")
        assert not unowned, (
            "these storage puts have no owner that can name the key after the "
            "writing process is gone. Either record the intended keys with "
            "record_unpublished_storage_keys before the first put, or add a "
            "PUT_SITES_WITH_ANOTHER_OWNER entry naming the reaper that can "
            "reconstruct them:\n" + "\n".join(unowned)
        )

    def test_the_three_recording_tails_record_before_they_put(self) -> None:
        """Order matters as much as presence: a record after the put is lost."""
        for rel, func in (
            ("processing/ingest/tasks_raster.py", "ingest_raster"),
            ("processing/ingest/tasks_raster_replace.py", "reupload_raster"),
            ("processing/ingest/tasks_vrt.py", "ingest_vrt"),
        ):
            lines = (APP / rel).read_text().splitlines()
            record = next(
                i
                for i, line in enumerate(lines)
                if "await record_unpublished_storage_keys(" in line
            )
            first_put = next(
                i for i, line in enumerate(lines) if "await storage.put(" in line
            )
            assert record < first_put, f"{rel}::{func} records after its first put"

    def test_the_justifications_are_exact_in_both_directions(self) -> None:
        """A justified function may not silently acquire a second put."""
        sites = self._put_sites()
        for key, (expected, justification) in PUT_SITES_WITH_ANOTHER_OWNER.items():
            assert key in sites, f"stale allowlist entry: {key[0]}::{key[1]}"
            assert sites[key] == expected, (
                f"{key[0]}::{key[1]} has {sites[key]} puts, entry says {expected}"
            )
            assert len(justification) > 40, key


class TestRetentionPurgeIsTheLastOwner:
    """fix(#1778 codex r4): the row being deleted is the last thing naming these.

    The two stale-job passes only read the rows they move OFF `running`. A job
    that reached `failed` or `cancelled` on its own, whose in-process
    best-effort cleanup then failed once (a storage blip, a DROP that lost a
    lock race), keeps its objects and its output table with the record still
    pointing at them, and nothing looks again. The retention purge holds that
    pointer right up to the moment it discards it, so it is the last chance to
    use it.
    """

    KEY = "rasters/purged-ds/attempts/dead/abc/source.cog.tif"

    @pytest.mark.asyncio
    async def test_a_failed_job_whose_cleanup_raised_is_reaped_by_the_purge(
        self, monkeypatch
    ) -> None:
        from app.core.config import settings
        from app.platform.jobs.sweep import fail_stale_jobs

        monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
        purged_job_id = uuid.uuid4()
        mock_db = _mock_db_for_fail_stale(
            running_rows=[],
            purged_rows=[
                (
                    purged_job_id,
                    None,
                    {
                        "unpublished_storage_keys": [self.KEY],
                        "analysis_out_table": "parcels_buffered",
                    },
                )
            ],
        )
        storage = MagicMock()
        storage.delete = AsyncMock()
        analysis_reap = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.platform.jobs.sweep._reap_unadopted_analysis_outputs",
                analysis_reap,
            ),
            patch(
                "app.platform.jobs.sweep._clear_settled_artifact_records", AsyncMock()
            ),
        ):
            outcome = await fail_stale_jobs(mock_db, detailed=True)

        assert outcome._unpublished_storage_keys == (self.KEY,)
        assert [call.args[0] for call in storage.delete.await_args_list] == [self.KEY]
        # fix(#1778 codex r7): (job, table), so the drop can verify ownership.
        analysis_reap.assert_awaited_once_with(((purged_job_id, "parcels_buffered"),))

    @pytest.mark.asyncio
    async def test_a_purged_row_naming_a_live_key_deletes_nothing(
        self, monkeypatch
    ) -> None:
        """The survivor check applies to this door too.

        A row can be purged while the object it named is the one a dataset is
        serving: an ingest that succeeded and whose recorded intent was never
        cleared off the row still carries the published key.
        """
        from app.core.config import settings
        from app.platform.jobs.sweep import fail_stale_jobs

        monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
        mock_db = _mock_db_for_fail_stale(
            running_rows=[],
            purged_rows=[
                (uuid.uuid4(), None, {"unpublished_storage_keys": [self.KEY]})
            ],
        )
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value={self.KEY}),
            ),
            patch(
                "app.platform.jobs.sweep._clear_settled_artifact_records", AsyncMock()
            ),
        ):
            outcome = await fail_stale_jobs(mock_db, detailed=True)

        assert outcome._unpublished_storage_keys == (self.KEY,)
        storage.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_rolled_back_purge_deletes_nothing(self, monkeypatch) -> None:
        from app.core.config import settings
        from app.platform.jobs.sweep import fail_stale_jobs

        monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
        mock_db = _mock_db_for_fail_stale(
            running_rows=[],
            purged_rows=[
                (uuid.uuid4(), None, {"unpublished_storage_keys": [self.KEY]})
            ],
        )
        mock_db.commit.side_effect = RuntimeError("commit failed")
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
            pytest.raises(RuntimeError, match="commit failed"),
        ):
            await fail_stale_jobs(mock_db, detailed=True)

        storage.delete.assert_not_awaited()


class TestReapScalesAndStaysRetryable:
    """fix(#1778 codex r5): the two ways a whole sweep's worth of keys was lost.

    The survivor query expanded its key list into four `IN` clauses, so its
    argument count was four per key. Past roughly 8192 keys that crosses
    asyncpg's 32767-argument ceiling, the query raises, and the reaper's own
    "an unreadable catalog deletes nothing" rule skips every delete. That rule
    is right, but the retention purge had already committed the deletion of the
    rows that were those keys' last durable owners, so the objects leaked for
    good.
    """

    @pytest.mark.anyio
    async def test_ten_thousand_keys_run_as_one_argument(self, test_db_session) -> None:
        """Against real Postgres, so the argument ceiling is the real one.

        The survivor check has to still work at this size, not merely not
        raise: the live key is planted among ten thousand orphans and has to
        come back.
        """
        from app.modules.catalog.datasets.domain.models import Dataset, Record
        from app.platform.jobs.sweep import _live_referenced_storage_keys
        from app.processing.raster.models import RasterAsset

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
        live_key = f"rasters/{dataset.id}/attempts/live/abc/source.cog.tif"
        test_db_session.add(
            RasterAsset(
                dataset_id=dataset.id,
                asset_uri=live_key,
                storage_backend="local",
            )
        )
        await test_db_session.commit()

        keys = tuple(
            [
                f"rasters/{dataset.id}/attempts/dead-{i}/abc/source.cog.tif"
                for i in range(10_000)
            ]
            + [live_key]
        )
        assert len(keys) * 4 > 32_767, "the case has to exceed the bind ceiling"

        live = await _live_referenced_storage_keys(keys)

        assert live == {live_key}

    @pytest.mark.asyncio
    async def test_duplicate_keys_are_deleted_once(self) -> None:
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        key = "rasters/ds/attempts/a/abc/source.cog.tif"
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.platform.jobs.sweep._clear_settled_artifact_records", AsyncMock()
            ),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys(
                (key, key, key)
            )

        assert (reaped, skipped, failures) == (1, 0, 0)
        assert storage.delete.await_count == 1

    @pytest.mark.asyncio
    async def test_the_purge_will_not_delete_a_row_that_still_owns_an_artifact(
        self, monkeypatch
    ) -> None:
        """The durable pending-reap record, and why it is the job row.

        The reap runs after this function's commit and can fail as a whole. If
        the purge had already deleted the row, the pointer is gone and the
        objects leak; keeping the row until the artifacts are accounted for
        makes the failure retryable and costs no new table.
        """
        from sqlalchemy.sql.dml import Delete

        from app.core.config import settings
        from app.platform.jobs.sweep import fail_stale_jobs

        monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
        mock_db = _mock_db_for_fail_stale(
            running_rows=[],
            purged_rows=[
                (
                    uuid.uuid4(),
                    None,
                    {"unpublished_storage_keys": ["rasters/a/attempts/b/c/x.tif"]},
                )
            ],
        )
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
            patch(
                "app.platform.jobs.sweep._clear_settled_artifact_records", AsyncMock()
            ),
        ):
            await fail_stale_jobs(mock_db, detailed=True)

        deletes = [
            call.args[0]
            for call in mock_db.execute.await_args_list
            if isinstance(call.args[0], Delete)
        ]
        assert len(deletes) == 1
        where_sql = str(deletes[0].compile(compile_kwargs={"literal_binds": True}))
        assert "unpublished_storage_keys" in where_sql, (
            "the purge must exempt rows that still name an unreaped artifact, "
            "got: " + where_sql
        )
        assert "analysis_out_table" in where_sql

    @pytest.mark.asyncio
    async def test_a_delete_that_raised_keeps_its_record(self) -> None:
        """Only a final answer clears the row, and an error is not one."""
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        settled = AsyncMock()
        good = "rasters/ds/attempts/a/abc/quicklook_256.png"
        bad = "rasters/ds/attempts/a/abc/source.cog.tif"
        storage = MagicMock()
        storage.delete = AsyncMock(
            side_effect=lambda key: (
                (_ for _ in ()).throw(RuntimeError("no")) if key == bad else None
            )
        )
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", settled),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys((good, bad))

        assert (reaped, skipped, failures) == (1, 0, 1)
        settled.assert_awaited_once_with(storage_keys={good})

    @pytest.mark.asyncio
    async def test_a_refused_key_still_clears_its_record(self) -> None:
        """Refusing is a final answer too.

        A key a live row names is refused on every pass. Leaving it on the
        record would pin the job row for the life of the dataset.
        """
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        settled = AsyncMock()
        key = "rasters/ds/attempts/a/abc/source.cog.tif"
        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value={key}),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", settled),
        ):
            await reap_unpublished_storage_keys((key,))

        storage.delete.assert_not_awaited()
        settled.assert_awaited_once_with(storage_keys={key})

    @pytest.mark.asyncio
    async def test_a_failed_survivor_query_clears_nothing(self) -> None:
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        settled = AsyncMock()
        with (
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(side_effect=RuntimeError("catalog unreadable")),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", settled),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys(
                ("rasters/ds/attempts/a/abc/source.cog.tif",)
            )

        assert (reaped, skipped, failures) == (0, 1, 0)
        settled.assert_not_awaited()

    @pytest.mark.anyio
    async def test_clearing_takes_the_record_off_only_a_fully_settled_row(
        self, test_db_session
    ) -> None:
        """Against real Postgres: the containment test and the key removal.

        A row names all three of its objects at once, so clearing the field
        while one is unresolved would drop the other two from the record with
        it.
        """
        from sqlalchemy import select

        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import _clear_settled_artifact_records

        done = IngestJob(
            status="failed",
            file_path="",
            user_metadata={
                "unpublished_storage_keys": ["rasters/a/x.tif", "rasters/a/y.png"],
                "keep_me": True,
            },
        )
        partial = IngestJob(
            status="failed",
            file_path="",
            user_metadata={
                "unpublished_storage_keys": ["rasters/a/x.tif", "rasters/b/z.tif"]
            },
        )
        test_db_session.add_all([done, partial])
        await test_db_session.flush()
        # Snapshotted before the commit: it expires every instance, and the
        # next attribute read would be lazy I/O on an async session.
        done_id, partial_id = done.id, partial.id
        await test_db_session.commit()

        await _clear_settled_artifact_records(
            storage_keys={"rasters/a/x.tif", "rasters/a/y.png"}
        )

        test_db_session.expire_all()
        rows = {
            row.id: row.user_metadata
            for row in (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id.in_([done_id, partial_id]))
                )
            ).scalars()
        }
        assert rows[done_id] == {"keep_me": True}, (
            "a fully settled row loses the record and keeps everything else"
        )
        assert "unpublished_storage_keys" in rows[partial_id], (
            "a row with an unsettled key keeps its whole record for the retry"
        )


class TestTheRecordAccumulatesAcrossAttempts:
    """fix(#1778 codex r9): a retry used to forget the previous attempt's keys.

    `/jobs/{id}/retry` preserves `user_metadata`, so a retried ingest reached
    the recorder with attempt 1's keys still on the row. The JSONB merge set
    the field to attempt 2's keys alone, and an attempt whose own best-effort
    delete had also failed lost its objects' last durable pointer with it:
    neither stale pass nor the retention purge could name them afterwards.

    The record is a flat list each attempt extends. Which attempt wrote a key
    is not something any reader needs -- every one of them asks only whether a
    key is still owed a reap -- and keeping the shape a list is what lets a row
    written before this commit still reap.
    """

    @staticmethod
    async def _record(job_id, attempt_uuid, keys):
        from app.processing.ingest.tasks_raster_common import (
            record_unpublished_storage_keys,
        )

        await record_unpublished_storage_keys(
            job_id,
            attempt_uuid,
            keys=keys,
            already_published=(),
            attempt_scope="",
            job_id=str(job_id),
            task="ingest_raster",
        )

    @staticmethod
    async def _reload(session, job_id):
        from sqlalchemy import select

        from app.platform.jobs.models import IngestJob

        session.expire_all()
        return (
            await session.execute(select(IngestJob).where(IngestJob.id == job_id))
        ).scalar_one()

    @pytest.mark.anyio
    async def test_a_retry_keeps_the_previous_attempts_keys(
        self, test_db_session
    ) -> None:
        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import unpublished_storage_keys_from_metadata

        attempt_one, attempt_two = uuid.uuid4(), uuid.uuid4()
        job = IngestJob(status="failed", file_path="", attempt_id=attempt_one)
        test_db_session.add(job)
        await test_db_session.flush()
        job_id = job.id
        await test_db_session.commit()

        first = ["rasters/a/attempts/one/h/source.cog.tif"]
        await self._record(job_id, attempt_one, first)

        # The retry keeps user_metadata and takes a new attempt token.
        row = await self._reload(test_db_session, job_id)
        row.attempt_id = attempt_two
        await test_db_session.commit()

        second = ["rasters/a/attempts/two/h/source.cog.tif"]
        await self._record(job_id, attempt_two, second)

        row = await self._reload(test_db_session, job_id)
        assert unpublished_storage_keys_from_metadata(row.user_metadata) == tuple(
            first + second
        ), "attempt 1's objects lost their last durable pointer"

    @pytest.mark.anyio
    async def test_clearing_removes_only_the_settled_keys(
        self, test_db_session
    ) -> None:
        """A key whose delete raised keeps its place in the record."""
        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import (
            _clear_settled_artifact_records,
            unpublished_storage_keys_from_metadata,
        )

        settled = "rasters/a/attempts/one/h/source.cog.tif"
        unsettled = "rasters/a/attempts/two/h/source.cog.tif"
        job = IngestJob(
            status="failed",
            file_path="",
            user_metadata={
                "unpublished_storage_keys": [settled, unsettled],
                "keep_me": True,
            },
        )
        test_db_session.add(job)
        await test_db_session.flush()
        job_id = job.id
        await test_db_session.commit()

        await _clear_settled_artifact_records(storage_keys={settled})

        row = await self._reload(test_db_session, job_id)
        assert unpublished_storage_keys_from_metadata(row.user_metadata) == (
            unsettled,
        ), "the unsettled key must survive for the next sweep"
        assert row.user_metadata["keep_me"] is True

        await _clear_settled_artifact_records(storage_keys={unsettled})

        row = await self._reload(test_db_session, job_id)
        assert "unpublished_storage_keys" not in row.user_metadata, (
            "the field goes once nothing is owed, so the purge can take the row"
        )
        assert row.user_metadata["keep_me"] is True

    @pytest.mark.anyio
    async def test_both_attempts_keys_are_reaped_in_one_sweep(
        self, test_db_session
    ) -> None:
        """End to end: the pin the review asked for.

        Attempt 1 fails with a failed delete, the retry writes new keys, both
        attempts' keys are on the row, one sweep reaps both, and the record
        clears only for what it settled.
        """
        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        first = "rasters/a/attempts/one/h/source.cog.tif"
        second = "rasters/a/attempts/two/h/source.cog.tif"
        job = IngestJob(
            status="failed",
            file_path="",
            user_metadata={"unpublished_storage_keys": [first, second]},
        )
        test_db_session.add(job)
        await test_db_session.flush()
        job_id = job.id
        await test_db_session.commit()

        storage = MagicMock()
        storage.delete = AsyncMock()
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys(
                (first, second)
            )

        assert (reaped, skipped, failures) == (2, 0, 0)
        assert {call.args[0] for call in storage.delete.await_args_list} == {
            first,
            second,
        }
        row = await self._reload(test_db_session, job_id)
        assert "unpublished_storage_keys" not in row.user_metadata

    @pytest.mark.anyio
    async def test_a_row_written_before_this_commit_still_reaps(
        self, test_db_session
    ) -> None:
        """A plain list is the shape both before and after, by design."""
        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import (
            _clear_settled_artifact_records,
            unpublished_storage_keys_from_metadata,
        )

        legacy = "rasters/legacy/h/source.cog.tif"
        job = IngestJob(
            status="failed",
            file_path="",
            user_metadata={"unpublished_storage_keys": [legacy]},
        )
        test_db_session.add(job)
        await test_db_session.flush()
        job_id = job.id
        await test_db_session.commit()

        row = await self._reload(test_db_session, job_id)
        assert unpublished_storage_keys_from_metadata(row.user_metadata) == (legacy,)

        await _clear_settled_artifact_records(storage_keys={legacy})

        row = await self._reload(test_db_session, job_id)
        assert "unpublished_storage_keys" not in row.user_metadata

    def test_the_recorder_is_the_only_writer_of_the_record(self) -> None:
        """Enumerated, so a second writer cannot reintroduce the replace."""
        writers = set()
        for module in sorted(APP.rglob("*.py")):
            body = module.read_text()
            if "UNPUBLISHED_STORAGE_KEYS_FIELD" not in body:
                continue
            if "update(IngestJob)" in body or "UPDATE catalog.ingest_jobs" in body:
                writers.add(str(module.relative_to(APP)))
        assert writers == {
            "processing/ingest/tasks_raster_common.py",
            "platform/jobs/sweep.py",
        }, writers


def _mock_db_for_fail_stale(
    *, running_rows: list, purged_rows: list | None = None
) -> AsyncMock:
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

    # fix(#1778 codex r5): the exempted-row SELECT the purge issues first.
    # These fixtures drive the reaps through it rather than through the DELETE,
    # because a row that still names an artifact is deliberately NOT deleted.
    retained = MagicMock()
    # fix(#1778 codex r7): (id, user_metadata), because the analysis reap is
    # keyed on the owning job now rather than on a name two jobs could hold.
    retained.all.return_value = [
        (job_row_id, um) for (job_row_id, _fp, um) in (purged_rows or [])
    ]
    results.append(retained)

    purge = MagicMock()
    purge.all.return_value = []
    results.append(purge)
    # fix(#1778 codex r4): the purge only issues its survivor SELECT when a
    # deleted row carried a file_path, and these fixtures carry none.
    assert not any(row[1] for row in (purged_rows or [])), (
        "a purged row with a file_path adds one SELECT this double does not model"
    )

    post_expiry = MagicMock()
    post_expiry.all.return_value = []
    results.append(post_expiry)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=results)
    mock_db.commit = AsyncMock()
    return mock_db
