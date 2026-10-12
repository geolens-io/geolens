"""A VRT never reaches anyone who cannot read each of its member rasters."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.authorization import VRT_AUDIENCE_EXCEEDS_SOURCES
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
    _make_editor,
    _patch_defer,
)
from tests.test_vrt_staged_mutation_1327 import _capture_defer


async def _create_vrt_request(client, headers, source_ids, visibility):
    p_create, p_regen = _patch_defer()
    with p_create, p_regen:
        return await client.post(
            "/ingest/vrt/create",
            json={
                "source_dataset_ids": [str(i) for i in source_ids],
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": "Audience VRT",
                "visibility": visibility,
            },
            headers=headers,
        )


async def _servable_vrt(session, *, created_by, visibility) -> uuid.UUID:
    """A VRT whose asset records its members, so the tile check can open it."""
    vrt_id = await _create_vrt_dataset(
        session, created_by=created_by, visibility=visibility
    )
    await session.execute(
        text(
            "UPDATE catalog.raster_assets SET built_from = '{}'::jsonb "
            "WHERE dataset_id = :id"
        ),
        {"id": vrt_id},
    )
    await session.commit()
    return vrt_id


async def _raster_auth_check(client, dataset_id):
    return await client.get(
        "/tiles/raster-auth-check/", params={"dataset_id": str(dataset_id)}
    )


async def test_create_refuses_a_vrt_wider_than_a_source(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    sources = [
        await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="internal"
        ),
        await _create_raster_dataset(
            test_db_session, created_by=editor_id, visibility="public"
        ),
    ]

    public = await _create_vrt_request(client, editor_headers, sources, "public")
    internal = await _create_vrt_request(client, editor_headers, sources, "internal")

    assert public.status_code == 422, public.text
    assert public.json()["detail"] == VRT_AUDIENCE_EXCEEDS_SOURCES
    assert internal.status_code == 202, internal.text


async def test_add_source_refuses_a_source_narrower_than_the_vrt(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    deferred = _capture_defer(monkeypatch)
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    internal_src = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="internal"
    )

    resp = await client.post(
        f"/ingest/vrt/{vrt_id}/sources/",
        json={"source_dataset_id": str(internal_src)},
        headers=editor_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == VRT_AUDIENCE_EXCEEDS_SOURCES
    assert deferred == []


async def test_vrt_visibility_and_status_may_not_widen_past_a_member(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    internal_src = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="internal"
    )
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=editor_id, visibility="private"
    )
    await _link_source(test_db_session, vrt_id, internal_src, 0)

    to_public = await client.patch(
        f"/datasets/{vrt_id}", json={"visibility": "public"}, headers=editor_headers
    )
    to_internal = await client.patch(
        f"/datasets/{vrt_id}", json={"visibility": "internal"}, headers=editor_headers
    )

    assert to_public.status_code == 422, to_public.text
    assert to_public.json()["detail"] == VRT_AUDIENCE_EXCEEDS_SOURCES
    assert to_internal.status_code == 200, to_internal.text

    # Publishing is a widening too: an unpublished public VRT reaches only
    # its owner and admins until it is published.
    staged_id = await _create_vrt_dataset(
        test_db_session,
        created_by=editor_id,
        visibility="public",
        record_status="internal",
    )
    await _link_source(test_db_session, staged_id, internal_src, 0)
    publish = await client.patch(
        f"/datasets/{staged_id}/status/",
        json={"status": "published"},
        headers=editor_headers,
    )
    assert publish.status_code == 422, publish.text
    assert publish.json()["detail"] == VRT_AUDIENCE_EXCEEDS_SOURCES


async def test_regenerate_refuses_a_member_the_owner_can_no_longer_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    deferred = _capture_defer(monkeypatch)
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    narrowed_src = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )
    await _link_source(test_db_session, vrt_id, narrowed_src, 0)

    resp = await client.post(
        f"/datasets/{vrt_id}/vrt/regenerate/", headers=editor_headers
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == VRT_AUDIENCE_EXCEEDS_SOURCES
    assert deferred == []


async def _queue_regeneration(client, admin_auth_header, session, *, staged):
    """An editor's VRT over an admin's private raster and one of the editor's,
    queued for a rebuild of the given members (None: a plain regenerate)."""
    from datetime import datetime, timezone

    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset, VrtGeneration

    admin_id = await _get_admin_id(session)
    _, editor_id = await _make_editor(client, admin_auth_header)
    vrt_id = await _create_vrt_dataset(session, created_by=editor_id)
    narrowed_src = await _create_raster_dataset(
        session, created_by=admin_id, visibility="private"
    )
    own_src = await _create_raster_dataset(session, created_by=editor_id)
    await _link_source(session, vrt_id, narrowed_src, 0)
    await _link_source(session, vrt_id, own_src, 1)
    members = {"narrowed": narrowed_src, "own": own_src}
    generation = VrtGeneration(
        vrt_dataset_id=vrt_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=2,
        staged_source_ids=(
            None if staged is None else [str(members[name]) for name in staged]
        ),
    )
    session.add(generation)
    await session.flush()
    asset = (
        await session.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == vrt_id)
        )
    ).scalar_one()
    asset.status = "regenerating"
    asset.current_generation_id = generation.id
    job = IngestJob(status="pending", source_filename="audience-regenerate.vrt")
    session.add(job)
    await session.commit()
    return {
        "job_id": str(job.id),
        "attempt_id": str(job.attempt_id),
        "vrt_dataset_id": str(vrt_id),
        "generation_id": str(generation.id),
    }


class _MembersRead(Exception):
    pass


async def _run_regeneration(monkeypatch, kwargs):
    from app.processing.ingest.tasks import regenerate_vrt

    async def _snapshot(*args, **kw):
        raise _MembersRead

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.snapshot_member_sources", _snapshot
    )
    await regenerate_vrt.func(**kwargs)


async def test_regenerate_task_refuses_before_reading_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    kwargs = await _queue_regeneration(
        client, admin_auth_header, test_db_session, staged=None
    )

    with pytest.raises(ValueError, match="not visible to everyone"):
        await _run_regeneration(monkeypatch, kwargs)


async def test_regenerate_task_lets_a_removal_through(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    kwargs = await _queue_regeneration(
        client, admin_auth_header, test_db_session, staged=["narrowed"]
    )

    with pytest.raises(_MembersRead):
        await _run_regeneration(monkeypatch, kwargs)


async def test_owner_cannot_narrow_a_source_of_their_own_wider_vrt(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    src = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    await _link_source(test_db_session, vrt_id, src, 0)

    resp = await client.patch(
        f"/datasets/{src}", json={"visibility": "private"}, headers=editor_headers
    )

    assert resp.status_code == 422, resp.text
    assert "VRT" in resp.json()["detail"]


async def test_another_users_vrt_stops_serving_instead_of_blocking_the_owner(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    src = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    vrt_id = await _servable_vrt(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _link_source(test_db_session, vrt_id, src, 0)

    narrow = await client.patch(
        f"/datasets/{src}", json={"visibility": "private"}, headers=editor_headers
    )
    tiles = await _raster_auth_check(client, vrt_id)

    assert narrow.status_code == 200, narrow.text
    assert tiles.status_code == 409, tiles.text


async def test_a_vrt_within_its_members_audience_still_serves(
    client: AsyncClient, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    src = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    vrt_id = await _servable_vrt(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _link_source(test_db_session, vrt_id, src, 0)

    tiles = await _raster_auth_check(client, vrt_id)

    assert tiles.status_code == 200, tiles.text


async def test_narrowing_a_member_rolls_the_vrt_publication_version(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    src = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _link_source(test_db_session, vrt_id, src, 0)

    async def _version() -> int:
        return (
            await test_db_session.execute(
                text("SELECT publication_version FROM catalog.datasets WHERE id = :id"),
                {"id": vrt_id},
            )
        ).scalar_one() or 0

    before = await _version()
    narrow = await client.patch(
        f"/datasets/{src}", json={"visibility": "private"}, headers=editor_headers
    )
    test_db_session.expire_all()

    assert narrow.status_code == 200, narrow.text
    assert await _version() > before


async def test_transfer_may_not_leave_a_vrt_past_its_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, editor_id = await _make_editor(client, admin_auth_header)
    _, other_id = await _make_editor(client, admin_auth_header)
    src = await _create_raster_dataset(test_db_session, created_by=editor_id)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    await _link_source(test_db_session, vrt_id, src, 0)

    vrt_away = await client.patch(
        f"/datasets/{vrt_id}",
        json={"owner_id": str(other_id)},
        headers=admin_auth_header,
    )
    member_away = await client.patch(
        f"/datasets/{src}", json={"owner_id": str(other_id)}, headers=admin_auth_header
    )

    assert vrt_away.status_code == 422, vrt_away.text
    assert member_away.status_code == 422, member_away.text


async def test_transfer_with_a_widening_is_checked_as_one_change(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, editor_id = await _make_editor(client, admin_auth_header)
    _, other_id = await _make_editor(client, admin_auth_header)
    src = await _create_raster_dataset(test_db_session, created_by=editor_id)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    await _link_source(test_db_session, vrt_id, src, 0)

    resp = await client.patch(
        f"/datasets/{src}",
        json={"owner_id": str(other_id), "visibility": "public"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text


async def test_an_authority_whose_audience_is_stale_counts_every_member(
    test_db_session, monkeypatch
):
    from app.modules.catalog import authorization
    from app.platform.extensions import DefaultPermissionExtension, RecordAudienceQuery

    class _WiderReads(DefaultPermissionExtension):
        def filter_visible(self, *args, **kwargs):
            return super().filter_visible(*args, **kwargs)

    admin_id = await _get_admin_id(test_db_session)
    src = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    vrt = RecordAudienceQuery(
        dataset_id=None,
        record_id=None,
        owner_id=admin_id,
        visibility="private",
        record_status="published",
    )
    assert (
        await authorization.vrt_members_beyond_audience(test_db_session, [src], vrt)
        == []
    )

    monkeypatch.setattr(authorization, "get_permission_extension", _WiderReads)

    assert await authorization.vrt_members_beyond_audience(
        test_db_session, [src], vrt
    ) == [src]


async def test_an_account_the_authority_cannot_classify_counts_as_outside(
    test_db_session, monkeypatch
):
    import sqlalchemy as sa

    from app.modules.catalog import authorization
    from app.platform.extensions import (
        DefaultPermissionExtension,
        RecordAudience,
        RecordAudienceQuery,
    )

    class _Unclassified(DefaultPermissionExtension):
        async def record_audience(self, query, user_cls, *, grant_cls=None):
            community = await super().record_audience(
                query, user_cls, grant_cls=grant_cls
            )
            return RecordAudience(
                users=sa.and_(community.users, sa.cast(sa.null(), sa.Boolean)),
                includes_anonymous=community.includes_anonymous,
            )

    admin_id = await _get_admin_id(test_db_session)
    src = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    vrt = RecordAudienceQuery(
        dataset_id=None,
        record_id=None,
        owner_id=admin_id,
        visibility="private",
        record_status="published",
    )
    monkeypatch.setattr(authorization, "get_permission_extension", _Unclassified)

    assert await authorization.vrt_members_beyond_audience(
        test_db_session, [src], vrt
    ) == [src]


async def test_transfer_checks_the_incoming_owners_vrts(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, editor_id = await _make_editor(client, admin_auth_header)
    _, other_id = await _make_editor(client, admin_auth_header)
    src = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=other_id, visibility="public"
    )
    await _link_source(test_db_session, vrt_id, src, 0)

    resp = await client.patch(
        f"/datasets/{src}",
        json={"owner_id": str(other_id), "visibility": "private"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
