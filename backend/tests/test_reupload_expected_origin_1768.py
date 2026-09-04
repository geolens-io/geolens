"""The re-upload commit door's expected-origin condition (#1768).

`geolens replace` and the web re-upload dialog both refuse to replace a
dataset whose origin is a service, a STAC item, or a registered table. That
refusal is a CLIENT-side precheck: the client reads the origin once, then
uploads, previews, and waits for a human to confirm. Anything that rebinds
the dataset in that window is invisible to it, and the swap the commit queues
rebinds unconditionally to `upload` (`_apply_reupload_swap` in
tasks_reupload.py) — so a service or STAC binding established mid-flow was
severed by a commit that looked, to the client, exactly like the one it had
checked.

The commit body now carries the origin the client SAW. The door re-reads the
dataset's current origin after the run row takes the one-active-run admission
slot and refuses a mismatch with 409 `origin_changed` — the same code the
refresh door already uses when a source moves under a queued run.

The field is optional, so the pre-#1768 contract is still exercised here: a
body that omits it commits exactly as before.
"""

from __future__ import annotations

import typing
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from unittest.mock import patch

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.dataset_origin import ORIGIN_KINDS, OriginKind
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


# (source_format, the origin kind classify_origin derives from it). Every
# kind a vector dataset can carry, so the door is proven for the three the
# clients refuse to replace (service, stac, postgis) as well as the two they
# allow. `postgis` is spelled as a NULL source_format rather than by
# registering a real table: registration mutates cluster-global reader grants
# and would force this module into `_TENANCY_GLOBAL_STATE_MODULES`, and the
# door reads nothing that a real registration would add.
ORIGIN_CASES: list[tuple[str | None, str]] = [
    ("geojson", "upload"),
    ("wfs", "service"),
    ("stac", "stac"),
    (None, "postgis"),
    ("created", "created"),
]

#: An origin kind that is not the one under test, for the stale-value case.
_OTHER_KIND = {
    "upload": "service",
    "service": "upload",
    "stac": "upload",
    "postgis": "upload",
    "created": "upload",
}


async def _seed_committable_reupload(session, *, source_format: str | None):
    """Dataset + bound pending re-upload job — the state a client reaches
    after uploading its replacement and before it confirms."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=admin_id, source_format=source_format
    )
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.gpkg",
        file_path="/tmp/fake-reupload-1768.gpkg",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return dataset, job


async def _runs_for(session, dataset_id) -> list[DatasetRefreshRun]:
    result = await session.execute(
        select(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset_id)
    )
    return list(result.scalars().all())


async def _noop_defer(fn, rollback=None, db=None, job=None):
    """Skip Procrastinate: this module tests the door, not the dispatch."""
    return None


class TestExpectedOriginMatches:
    @pytest.mark.parametrize("source_format,origin_kind", ORIGIN_CASES)
    async def test_commit_is_accepted_when_the_origin_still_matches(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        source_format: str | None,
        origin_kind: str,
    ):
        """The whole point of the condition is that it costs a correct client
        nothing: the origin the client saw is still the origin, so the commit
        is queued exactly as it was before #1768."""
        dataset, job = await _seed_committable_reupload(
            test_db_session, source_format=source_format
        )

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.defer_with_orphan_guard",
            side_effect=_noop_defer,
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"expected_origin_kind": origin_kind},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "pending"
        runs = await _runs_for(test_db_session, dataset.id)
        assert [run.ingest_job_id for run in runs] == [job.id]


