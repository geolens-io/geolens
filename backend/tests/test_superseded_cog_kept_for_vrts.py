"""A replaced raster's superseded COG stays while a VRT may still read it, charged.

A VRT names each member's COG by key, so a replacement of a member keeps the
old COG for as long as a VRT built from it, or a build that may have read it,
is around. The quicklooks go either way. A kept COG counts against the
member's owner under a ``retained_cog:`` row until the stale-job sweep
reclaims it, object first and row second.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import structlog
from sqlalchemy import delete, select, text

import app.core.db as db_module
from app.modules.auth.models import User
from app.modules.quota.service import get_user_quota_usage
from app.platform.jobs.models import PUBLISH_FOLLOWUPS_FIELD, IngestJob
from app.platform.jobs.sweep import fail_stale_jobs
from app.processing.ingest import tasks_raster_replace, tasks_vrt
from app.processing.ingest.publish_followups import run_owed_publish_followups
from app.processing.ingest.tasks_raster_replace import reupload_raster
from app.processing.raster import vrt_members
from app.processing.raster.models import RasterAsset, VrtGeneration, VrtSourceLink
from app.processing.raster.vrt_members import reclaim_retained_cogs
from tests.test_raster_replace_1221 import (
    _capped,
    _drop_owner,
    _geotiff_bytes,
    _make_live_raster,
    _make_owner,
    _make_vrt_parent,
    _purge,
    _purge_vrt,
    _queue_replace_job,
    _run_vrt_creation,
    _set_counted_data_bytes,
)
from tests.test_publish_followups import _make_due
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

OLD_BYTES = 1000


async def _admin_id(session) -> uuid.UUID:
    return (
        await session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()


def _old_keys(live) -> tuple[str, str, str]:
    return (
        live.cog_key,
        live.asset.quicklook_256_uri,
        live.asset.quicklook_512_uri,
    )


async def _replace(
    session, tmp_path: Path, *, dataset_id, admin_id, seed: int = 99
) -> uuid.UUID:
    """Run a real, acknowledged replacement of ``dataset_id``; returns its job id."""
    source = tmp_path / f"replacement-{seed}.tif"
    source.write_bytes(_geotiff_bytes(seed=seed))
    job = await _queue_replace_job(
        session, dataset_id=dataset_id, user_id=admin_id, file_path=str(source)
    )
    job_id = job.id
    await reupload_raster.func(
        job_id=str(job_id),
        dataset_id=str(dataset_id),
        file_path=str(source),
        user_id=str(admin_id),
        attempt_id=str(job.attempt_id),
    )
    return job_id


async def _left(storage, keys) -> list[str]:
    return [key for key in keys if await storage.exists(key)]


async def _set_built_from(session, vrt_id, built_from: dict | None) -> None:
    await session.execute(
        text(
            "UPDATE catalog.raster_assets "
            "SET built_from = CAST(:built_from AS jsonb) WHERE dataset_id = :id"
        ),
        {
            "built_from": None if built_from is None else json.dumps(built_from),
            "id": vrt_id,
        },
    )
    await session.commit()


async def _retained(session, dataset_id) -> list[tuple[str, int]]:
    """The kept COGs charged to ``dataset_id``, as (logical key, bytes)."""
    rows = await session.execute(
        text(
            "SELECT href, size_bytes FROM catalog.dataset_assets "
            "WHERE dataset_id = :id AND key LIKE 'retained_cog:%'"
        ),
        {"id": dataset_id},
    )
    await session.commit()
    return sorted((href, size) for href, size in rows.all())


async def _data_bytes(session, dataset_id) -> int:
    size = await session.scalar(
        text(
            "SELECT size_bytes FROM catalog.dataset_assets "
            "WHERE dataset_id = :id AND key = 'data'"
        ),
        {"id": dataset_id},
    )
    await session.commit()
    return size


async def _usage(session, owner_id) -> int:
    usage = await get_user_quota_usage(session, owner_id)
    await session.commit()
    return usage.bytes_used


async def _live_cog(session, dataset_id) -> str:
    uri = await session.scalar(
        select(RasterAsset.asset_uri).where(RasterAsset.dataset_id == dataset_id)
    )
    await session.commit()
    return uri


def _kept_events(logs) -> list[dict]:
    return [e for e in logs if e["event"] == "superseded_cog_kept_for_vrt"]


async def test_a_vrt_built_from_the_old_cog_keeps_it_and_loses_its_quicklooks(
    test_db_session, raster_storage, tmp_path
) -> None:
    """The mosaic keeps reading the member's old COG, charged; the quicklooks go."""
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    cog, ql256, ql512 = _old_keys(member)
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    await _set_built_from(test_db_session, ids[0], {str(ids[2]): cog})
    await _set_counted_data_bytes(test_db_session, ids[2], OLD_BYTES)
    try:
        with structlog.testing.capture_logs() as logs:
            await _replace(
                test_db_session, tmp_path, dataset_id=ids[2], admin_id=admin_id
            )

        assert await _left(raster_storage, (cog, ql256, ql512)) == [cog]
        assert await _retained(test_db_session, ids[2]) == [(cog, OLD_BYTES)]
        assert [
            (e["storage_key"], e["vrt_dataset_ids"]) for e in _kept_events(logs)
        ] == [(cog, [str(ids[0])])]
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_raster_in_no_vrt_loses_all_three(
    test_db_session, raster_storage, tmp_path
) -> None:
    """With nothing reading it, the superseded COG goes with its quicklooks, uncharged."""
    admin_id = await _admin_id(test_db_session)
    live = await _make_live_raster(test_db_session, raster_storage, created_by=admin_id)
    keys = _old_keys(live)
    dataset_id, record_id = live.dataset.id, live.dataset.record_id
    try:
        with structlog.testing.capture_logs() as logs:
            await _replace(
                test_db_session, tmp_path, dataset_id=dataset_id, admin_id=admin_id
            )

        assert await _left(raster_storage, keys) == []
        assert await _retained(test_db_session, dataset_id) == []
        assert _kept_events(logs) == []
    finally:
        await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


