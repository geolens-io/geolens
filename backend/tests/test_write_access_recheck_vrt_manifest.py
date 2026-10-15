"""VRT and manifest admissions re-check the caller under the catalog rows.

Each test lets the handler's guard pass, commits a change to the caller's
standing from a second session straight after it, and lets the request run on.
The write must be refused with the guard's 403 or 404 and leave nothing behind.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
import app.modules.auth.permissions as permissions
import app.modules.catalog.authorization as authorization
from app.modules.auth.models import User
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.api import router_vrt
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.service import get_dataset
from app.platform.jobs.models import ADMITTED_CAPABILITY_METADATA_KEY, IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.manifest_service import _admit_refresh_run
from app.processing.ingest.publication import WriteAccessRevoked
from app.processing.ingest.vrt_admission import stage_vrt_regeneration
from app.processing.raster.models import RasterAsset, VrtGeneration
from tests.factories import create_dataset
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _link_source,
)

from tests.test_regenerate_vrt_integration import (  # noqa: F401 - fixtures
    _stage_generation,
    local_storage,
    quicklook_stub,
    source_tifs,
    vrt_db_state,
)
from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _commit,
    _deactivate,
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

        with pytest.raises(WriteAccessRevoked):
            await _admit_refresh_run(request, request_job, created.id, owner)

    assert not await test_db_session.scalar(
        select(DatasetRefreshRun.id).where(DatasetRefreshRun.dataset_id == created.id)
    )


async def _hand_vrt_records_to(state: dict, owner_id: uuid.UUID) -> None:
    record_ids = select(Dataset.record_id).where(
        Dataset.id.in_(
            [uuid.UUID(state["vrt_dataset_id"]), *state["source_dataset_ids"]]
        )
    )
    await _commit(
        update(Record).where(Record.id.in_(record_ids)).values(created_by=owner_id)
    )


async def _give_vrt_regeneration_to(state: dict, owner_id: uuid.UUID) -> None:
    await _hand_vrt_records_to(state, owner_id)
    await _commit(
        update(IngestJob)
        .where(IngestJob.id == uuid.UUID(state["job_id"]))
        .values(created_by=owner_id)
    )


async def _regenerate(state: dict, *, staged: bool) -> tuple[str, str | None, Any]:
    """Run the regeneration a source change (``staged``) or a plain
    regenerate queues, and return the job's status and error and the VRT's
    published hash."""
    from app.processing.ingest.tasks import regenerate_vrt, regenerate_vrt_staged

    kwargs = {
        "job_id": state["job_id"],
        "attempt_id": state["attempt_id"],
        "vrt_dataset_id": state["vrt_dataset_id"],
    }
    task = regenerate_vrt
    if staged:
        async with db_module.async_session() as session:
            generation_id = await _stage_generation(
                session, state, state["source_dataset_ids"]
            )
            # What a source door records on the job it queues.
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == uuid.UUID(state["job_id"]))
                .values(user_metadata={ADMITTED_CAPABILITY_METADATA_KEY: "upload"})
            )
            await session.commit()
        kwargs["generation_id"] = str(generation_id)
        task = regenerate_vrt_staged
    try:
        await task.func(**kwargs)
    except WriteAccessRevoked:
        pass
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, uuid.UUID(state["job_id"]))
        sha256 = await session.scalar(
            select(RasterAsset.sha256).where(RasterAsset.id == state["vrt_asset_id"])
        )
    return job.status, job.error_message, sha256


def _without_edit_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Editors keep upload and lose edit_metadata."""
    effective = permissions.get_effective_permissions

    async def editors_without_edit_metadata(db):
        matrix = await effective(db)
        matrix["editor"]["edit_metadata"] = False
        return matrix

    monkeypatch.setattr(
        permissions, "get_effective_permissions", editors_without_edit_metadata
    )


@pytest.mark.parametrize(
    ("staged", "change", "published"),
    [
        # A source change was admitted under upload.
        (True, "viewer", False),
        (True, "deactivate", False),
        (True, "upload_only", True),
        # A plain regenerate needs ownership and an active account only.
        (False, "viewer", True),
        (False, "transfer", False),
        (False, None, True),
    ],
)
async def test_a_vrt_regeneration_rechecks_its_submitter_before_it_publishes(
    vrt_db_state: dict,  # noqa: F811
    local_storage,  # noqa: F811
    quicklook_stub,  # noqa: F811
    clean_tables,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    staged: bool,
    change: str | None,
    published: bool,
) -> None:
    _, owner_id = people["owner"]
    await _give_vrt_regeneration_to(vrt_db_state, owner_id)
    if change == "viewer":
        await _commit(_demote_to_viewer(owner_id))
    elif change == "deactivate":
        await _commit(_deactivate(owner_id))
    elif change == "transfer":
        # The members go too, so the VRT's audience check still passes.
        await _hand_vrt_records_to(vrt_db_state, people["target"])
    elif change == "upload_only":
        _without_edit_metadata(monkeypatch)

    status, error, sha256 = await _regenerate(vrt_db_state, staged=staged)

    if published:
        assert status == "complete", error
        assert sha256 is not None
    else:
        assert status == "failed"
        assert error == str(WriteAccessRevoked())
        assert sha256 is None


async def test_a_source_door_records_the_capability_it_admitted_under(
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
) -> None:
    _, owner_id = people["owner"]
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=owner_id)
    asset = await test_db_session.scalar(
        select(RasterAsset).where(RasterAsset.dataset_id == vrt_id)
    )
    owner = await test_db_session.get(User, owner_id)

    job, _ = await stage_vrt_regeneration(test_db_session, asset, vrt_id, [], owner)

    assert job.user_metadata == {ADMITTED_CAPABILITY_METADATA_KEY: "upload"}
    await test_db_session.rollback()