class TestExpectedOriginNoLongerMatches:
    @pytest.mark.parametrize("source_format,origin_kind", ORIGIN_CASES)
    async def test_commit_is_refused_when_the_origin_is_not_the_one_seen(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        source_format: str | None,
        origin_kind: str,
    ):
        """One case per origin kind: a client that captured some OTHER kind is
        refused, and the refusal names both sides so the client can say what
        changed rather than just that something did."""
        dataset, job = await _seed_committable_reupload(
            test_db_session, source_format=source_format
        )
        stale = _OTHER_KIND[origin_kind]

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job.id}/commit",
            json={"expected_origin_kind": stale},
            headers=admin_auth_header,
        )

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "origin_changed"
        assert detail["origin_kind"] == origin_kind
        assert detail["expected_origin_kind"] == stale

        # Nothing was reserved, so the next dispatch is admitted immediately.
        assert await _runs_for(test_db_session, dataset.id) == []
        await test_db_session.refresh(job)
        assert job.status == "pending"

    async def test_an_omitted_expected_origin_keeps_the_old_contract(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Additive, and provably so: a client that sends no
        `expected_origin_kind` commits over a service origin exactly as every
        client did before #1768. This is the compatibility guarantee, not an
        oversight — an older CLI or SDK must keep working."""
        dataset, job = await _seed_committable_reupload(
            test_db_session, source_format="wfs"
        )

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.defer_with_orphan_guard",
            side_effect=_noop_defer,
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text

    async def test_an_unknown_origin_kind_is_rejected_by_the_schema(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        dataset, job = await _seed_committable_reupload(
            test_db_session, source_format="geojson"
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job.id}/commit",
            json={"expected_origin_kind": "sftp"},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text


def _rebinding_create_pending_run(session_factory, dataset_id):
    """Wrap the real `create_pending_run`: commit a service rebinding of the
    dataset on a SEPARATE session first, then proceed.

    This is the #1768 race made deterministic. The rebinding lands after the
    client captured `upload` and after the door's own first read of the
    dataset, which is exactly the window a concurrent service or STAC
    re-upload commits in. It runs before the real helper for the same reason
    the cancel race in `test_job_cancel_reupload_commit.py` does: once the
    helper flushes, the request holds row locks the side session would wait
    on forever.
    """

    async def _wrapped(session, **kwargs):
        async with session_factory() as side_session:
            await side_session.execute(
                update(Dataset)
                .where(Dataset.id == dataset_id)
                .values(
                    source_format="wfs",
                    origin_uri="https://example.test/wfs",
                    origin_ref={
                        "kind": "service",
                        "service_type": "wfs",
                        "url": "https://example.test/wfs",
                        "layer_id": "parcels",
                    },
                )
            )
            await side_session.commit()
        return await create_pending_run(session, **kwargs)

    return _wrapped


class TestOriginChangesBetweenCaptureAndCommit:
    async def test_a_rebinding_mid_flow_is_refused_and_left_intact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """The bug from the issue, end to end: the client saw `upload`, a
        service binding commits while it was uploading and confirming, and the
        commit must not install the file swap that would sever it."""
        from app.core.db import async_session

        dataset, job = await _seed_committable_reupload(
            test_db_session, source_format="geojson"
        )

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.create_pending_run",
            side_effect=_rebinding_create_pending_run(async_session, dataset.id),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"expected_origin_kind": "upload"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "origin_changed"
        assert detail["origin_kind"] == "service"
        assert detail["expected_origin_kind"] == "upload"

        # The binding that landed mid-flow survives untouched — that is the
        # harm #1768 is about, not the refusal.
        await test_db_session.refresh(dataset)
        assert dataset.source_format == "wfs"
        assert dataset.origin_ref["kind"] == "service"
        assert dataset.origin_uri == "https://example.test/wfs"

        # And nothing is stranded: no run row holds the admission index, and
        # the job is still committable once the client re-reads the origin.
        assert await _runs_for(test_db_session, dataset.id) == []
        await test_db_session.refresh(job)
        assert job.status == "pending"

        admin_id = await get_user_id(test_db_session, "admin")
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=job.id,
            feature_count_before=1,
        )
        await test_db_session.commit()
        assert run.status == "pending"


def test_origin_kind_literal_mirrors_the_origin_vocabulary():
    """`OriginKind` is the request-model spelling of `ORIGIN_KINDS`. A kind
    added to one alone must fail here rather than in a request."""
    assert set(typing.get_args(OriginKind)) == ORIGIN_KINDS