async def test_a_vrt_with_no_record_of_its_build_keeps_the_old_cog(
    test_db_session, raster_storage, tmp_path
) -> None:
    """A VRT without ``built_from`` may be reading any COG its member ever had.

    The sweep keeps it too, charged, until the VRT is rebuilt.
    """
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    cog, ql256, ql512 = _old_keys(member)
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    await _set_counted_data_bytes(test_db_session, ids[2], OLD_BYTES)
    try:
        await _replace(test_db_session, tmp_path, dataset_id=ids[2], admin_id=admin_id)
        await reclaim_retained_cogs()

        assert await _left(raster_storage, (cog, ql256, ql512)) == [cog]
        assert await _retained(test_db_session, ids[2]) == [(cog, OLD_BYTES)]
    finally:
        await _purge_vrt(test_db_session, ids=ids)


@pytest.mark.parametrize("status", ["pending", "running"])
@pytest.mark.parametrize("how", ["stages", "links"])
async def test_a_build_in_flight_keeps_the_old_cog(
    test_db_session, raster_storage, tmp_path, status: str, how: str
) -> None:
    """A generation that may read the member keeps its COG, whatever the VRT last published.

    ``stages``: the member is being added to a VRT that doesn't link it yet.
    ``links``: the VRT links the member but last published another COG of it.
    """
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    other = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session,
        raster_storage,
        created_by=admin_id,
        member=other if how == "stages" else member,
    )
    cog, ql256, ql512 = _old_keys(member)
    member_id, member_record = member.dataset.id, member.dataset.record_id
    other_id, other_record = other.dataset.id, other.dataset.record_id
    parent_id, parent_record = parent.dataset.id, parent.dataset.record_id
    if how == "links":
        await _set_built_from(
            test_db_session, parent_id, {str(member_id): "rasters/elsewhere.cog.tif"}
        )
    test_db_session.add(
        VrtGeneration(
            vrt_dataset_id=parent_id,
            status=status,
            started_at=datetime.now(timezone.utc),
            staged_source_ids=(
                [str(other_id), str(member_id)] if how == "stages" else None
            ),
        )
    )
    await test_db_session.commit()
    try:
        await _replace(
            test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
        )

        assert await _left(raster_storage, (cog, ql256, ql512)) == [cog]
        assert [href for href, _ in await _retained(test_db_session, member_id)] == [
            cog
        ]
    finally:
        await _purge_vrt(
            test_db_session, ids=(parent_id, parent_record, member_id, member_record)
        )
        await _purge(test_db_session, dataset_id=other_id, record_id=other_record)


