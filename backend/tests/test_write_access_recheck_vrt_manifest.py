"""VRT and manifest admissions re-check the caller under the catalog rows.

Each test lets the handler's guard pass, commits a change to the caller's
standing from a second session straight after it, and lets the request run on.
The write must be refused with the guard's 403 or 404 and leave nothing behind.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
import app.modules.catalog.authorization as authorization
from app.modules.auth.models import User
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.api import router_vrt
from app.modules.catalog.datasets.domain.service import get_dataset
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.manifest_service import _admit_refresh_run
from app.processing.raster.models import RasterAsset, VrtGeneration
from tests.factories import create_dataset
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _link_source,
)

from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _commit,
    _demote_to_viewer,
    _then,
    _transfer_dataset,
    people,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_init_tile_pool_for_tests")]


async def _vrt_state(vrt_id: uuid.UUID) -> tuple[str, int]:
    async with db_module.async_session() as session:
        status = await session.scalar(
            select(RasterAsset.status).where(RasterAsset.dataset_id == vrt_id)
        )
        generations = await session.scalar(
            select(func.count())
            .select_from(VrtGeneration)
            .where(VrtGeneration.vrt_dataset_id == vrt_id)
        )
    return status, generations


async def test_vrt_regeneration_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=owner_id, visibility="public"
    )

    monkeypatch.setattr(
        router_vrt,
        "check_dataset_write_access",
        _then(
            router_vrt.check_dataset_write_access,
            _transfer_dataset(vrt_id, people["target"]),
        ),
    )
    resp = await client.post(
        f"/datasets/{vrt_id}/vrt/regenerate/", headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert await _vrt_state(vrt_id) == ("ready", 0)


async def test_vrt_source_removal_is_refused_after_a_role_downgrade(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=owner_id)
    sources = [
        await _create_raster_dataset(test_db_session, created_by=owner_id)
        for _ in range(3)
    ]
    for position, source_id in enumerate(sources):
        await _link_source(test_db_session, vrt_id, source_id, position)

    # The handler imports the guard when it runs.
    monkeypatch.setattr(
        authorization,
        "check_dataset_write_access",
        _then(authorization.check_dataset_write_access, _demote_to_viewer(owner_id)),
    )
    resp = await client.delete(
        f"/ingest/vrt/{vrt_id}/sources/{sources[0]}/", headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Missing permission: upload"
    assert await _vrt_state(vrt_id) == ("ready", 0)


async def test_manifest_run_admission_is_refused_after_a_transfer(
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
) -> None:
    _, owner_id = people["owner"]
    created = await create_dataset(test_db_session, created_by=owner_id)
    job = IngestJob(
        dataset_id=created.id,
        status="running",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.gpkg",
        created_by=owner_id,
        user_metadata={"manifest_key": "parcels", "reupload": True},
    )
    test_db_session.add(job)
    await test_db_session.commit()

    async with db_module.async_session() as request:
        owner = await request.get(User, owner_id)
        await check_dataset_write_access(
            request, await get_dataset(request, created.id), created.id, owner
        )
        await _commit(_transfer_dataset(created.id, people["target"]))
        request_job = await request.get(IngestJob, job.id)

        with pytest.raises(HTTPException) as refused:
            await _admit_refresh_run(request, request_job, created.id, owner)

    assert refused.value.status_code == 403
    assert not await test_db_session.scalar(
        select(DatasetRefreshRun.id).where(DatasetRefreshRun.dataset_id == created.id)
    )
