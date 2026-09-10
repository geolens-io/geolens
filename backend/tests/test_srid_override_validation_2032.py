"""The commit doors' srid_override validity check (#2032).

`srid_override` assigns the CRS a source's coordinates are read under. A code
PostGIS has no `spatial_ref_sys` row for used to commit with a 202 and then be
dropped by `_resolve_effective_srid`'s "override > detected > 4326" precedence,
so the dataset was ingested under the DETECTED CRS with nothing in the
response saying so. Both doors now refuse it, naming the field and the code.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.platform.jobs.models import IngestJob

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

#: Inside the schema's 1..998999 bound, in neither EPSG registry.
UNASSIGNED_SRID = 99999


async def _pending_import_job(session) -> IngestJob:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        source_filename="roads.geojson",
        file_path="/tmp/fake-2032.geojson",
        created_by=admin_id,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _pending_reupload_job(session):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.gpkg",
        file_path="/tmp/fake-2032.gpkg",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return dataset, job


async def _noop_defer(fn, rollback=None, db=None, job=None):
    return None


class TestRegistries:
    async def test_a_code_only_proj_knows_is_accepted(self, test_db_session):
        """fix(#2032 review): a raster override never reaches PostGIS.

        The two EPSG databases are versioned independently, so a code PROJ has
        and this PostGIS install does not is the worker's to apply, not this
        door's to refuse.
        """
        from unittest.mock import AsyncMock

        from app.core.geo import unknown_srid_refusal

        session = AsyncMock()
        session.scalar.return_value = None  # not in spatial_ref_sys

        assert await unknown_srid_refusal(session, 2263) is None
        session.scalar.assert_not_awaited()

        refusal = await unknown_srid_refusal(session, UNASSIGNED_SRID)
        assert refusal is not None and str(UNASSIGNED_SRID) in refusal
        session.scalar.assert_awaited_once()


class TestImportCommitDoor:
    async def test_refuses_an_srid_the_database_does_not_know(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        job = await _pending_import_job(test_db_session)

        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"title": "Roads", "srid_override": UNASSIGNED_SRID},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "srid_override" in detail and str(UNASSIGNED_SRID) in detail, detail
        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert not (job.user_metadata or {})

    async def test_accepts_an_assigned_srid(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        job = await _pending_import_job(test_db_session)

        with patch(
            "app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock
        ) as queue:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Roads", "srid_override": 2263},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        queue.assert_awaited_once()


class TestReuploadCommitDoor:
    async def test_refuses_an_srid_the_database_does_not_know(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset, job = await _pending_reupload_job(test_db_session)

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job.id}/commit",
            json={"srid_override": UNASSIGNED_SRID},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "srid_override" in detail and str(UNASSIGNED_SRID) in detail, detail
        await test_db_session.refresh(job)
        assert job.status == "pending"

    async def test_accepts_an_assigned_srid(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset, job = await _pending_reupload_job(test_db_session)

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.defer_with_orphan_guard",
            side_effect=_noop_defer,
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"srid_override": 2263},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        await test_db_session.refresh(job)
        assert job.user_metadata["srid_override"] == 2263