async def _put_cog_where_vrts_read(uri: str) -> None:
    """Put a member COG where a real VRT build reads it."""
    member_path = Path(tasks_vrt.resolve_vrt_source_path(uri, tenant_id=None))
    member_path.parent.mkdir(parents=True, exist_ok=True)
    member_path.write_bytes(_geotiff_bytes(seed=1))


async def _regenerate_with(session, *, parent_id, members, user_id) -> None:
    """Drive a real ``regenerate_vrt`` that publishes ``members`` as the VRT's set."""
    generation_id = uuid.uuid4()
    job = IngestJob(
        dataset_id=parent_id,
        source_filename="regen",
        created_by=user_id,
        status="pending",
        user_metadata={"vrt_regenerate": True},
    )
    session.add(job)
    session.add(
        VrtGeneration(
            id=generation_id,
            vrt_dataset_id=parent_id,
            status="pending",
            started_at=datetime.now(timezone.utc),
            staged_source_ids=[str(member) for member in members],
        )
    )
    await session.execute(
        text(
            "UPDATE catalog.raster_assets "
            "SET current_generation_id = :gen, status = 'regenerating' "
            "WHERE dataset_id = :id"
        ),
        {"gen": generation_id, "id": parent_id},
    )
    await session.commit()
    await session.refresh(job)
    await tasks_vrt.regenerate_vrt.func(
        job_id=str(job.id),
        vrt_dataset_id=str(parent_id),
        attempt_id=str(job.attempt_id),
        generation_id=str(generation_id),
    )


async def test_a_member_rebuilt_out_of_its_vrt_is_reaped_normally(
    test_db_session, raster_storage, tmp_path
) -> None:
    """Once a regeneration drops the member, its next replacement loses all three."""
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    other = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    await _put_cog_where_vrts_read(other.asset.asset_uri)
    keys = _old_keys(member)
    member_id, member_record = member.dataset.id, member.dataset.record_id
    other_id, other_record = other.dataset.id, other.dataset.record_id
    parent_id, parent_record = parent.dataset.id, parent.dataset.record_id
    test_db_session.add(
        VrtSourceLink(vrt_dataset_id=parent_id, source_dataset_id=other_id, position=1)
    )
    await test_db_session.commit()
    await _set_built_from(
        test_db_session,
        parent_id,
        {str(member_id): keys[0], str(other_id): other.cog_key},
    )
    try:
        await _regenerate_with(
            test_db_session, parent_id=parent_id, members=[other_id], user_id=admin_id
        )
        built_from = await test_db_session.scalar(
            select(RasterAsset.built_from).where(RasterAsset.dataset_id == parent_id)
        )
        assert set(built_from) == {str(other_id)}, "the regeneration kept the member"

        await _replace(
            test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
        )

        assert await _left(raster_storage, keys) == []
        assert await _retained(test_db_session, member_id) == []
    finally:
        await _purge_vrt(
            test_db_session, ids=(parent_id, parent_record, member_id, member_record)
        )
        await _purge(test_db_session, dataset_id=other_id, record_id=other_record)


async def test_a_vrt_created_while_its_member_is_replaced_keeps_the_cog_it_read(
    test_db_session, raster_storage, tmp_path, monkeypatch
) -> None:
    """A VRT creation that read the old COG before the swap still has it once published.

    The replacement lands right after the creation reads its members, when no
    VRT row names the member yet.
    """
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    cog, ql256, ql512 = _old_keys(member)
    member_id, member_record = member.dataset.id, member.dataset.record_id
    real_snapshot = tasks_vrt.snapshot_member_sources
    replaced: list[bool] = []

    async def _replace_after_the_read(*args, **kwargs):
        snapshot = await real_snapshot(*args, **kwargs)
        if not replaced:
            replaced.append(True)
            await _replace(
                test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
            )
        return snapshot

    monkeypatch.setattr(tasks_vrt, "snapshot_member_sources", _replace_after_the_read)
    vrt_id = vrt_record = None
    try:
        with structlog.testing.capture_logs() as logs:
            vrt_id, vrt_record = await _run_vrt_creation(
                test_db_session, raster_storage, member=member, user_id=admin_id
            )

        assert replaced, "the replacement never ran"
        built_from = await test_db_session.scalar(
            select(RasterAsset.built_from).where(RasterAsset.dataset_id == vrt_id)
        )
        assert built_from == {str(member_id): cog}
        assert await _left(raster_storage, (cog, ql256, ql512)) == [cog]
        assert [href for href, _ in await _retained(test_db_session, member_id)] == [
            cog
        ]
        assert [
            (e["storage_key"], e["vrt_dataset_ids"], len(e["vrt_job_ids"]))
            for e in _kept_events(logs)
        ] == [(cog, [], 1)]
    finally:
        if vrt_id is not None:
            await _purge_vrt(
                test_db_session, ids=(vrt_id, vrt_record, member_id, member_record)
            )
        else:
            await _purge(test_db_session, dataset_id=member_id, record_id=member_record)


