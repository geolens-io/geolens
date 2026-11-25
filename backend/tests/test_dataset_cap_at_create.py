"""The dataset-count cap is checked where a dataset is created, not at upload.

An upload door cannot tell a new dataset from a replacement or an unused
file, so it charges bytes only. The count cap answers at the import commit
and at a manifest entry classified as a create.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.quota.service import (
    DatasetQuotaExceededError,
    get_user_quota_usage,
)
from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY, IngestJob
from tests.factories import create_dataset
from tests.test_manifest_reapply_publication import _reupload_task
from tests.test_manifest_upload_source import (
    _ORIGINAL,
    _RESURVEYED,
    _apply,
    _checksum,
    _complete,
    _entry,
    _manifest,
    _row,
    _staged_row,
    _upload,
    _user_id,
)

pytestmark = pytest.mark.anyio

AT_CAP = "Dataset quota exceeded: 1 of 1 datasets used"


@contextmanager
def _caps(datasets: int, storage_bytes: int = 0):
    with (
        patch(
            "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
            new=AsyncMock(return_value=datasets),
        ),
        patch(
            "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
            new=AsyncMock(return_value=storage_bytes),
        ),
    ):
        yield


async def _dataset_count(session, user_id: uuid.UUID) -> int:
    return (await get_user_quota_usage(session, user_id)).dataset_count


async def _published(client, headers, session, key: str) -> uuid.UUID:
    """A dataset an earlier version 2 apply of ``key`` created for the caller."""
    first = await _upload(client, headers)
    await _apply(client, headers, _manifest(_entry(key, first, _checksum(_ORIGINAL))))
    owner = (await _row(session, first)).created_by
    return await _complete(session, first, owner)


class _PlanPort:
    """An entitlement port that records each limit it is asked about.

    ``dataset_limit`` stands for a paid plan's own dataset cap: asking for
    more datasets than it allows is refused, as an overlay would.
    """

    def __init__(self, dataset_limit: int | None = None) -> None:
        self.dataset_limit = dataset_limit
        self.asked: list[tuple[str, int]] = []

    async def has_feature(self, feature: str) -> bool:
        return True

    async def enforce_limit(self, dimension: str, n: int) -> None:
        self.asked.append((dimension, n))
        if (
            dimension == "dataset_count"
            and self.dataset_limit is not None
            and n > self.dataset_limit
        ):
            raise HTTPException(status_code=402, detail="Plan dataset limit reached")

    def datasets_asked(self) -> list[int]:
        return [n for dimension, n in self.asked if dimension == "dataset_count"]


@contextmanager
def _plan(port: _PlanPort):
    with patch(
        "app.platform.extensions.entitlement.get_entitlement_port", return_value=port
    ):
        yield port


async def _commit(client: AsyncClient, headers: dict, job_id: uuid.UUID):
    with patch(
        "app.processing.ingest.router.queue_ingest_job", new=AsyncMock()
    ) as queue:
        response = await client.post(
            f"/ingest/commit/{job_id}", json={"title": "Capitals"}, headers=headers
        )
    return response, queue.await_count


class TestManifestRepublishAtTheCap:
    async def test_an_unchanged_republish_is_a_skip(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        await _published(client, editor_auth_header, test_db_session, "cap-unchanged")

        with _caps(1):
            again = await _upload(client, editor_auth_header)
            result = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("cap-unchanged", again, _checksum(_ORIGINAL))),
            )

        assert (result["action"], result["queued"]) == ("skip", 0)

    async def test_new_data_replaces_the_dataset(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        dataset_id = await _published(
            client, editor_auth_header, test_db_session, "cap-replace"
        )

        with _caps(1), _reupload_task() as task:
            second = await _upload(client, editor_auth_header, _RESURVEYED)
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(_entry("cap-replace", second, _checksum(_RESURVEYED))),
                headers=editor_auth_header,
            )

        [result] = response.json()["results"]
        assert (result["action"], result["dataset_id"]) == ("update", str(dataset_id))
        task.defer_async.assert_awaited_once()
        editor = await _user_id(client, editor_auth_header)
        assert await _dataset_count(test_db_session, editor) == 1

    async def test_a_create_entry_is_refused_and_its_sibling_update_runs(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        dataset_id = await _published(
            client, editor_auth_header, test_db_session, "cap-kept"
        )

        with (
            _caps(1),
            _reupload_task() as task,
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            new = await _upload(client, editor_auth_header)
            changed = await _upload(client, editor_auth_header, _RESURVEYED)
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(
                    _entry("cap-new", new, _checksum(_ORIGINAL)),
                    _entry("cap-kept", changed, _checksum(_RESURVEYED)),
                ),
                headers=editor_auth_header,
            )

        assert response.status_code == 200, response.text
        refused, updated = response.json()["results"]
        assert (refused["dataset_key"], refused["action"]) == ("cap-new", "error")
        assert AT_CAP in refused["message"]
        assert (updated["action"], updated["dataset_id"]) == (
            "update",
            str(dataset_id),
        )
        queue.assert_not_awaited()
        task.defer_async.assert_awaited_once()
        # The refused entry never claimed its upload.
        unclaimed = await _row(test_db_session, new)
        assert unclaimed.status == "pending"
        assert "manifest_key" not in unclaimed.user_metadata

    async def test_several_creates_one_below_the_cap_admit_only_the_first(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        await _published(client, editor_auth_header, test_db_session, "cap-existing")

        with (
            _caps(2),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            uploads = [await _upload(client, editor_auth_header) for _ in range(3)]
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(
                    *(
                        _entry(f"cap-batch-{index}", job_id, _checksum(_ORIGINAL))
                        for index, job_id in enumerate(uploads)
                    )
                ),
                headers=editor_auth_header,
            )

        results = response.json()["results"]
        assert [result["action"] for result in results] == ["create", "error", "error"]
        for refused in results[1:]:
            assert "Dataset quota exceeded: 2 of 2 datasets used" in refused["message"]
        assert queue.await_count == 1

    async def test_a_dataset_created_while_the_entry_stages_is_seen_at_admission(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        import app.core.db as db_module
        from app.processing.ingest import manifest_service

        await _published(client, editor_auth_header, test_db_session, "cap-raced")
        editor = await _user_id(client, editor_auth_header)
        claim = manifest_service.claim_upload_source

        async def _claim_after_another_create(*args, **kwargs):
            async with db_module.async_session() as other:
                await create_dataset(other, created_by=editor)
            return await claim(*args, **kwargs)

        with (
            _caps(2),
            patch.object(
                manifest_service, "claim_upload_source", _claim_after_another_create
            ),
        ):
            job_id = await _upload(client, editor_auth_header)
            result = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("cap-raced-new", job_id, _checksum(_ORIGINAL))),
            )

        assert (result["action"], result["queued"]) == ("error", 0)
        assert "Dataset quota exceeded: 2 of 2 datasets used" in result["message"]


async def _results(client: AsyncClient, headers: dict, manifest: dict) -> list[dict]:
    with (
        _reupload_task(),
        patch(
            "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
        ),
    ):
        response = await client.post(
            "/ingest/manifest/apply", json=manifest, headers=headers
        )
    assert response.status_code == 200, response.text
    return response.json()["results"]


class TestManifestDryRun:
    """A preview answers for the cap as the apply would, and writes nothing."""

    async def test_a_create_is_refused_and_its_sibling_update_is_previewed(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        dataset_id = await _published(
            client, editor_auth_header, test_db_session, "dry-kept"
        )

        with _caps(1), _plan(_PlanPort()) as port:
            new = await _upload(client, editor_auth_header)
            changed = await _upload(client, editor_auth_header, _RESURVEYED)
            entries = (
                _entry("dry-new", new, _checksum(_ORIGINAL)),
                _entry("dry-kept", changed, _checksum(_RESURVEYED)),
            )
            previewed = await _results(
                client, editor_auth_header, _manifest(*entries, dry_run=True)
            )
            untouched = [await _row(test_db_session, job) for job in (new, changed)]
            applied = await _results(client, editor_auth_header, _manifest(*entries))

        refused, updated = previewed
        assert refused["action"] == "error" and AT_CAP in refused["message"]
        assert (updated["action"], updated["dataset_id"], updated["message"]) == (
            "update",
            str(dataset_id),
            "Manifest dataset would be updated.",
        )
        for job in untouched:
            assert job.status == "pending" and "manifest_key" not in job.user_metadata
        # The preview's refusal is the apply's.
        assert (applied[0]["action"], applied[0]["message"], applied[0]["errors"]) == (
            "error",
            refused["message"],
            refused["errors"],
        )
        assert applied[1]["action"] == "update"
        # The core cap refused the create before the plan was asked, and an
        # update never asks.
        assert port.datasets_asked() == []

    @pytest.mark.parametrize(
        ("cap", "actions"),
        [(2, ["create", "error"]), (3, ["create", "create"])],
        ids=["one-below-the-cap", "below-the-cap"],
    )
    async def test_creates_are_counted_across_the_manifest(
        self,
        cap,
        actions,
        client: AsyncClient,
        editor_auth_header,
        test_db_session,
        clean_tables,
    ):
        await _published(client, editor_auth_header, test_db_session, "dry-existing")

        with _caps(cap), _plan(_PlanPort()) as port:
            uploads = [await _upload(client, editor_auth_header) for _ in range(2)]
            previewed = await _results(
                client,
                editor_auth_header,
                _manifest(
                    *(
                        _entry(f"dry-batch-{index}", job_id, _checksum(_ORIGINAL))
                        for index, job_id in enumerate(uploads)
                    ),
                    dry_run=True,
                ),
            )

        assert [result["action"] for result in previewed] == actions
        assert previewed[0]["message"] == "Manifest dataset would be created."
        if actions[1] == "error":
            assert (
                "Dataset quota exceeded: 2 of 2 datasets used"
                in (previewed[1]["message"])
            )
        # One question per create the core cap admits, counting the earlier ones.
        assert port.datasets_asked() == [2, 3][: actions.count("create")]


class TestImportCommitAtTheCap:
    async def test_the_upload_is_accepted_and_the_commit_refused(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)

        with _caps(1):
            job_id = await _upload(client, editor_auth_header)
            refused, queued = await _commit(client, editor_auth_header, job_id)

        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == AT_CAP
        assert queued == 0
        job = await _row(test_db_session, job_id)
        assert job.status == "pending"
        assert COMMIT_ATTEMPTED_METADATA_KEY not in job.user_metadata

        # The refused job is still committable once the account has room.
        with _caps(2):
            admitted, queued = await _commit(client, editor_auth_header, job_id)
        assert (admitted.status_code, queued) == (202, 1)

    async def test_below_the_cap_the_upload_and_the_commit_succeed(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)

        with _caps(2):
            job_id = await _upload(client, editor_auth_header)
            admitted, queued = await _commit(client, editor_auth_header, job_id)

        assert (admitted.status_code, queued) == (202, 1), admitted.text

    async def test_an_upload_staged_below_the_cap_is_refused_once_it_is_reached(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)

        with _caps(1):
            job_id = await _upload(client, editor_auth_header)
            await create_dataset(test_db_session, created_by=editor)
            refused, queued = await _commit(client, editor_auth_header, job_id)

        assert (refused.status_code, queued) == (422, 0), refused.text
        assert refused.json()["detail"] == AT_CAP

    async def test_a_fan_out_is_refused_and_leaves_the_job_pending(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)

        with (
            _caps(1),
            patch(
                "app.platform.jobs.defer_guard.defer_with_orphan_guard",
                new=AsyncMock(),
            ),
        ):
            job_id = await _upload(client, editor_auth_header)
            await test_db_session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(
                    user_metadata=IngestJob.user_metadata.op("||")(
                        {"all_layers": ["capitals"]}
                    )
                )
            )
            await test_db_session.commit()
            refused = await client.post(
                f"/ingest/commit-fan-out/{job_id}",
                json={"layers": [{"layer_name": "capitals"}]},
                headers=editor_auth_header,
            )

        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == AT_CAP
        assert (await _row(test_db_session, job_id)).status == "pending"


class TestByteCapStaysAtUpload:
    async def test_an_upload_over_the_byte_cap_is_refused_with_413(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)

        # At the count cap too: the upload door still answers for bytes alone.
        with _caps(1, storage_bytes=len(_ORIGINAL) - 1):
            response = await client.post(
                "/ingest/upload",
                files={"file": ("capitals.geojson", _ORIGINAL, "application/geo+json")},
                headers=editor_auth_header,
            )

        assert response.status_code == 413, response.text
        assert response.json()["detail"].startswith("Storage quota exceeded")


class TestEntitlementSeam:
    """A paid overlay's own limits sit behind ``enforce_limit``."""

    async def test_a_republish_never_asks_for_another_dataset(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        dataset_id = await _published(
            client, editor_auth_header, test_db_session, "plan-republish"
        )

        with _plan(_PlanPort(dataset_limit=1)) as port, _reupload_task():
            again = await _upload(client, editor_auth_header)
            unchanged = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("plan-republish", again, _checksum(_ORIGINAL))),
            )
            second = await _upload(client, editor_auth_header, _RESURVEYED)
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(
                    _entry("plan-republish", second, _checksum(_RESURVEYED))
                ),
                headers=editor_auth_header,
            )

        [replaced] = response.json()["results"]
        assert unchanged["action"] == "skip"
        assert (replaced["action"], replaced["dataset_id"]) == (
            "update",
            str(dataset_id),
        )
        assert port.datasets_asked() == []
        assert "storage_bytes" in {dimension for dimension, _ in port.asked}

    async def test_a_manifest_create_asks_and_its_sibling_update_does_not(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        dataset_id = await _published(
            client, editor_auth_header, test_db_session, "plan-kept"
        )

        with (
            _plan(_PlanPort(dataset_limit=1)) as port,
            _reupload_task() as task,
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            new = await _upload(client, editor_auth_header)
            changed = await _upload(client, editor_auth_header, _RESURVEYED)
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(
                    _entry("plan-new", new, _checksum(_ORIGINAL)),
                    _entry("plan-kept", changed, _checksum(_RESURVEYED)),
                ),
                headers=editor_auth_header,
            )

        refused, updated = response.json()["results"]
        assert refused["action"] == "error"
        assert "Plan dataset limit reached" in refused["message"]
        assert (updated["action"], updated["dataset_id"]) == (
            "update",
            str(dataset_id),
        )
        assert port.datasets_asked() == [2]
        queue.assert_not_awaited()
        task.defer_async.assert_awaited_once()

    async def test_a_create_refused_by_the_plan_keeps_its_upload_for_the_next_apply(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        await _published(client, editor_auth_header, test_db_session, "plan-full")
        job_id = await _upload(client, editor_auth_header)
        manifest = _manifest(_entry("plan-later", job_id, _checksum(_ORIGINAL)))

        with _plan(_PlanPort(dataset_limit=1)) as port:
            refused = await _apply(client, editor_auth_header, manifest)
            unclaimed = await _row(test_db_session, job_id)
            port.dataset_limit = 2
            admitted = await _apply(client, editor_auth_header, manifest)

        assert (refused["action"], refused["queued"]) == ("error", 0)
        assert "Plan dataset limit reached" in refused["message"]
        assert unclaimed.status == "pending"
        assert "manifest_key" not in unclaimed.user_metadata
        assert (admitted["action"], admitted["job_id"], admitted["queued"]) == (
            "create",
            str(job_id),
            1,
        )
        assert set(port.datasets_asked()) == {2}

    async def test_an_import_asks_at_the_commit_and_not_at_the_upload(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)

        with _plan(_PlanPort()) as port:
            job_id = await _upload(client, editor_auth_header)
            at_upload = port.datasets_asked()
            admitted, _queued = await _commit(client, editor_auth_header, job_id)

        assert admitted.status_code == 202, admitted.text
        assert at_upload == []
        assert port.datasets_asked() == [2]


async def _retry(client: AsyncClient, headers: dict, job_id: uuid.UUID):
    with patch("app.platform.jobs.router.queue_ingest_job", new=AsyncMock()) as queue:
        response = await client.post(f"/jobs/{job_id}/retry", headers=headers)
    return response, queue.await_count


class TestRetryAtTheCap:
    async def _never_committed(self, client, headers, session) -> uuid.UUID:
        """An upload nobody committed, failed with its file kept.

        The sweep leaves one like this on object storage.
        """
        job_id = await _upload(client, headers)
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(status="failed", error_message="The upload was never committed")
        )
        await session.commit()
        return job_id

    async def test_a_never_committed_upload_is_refused(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)

        with _caps(1):
            job_id = await self._never_committed(
                client, editor_auth_header, test_db_session
            )
            refused, queued = await _retry(client, editor_auth_header, job_id)

        assert (refused.status_code, queued) == (422, 0), refused.text
        assert refused.json()["detail"] == AT_CAP
        assert (await _row(test_db_session, job_id)).status == "failed"

        with _caps(2), _plan(_PlanPort()) as port:
            admitted, queued = await _retry(client, editor_auth_header, job_id)
        assert (admitted.status_code, queued) == (202, 1), admitted.text
        assert port.datasets_asked() == [2]

    async def test_a_plan_limit_refuses_the_retry(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        await create_dataset(test_db_session, created_by=editor)
        job_id = await self._never_committed(
            client, editor_auth_header, test_db_session
        )

        with _plan(_PlanPort(dataset_limit=1)):
            refused, queued = await _retry(client, editor_auth_header, job_id)

        assert (refused.status_code, queued) == (402, 0), refused.text
        assert (await _row(test_db_session, job_id)).status == "failed"

    async def test_a_replacement_retry_is_never_a_quota_refusal(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        editor = await _user_id(client, editor_auth_header)
        dataset = await create_dataset(test_db_session, created_by=editor)
        job = await _staged_row(
            test_db_session,
            editor,
            metadata={"reupload": True, "dataset_id": str(dataset.id)},
            status="failed",
        )

        with _caps(1), _plan(_PlanPort(dataset_limit=1)) as port:
            answered, queued = await _retry(client, editor_auth_header, job.id)

        assert (answered.status_code, queued) == (400, 0), answered.text
        assert "replacement jobs cannot be replayed" in answered.json()["detail"]
        assert port.datasets_asked() == []


class TestRacingCreates:
    async def test_two_admitted_commits_one_below_the_cap_create_one_dataset(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        """Both commits pass the door, which counts datasets and not queued jobs.

        The worker's reservation is what holds the cap: it locks per user and
        recounts in the transaction that inserts the record.
        """
        import app.core.db as db_module
        from app.modules.catalog.datasets.domain.service import (
            create_dataset as create_published_dataset,
        )

        editor = await _user_id(client, editor_auth_header)

        async def _publish() -> bool:
            async with db_module.async_session() as session:
                try:
                    await create_published_dataset(
                        session,
                        table_name=f"cap_race_{uuid.uuid4().hex[:12]}",
                        title="Raced",
                        created_by=editor,
                    )
                except DatasetQuotaExceededError:
                    await session.rollback()
                    return False
                await session.commit()
                return True

        with _caps(1):
            for _ in range(2):
                job_id = await _upload(client, editor_auth_header)
                admitted, _queued = await _commit(client, editor_auth_header, job_id)
                assert admitted.status_code == 202, admitted.text
            outcomes = await asyncio.gather(_publish(), _publish())

        assert sorted(outcomes) == [False, True]
        assert await _dataset_count(test_db_session, editor) == 1
