"""Every sink of a VRT's extent shows the requester's view or nothing.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.models import User
from app.modules.catalog.authorization import get_user_roles
from app.platform.extensions import get_processing_port
from tests.factories import create_collection_via_api
from tests.test_vrt_extent_visibility import (
    FULL,
    HIDDEN,
    READABLE,
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
    _make_editor,
    _rounded,
    _set_extent,
    _vrt_with_members,
)


async def _viewer(client, admin_auth_header, session):
    headers, user_id = await _make_editor(client, admin_auth_header)
    user = await session.get(User, user_id)
    return headers, user, await get_user_roles(session, user)


async def _title_token(session, vrt_id) -> str:
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    title = await session.scalar(
        select(Record.title)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == vrt_id)
    )
    return title.split(" ")[3]


async def test_collection_dataset_listing_shows_the_readable_extent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    headers, _, _ = await _viewer(client, admin_auth_header, test_db_session)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    collection = await create_collection_via_api(client, admin_auth_header)
    added = await client.post(
        f"/catalog/collections/{collection['id']}/datasets/",
        json={"dataset_ids": [str(vrt_id)]},
        headers=admin_auth_header,
    )
    assert added.status_code == 200, added.text

    async def listed(request_headers):
        resp = await client.get(
            f"/catalog/collections/{collection['id']}/datasets/",
            headers=request_headers,
        )
        assert resp.status_code == 200, resp.text
        (row,) = [d for d in resp.json()["datasets"] if d["id"] == str(vrt_id)]
        return _rounded(row["extent_bbox"])

    assert await listed(headers) == READABLE
    assert await listed(admin_auth_header) == FULL


async def test_metadata_patch_response_shows_the_owners_readable_extent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A VRT's owner who cannot read another owner's member edits its metadata."""
    headers, owner, _ = await _viewer(client, admin_auth_header, test_db_session)
    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=owner.id, visibility="private"
    )
    await _set_extent(test_db_session, vrt_id, FULL)
    for position, (created_by, bounds) in enumerate(
        ((owner.id, READABLE), (admin_id, HIDDEN))
    ):
        member = await _create_raster_dataset(
            test_db_session, created_by=created_by, visibility="private"
        )
        await _set_extent(test_db_session, member, bounds)
        await _link_source(test_db_session, vrt_id, member, position)

    resp = await client.patch(
        f"/datasets/{vrt_id}", json={"summary": "edited"}, headers=headers
    )

    assert resp.status_code == 200, resp.text
    assert _rounded(resp.json()["extent_bbox"]) == READABLE


async def test_ai_search_results_leave_out_vrt_extents(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    from app.processing.ai.service import _execute_search_tool

    _, viewer, roles = await _viewer(client, admin_auth_header, test_db_session)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )

    results = await _execute_search_tool(
        test_db_session,
        viewer,
        roles,
        {"q": await _title_token(test_db_session, vrt_id)},
        port=get_processing_port(),
    )

    (hit,) = [r for r in results if r["id"] == str(vrt_id)]
    assert hit["extent_bbox"] is None


async def test_generated_map_viewport_ignores_vrt_extents(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    import app.processing.ai.service as ai_service
    from app.processing.ai.schemas import LLMLayerSpec, LLMMapSpec

    _, viewer, roles = await _viewer(client, admin_auth_header, test_db_session)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    seen: list[list[object]] = []
    monkeypatch.setattr(
        ai_service,
        "_snap_viewport_to_extent",
        lambda spec, extents: seen.append(list(extents)),
    )
    spec = LLMMapSpec(
        name=f"vrt viewport {uuid.uuid4().hex[:6]}",
        center_lng=-100.0,
        center_lat=-40.0,
        zoom=3.0,
        layers=[LLMLayerSpec(dataset_id=str(vrt_id))],
    )

    try:
        await ai_service._validate_and_persist_map(
            test_db_session, viewer, roles, spec, port=get_processing_port()
        )
    finally:
        await test_db_session.rollback()

    assert seen == [[None]]


async def test_metadata_prompt_context_leaves_out_vrt_extents(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    from app.processing.ai import metadata_service

    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    metadata_service._dataset_context_cache.clear()

    context = await metadata_service._build_dataset_context(
        test_db_session, str(vrt_id), port=get_processing_port()
    )

    assert "51.0000" not in context
    assert "latitude" not in context