async def test_a_vrt_creation_noted_after_the_publish_looked_is_charged_by_the_followups(
    test_db_session, raster_storage, tmp_path, monkeypatch
) -> None:
    """A creation that notes the member between the publish's check and its commit.

    The publish credits the old bytes, since it saw no reader. The creation may
    still read the old COG, so the follow-ups keep it and charge it.
    """
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    cog, ql256, ql512 = _old_keys(member)
    member_id, member_record = member.dataset.id, member.dataset.record_id
    await _set_counted_data_bytes(test_db_session, member_id, OLD_BYTES)
    real_readers = tasks_raster_replace.cog_readers
    creation_ids: list[uuid.UUID] = []

    async def _creation_notes_after_the_check(session, dataset_id, asset_uri):
        readers = await real_readers(session, dataset_id, asset_uri)
        async with db_module.async_session() as other:
            job = IngestJob(
                source_filename="mosaic.vrt",
                created_by=admin_id,
                status="running",
                user_metadata={vrt_members.VRT_MEMBERS_FIELD: [str(member_id)]},
            )
            other.add(job)
            await other.commit()
            creation_ids.append(job.id)
        return readers

    monkeypatch.setattr(
        tasks_raster_replace, "cog_readers", _creation_notes_after_the_check
    )
    try:
        with structlog.testing.capture_logs() as logs:
            await _replace(
                test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
            )

        assert await _left(raster_storage, (cog, ql256, ql512)) == [cog]
        assert await _retained(test_db_session, member_id) == [(cog, OLD_BYTES)]
        assert [e["vrt_job_ids"] for e in _kept_events(logs)] == [
            [str(creation_ids[0])]
        ]
    finally:
        await test_db_session.execute(
            delete(IngestJob).where(IngestJob.id.in_(creation_ids))
        )
        await test_db_session.commit()
        await _purge(test_db_session, dataset_id=member_id, record_id=member_record)


async def test_a_kept_cog_is_charged_until_a_regeneration_moves_the_vrt_on(
    test_db_session, raster_storage, tmp_path
) -> None:
    """The member's owner pays for both COGs until the sweep reclaims the old one.

    A sweep while the VRT still reads it keeps it. A regeneration that builds
    from the new COG frees it, and the next sweep deletes it and its charge.
    """
    owner_id = await _make_owner(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=owner_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=owner_id, member=member
    )
    cog = member.cog_key
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    await _set_built_from(test_db_session, ids[0], {str(ids[2]): cog})
    await _set_counted_data_bytes(test_db_session, ids[2], OLD_BYTES)
    try:
        await _replace(test_db_session, tmp_path, dataset_id=ids[2], admin_id=owner_id)
        new_bytes = await _data_bytes(test_db_session, ids[2])
        assert await _usage(test_db_session, owner_id) == new_bytes + OLD_BYTES

        await reclaim_retained_cogs()
        assert await _left(raster_storage, (cog,)) == [cog]
        assert await _retained(test_db_session, ids[2]) == [(cog, OLD_BYTES)]

        await _put_cog_where_vrts_read(await _live_cog(test_db_session, ids[2]))
        await _regenerate_with(
            test_db_session, parent_id=ids[0], members=[ids[2]], user_id=owner_id
        )
        await reclaim_retained_cogs()

        assert await _left(raster_storage, (cog,)) == []
        assert await _retained(test_db_session, ids[2]) == []
        assert await _usage(test_db_session, owner_id) == new_bytes
    finally:
        await _purge_vrt(test_db_session, ids=ids)
        await _drop_owner(test_db_session, owner_id)


async def test_a_member_dropped_from_its_vrt_frees_its_kept_cog(
    test_db_session, raster_storage, tmp_path
) -> None:
    """A regeneration that leaves the member out lets the sweep reclaim its kept COG."""
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    other = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    await _put_cog_where_vrts_read(other.asset.asset_uri)
    cog = member.cog_key
    member_id, member_record = member.dataset.id, member.dataset.record_id
    other_id, other_record = other.dataset.id, other.dataset.record_id
    parent_id, parent_record = parent.dataset.id, parent.dataset.record_id
    test_db_session.add(
        VrtSourceLink(vrt_dataset_id=parent_id, source_dataset_id=other_id, position=1)
    )
    await test_db_session.commit()
    await _set_built_from(
        test_db_session, parent_id, {str(member_id): cog, str(other_id): other.cog_key}
    )
    try:
        await _replace(
            test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
        )
        assert await _left(raster_storage, (cog,)) == [cog]

        await _regenerate_with(
            test_db_session, parent_id=parent_id, members=[other_id], user_id=admin_id
        )
        await reclaim_retained_cogs()

        assert await _left(raster_storage, (cog,)) == []
        assert await _retained(test_db_session, member_id) == []
    finally:
        await _purge_vrt(
            test_db_session, ids=(parent_id, parent_record, member_id, member_record)
        )
        await _purge(test_db_session, dataset_id=other_id, record_id=other_record)


async def test_another_users_vrt_keeps_the_cog_on_the_members_owner(
    test_db_session, raster_storage, tmp_path
) -> None:
    """The member's owner is charged for a COG kept for someone else's VRT.

    The VRT's owner pays nothing. Deleting that VRT frees the COG for the
    stale-job sweep.
    """
    member_owner = await _make_owner(test_db_session)
    vrt_owner = await _make_owner(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=member_owner
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=vrt_owner, member=member
    )
    cog = member.cog_key
    member_id, member_record = member.dataset.id, member.dataset.record_id
    parent_id, parent_record = parent.dataset.id, parent.dataset.record_id
    await _set_built_from(test_db_session, parent_id, {str(member_id): cog})
    await _set_counted_data_bytes(test_db_session, member_id, OLD_BYTES)
    try:
        await _replace(
            test_db_session, tmp_path, dataset_id=member_id, admin_id=member_owner
        )
        new_bytes = await _data_bytes(test_db_session, member_id)

        assert await _usage(test_db_session, member_owner) == new_bytes + OLD_BYTES
        assert await _usage(test_db_session, vrt_owner) == 0

        await test_db_session.execute(
            delete(VrtSourceLink).where(VrtSourceLink.vrt_dataset_id == parent_id)
        )
        await test_db_session.commit()
        await _purge(test_db_session, dataset_id=parent_id, record_id=parent_record)
        async with db_module.async_session() as sweep:
            await fail_stale_jobs(sweep)

        assert await _left(raster_storage, (cog,)) == []
        assert await _usage(test_db_session, member_owner) == new_bytes
    finally:
        await _purge_vrt(
            test_db_session, ids=(parent_id, parent_record, member_id, member_record)
        )
        await _drop_owner(test_db_session, member_owner)
        await _drop_owner(test_db_session, vrt_owner)


@pytest.mark.parametrize("in_a_vrt", [True, False])
async def test_a_replacement_near_the_cap_fits_only_when_the_old_cog_goes(
    test_db_session, raster_storage, tmp_path, in_a_vrt: bool
) -> None:
    """The kept COG isn't credited, so a swap that fits by crediting it is refused."""
    owner_id = await _make_owner(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=owner_id
    )
    cog = member.cog_key
    member_id, member_record = member.dataset.id, member.dataset.record_id
    parent_id = parent_record = None
    if in_a_vrt:
        parent = await _make_vrt_parent(
            test_db_session, raster_storage, created_by=owner_id, member=member
        )
        parent_id, parent_record = parent.dataset.id, parent.dataset.record_id
        await _set_built_from(test_db_session, parent_id, {str(member_id): cog})
    await _set_counted_data_bytes(test_db_session, member_id, 10_000_000)
    try:
        with _capped(storage_cap=10_000_001):
            if in_a_vrt:
                with pytest.raises(Exception, match="[Ss]torage quota"):
                    await _replace(
                        test_db_session,
                        tmp_path,
                        dataset_id=member_id,
                        admin_id=owner_id,
                    )
            else:
                await _replace(
                    test_db_session, tmp_path, dataset_id=member_id, admin_id=owner_id
                )

        assert (await _live_cog(test_db_session, member_id) == cog) is in_a_vrt
        assert await _left(raster_storage, (cog,)) == ([cog] if in_a_vrt else [])
        assert await _retained(test_db_session, member_id) == []
    finally:
        if parent_id is not None:
            await _purge_vrt(
                test_db_session,
                ids=(parent_id, parent_record, member_id, member_record),
            )
        else:
            await _purge(test_db_session, dataset_id=member_id, record_id=member_record)
        await _drop_owner(test_db_session, owner_id)


async def _a_reader(*_args, **_kwargs):
    return [str(uuid.uuid4())], []


async def _owed(session, job_id) -> dict | None:
    record = await session.scalar(
        select(IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]).where(
            IngestJob.id == job_id
        )
    )
    await session.commit()
    return record


async def test_a_cog_kept_at_publish_and_read_by_nothing_after_is_left_to_the_sweep(
    test_db_session, raster_storage, tmp_path, monkeypatch
) -> None:
    """The follow-ups leave a COG the publish charged, even with no reader left.

    Its charge names it, so the sweep deletes it and then the charge.
    """
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    cog = member.cog_key
    member_id, member_record = member.dataset.id, member.dataset.record_id
    await _set_counted_data_bytes(test_db_session, member_id, OLD_BYTES)
    monkeypatch.setattr(tasks_raster_replace, "cog_readers", _a_reader)
    try:
        job_id = await _replace(
            test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
        )

        assert await _left(raster_storage, (cog,)) == [cog]
        assert await _retained(test_db_session, member_id) == [(cog, OLD_BYTES)]
        assert await _owed(test_db_session, job_id) is None

        await reclaim_retained_cogs()

        assert await _left(raster_storage, (cog,)) == []
        assert await _retained(test_db_session, member_id) == []
    finally:
        await _purge(test_db_session, dataset_id=member_id, record_id=member_record)


async def test_a_cog_whose_readers_cannot_be_read_stays_owed(
    test_db_session, raster_storage, tmp_path, monkeypatch
) -> None:
    """The follow-ups neither delete nor drop a COG they can't clear, and retry it once due."""
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    cog, ql256, ql512 = _old_keys(member)
    member_id, member_record = member.dataset.id, member.dataset.record_id

    async def _unreadable(*_args, **_kwargs):
        raise RuntimeError("connection lost")

    real_readers = vrt_members.cog_readers
    monkeypatch.setattr(vrt_members, "cog_readers", _unreadable)
    try:
        job_id = await _replace(
            test_db_session, tmp_path, dataset_id=member_id, admin_id=admin_id
        )

        assert await _left(raster_storage, (cog, ql256, ql512)) == [cog]
        record = await _owed(test_db_session, job_id)
        assert record["superseded_cog"]["key"] == cog
        assert "superseded_keys" not in record

        monkeypatch.setattr(vrt_members, "cog_readers", real_readers)
        await _make_due(job_id)
        await run_owed_publish_followups()

        assert await _left(raster_storage, (cog,)) == []
        assert await _owed(test_db_session, job_id) is None
    finally:
        await _purge(test_db_session, dataset_id=member_id, record_id=member_record)


@pytest.mark.parametrize("fails", ["before the delete", "after the delete"])
async def test_the_sweep_uncharges_a_cog_only_once_its_object_is_gone(
    test_db_session, raster_storage, tmp_path, monkeypatch, fails: str
) -> None:
    """A sweep cut short around the object delete leaves the charge for the next one."""
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    cog = member.cog_key
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    await _set_built_from(test_db_session, ids[0], {str(ids[2]): cog})
    await _set_counted_data_bytes(test_db_session, ids[2], OLD_BYTES)
    real_delete = raster_storage.delete

    async def _cut_short(key: str) -> None:
        if fails == "after the delete":
            await real_delete(key)
        raise OSError("storage unavailable")

    try:
        await _replace(test_db_session, tmp_path, dataset_id=ids[2], admin_id=admin_id)
        await _set_built_from(
            test_db_session, ids[0], {str(ids[2]): "rasters/elsewhere.cog.tif"}
        )

        monkeypatch.setattr(raster_storage, "delete", _cut_short)
        await reclaim_retained_cogs()
        monkeypatch.setattr(raster_storage, "delete", real_delete)

        assert await _left(raster_storage, (cog,)) == (
            [cog] if fails == "before the delete" else []
        )
        assert await _retained(test_db_session, ids[2]) == [(cog, OLD_BYTES)]

        await reclaim_retained_cogs()

        assert await _left(raster_storage, (cog,)) == []
        assert await _retained(test_db_session, ids[2]) == []
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_replace_and_regenerate_cycles_keep_one_charged_cog_at_most(
    test_db_session, raster_storage, tmp_path
) -> None:
    """Each cycle's kept COG is reclaimed once the VRT is rebuilt, so none pile up."""
    owner_id = await _make_owner(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=owner_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=owner_id, member=member
    )
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    cog = member.cog_key
    await _set_built_from(test_db_session, ids[0], {str(ids[2]): cog})
    await _set_counted_data_bytes(test_db_session, ids[2], OLD_BYTES)
    superseded: list[str] = []
    try:
        for cycle in range(3):
            old_bytes = await _data_bytes(test_db_session, ids[2])
            superseded.append(await _live_cog(test_db_session, ids[2]))
            await _replace(
                test_db_session,
                tmp_path,
                dataset_id=ids[2],
                admin_id=owner_id,
                seed=100 + cycle,
            )
            new_bytes = await _data_bytes(test_db_session, ids[2])
            assert await _retained(test_db_session, ids[2]) == [
                (superseded[-1], old_bytes)
            ]
            assert await _usage(test_db_session, owner_id) == new_bytes + old_bytes

            await _put_cog_where_vrts_read(await _live_cog(test_db_session, ids[2]))
            await _regenerate_with(
                test_db_session, parent_id=ids[0], members=[ids[2]], user_id=owner_id
            )
            await reclaim_retained_cogs()

            assert await _retained(test_db_session, ids[2]) == []
            assert await _usage(test_db_session, owner_id) == new_bytes
            assert await _left(raster_storage, superseded) == []
    finally:
        await _purge_vrt(test_db_session, ids=ids)
        await _drop_owner(test_db_session, owner_id)


@pytest.mark.parametrize("owed", [True, False])
async def test_an_unpublished_key_a_replacement_still_owes_as_its_cog_is_not_reaped(
    test_db_session, raster_storage, owed: bool
) -> None:
    """The stale-job reap leaves a superseded COG to the replacement's follow-ups.

    An earlier job that published the COG can still name it among its
    unpublished keys while a VRT that noted the member after the replacement
    looked is reading it.
    """
    from app.platform.jobs.sweep import reap_unpublished_storage_keys

    admin_id = await _admin_id(test_db_session)
    cog = f"rasters/{uuid.uuid4()}/attempts/{uuid.uuid4()}/sha/source.cog.tif"
    await raster_storage.put(cog, io.BytesIO(b"read by a VRT"))
    job = IngestJob(
        source_filename="replacement.tif",
        created_by=admin_id,
        status="complete",
        user_metadata={},
    )
    test_db_session.add(job)
    await test_db_session.flush()
    if owed:
        job.user_metadata = {
            PUBLISH_FOLLOWUPS_FIELD: {
                "task": "reupload_raster",
                "attempt_id": str(job.attempt_id),
                "superseded_cog": {"key": cog, "bytes": 1},
            }
        }
    await test_db_session.commit()
    job_id = job.id
    try:
        reaped = await reap_unpublished_storage_keys((cog,))

        assert reaped == ((0, 1, 0) if owed else (1, 0, 0))
        assert await raster_storage.exists(cog) is owed
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()


async def test_an_admin_cleanup_reclaims_a_kept_cog_nothing_reads(
    client, admin_auth_header, test_db_session, raster_storage
) -> None:
    """The explicit stale-job cleanup reclaims kept COGs, as the background sweep does."""
    admin_id = await _admin_id(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    member_id, member_record = member.dataset.id, member.dataset.record_id
    kept = f"rasters/{member_id}/superseded/source.cog.tif"
    await raster_storage.put(kept, io.BytesIO(b"kept"))
    await vrt_members.retain_cog(
        test_db_session,
        dataset_id=member_id,
        attempt_id=uuid.uuid4(),
        asset_uri=kept,
        size_bytes=OLD_BYTES,
    )
    await test_db_session.commit()
    try:
        response = await client.post("/jobs/cleanup/stale/", headers=admin_auth_header)

        assert response.status_code == 200, response.text
        assert await _left(raster_storage, (kept,)) == []
        assert await _retained(test_db_session, member_id) == []
    finally:
        await _purge(test_db_session, dataset_id=member_id, record_id=member_record)
