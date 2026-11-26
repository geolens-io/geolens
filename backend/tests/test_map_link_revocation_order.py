"""A write that narrows a map revokes its links only once nothing can refuse it."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.maps import manifest_apply
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.stories.groups import sharing_blocking_maps
from app.modules.catalog.stories.schemas import BlockingMap
from app.modules.catalog.stories.service import StoryReachError
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import (
    create_embed_token,
    validate_embed_token_access,
)
from app.platform.cache import init_cache
from tests.test_api_key_scope_875 import _remove_keys_minted_by_the_test  # noqa: F401
from tests.test_manifest_maps_apply import _apply, _dataset, _map
from tests.test_manifest_maps_dry_run import _admin, _layer
from tests.test_map_dashboard_config import _widget
from tests.test_map_group_sharing import OPT_IN, _share, layered, owned  # noqa: F401

pytestmark = pytest.mark.anyio

# A widget on a layer the map doesn't have: refused by the dashboard merge,
# which runs after the save has worked out the map's new visibility.
_REFUSED_DASHBOARD = {"widgets": [_widget("indicator", uuid.uuid4())]}


async def _mint(session, map_id, owner_id) -> tuple[uuid.UUID, str, uuid.UUID]:
    """An embed token for the map, validated once so its acceptance is cached:
    its id, raw value and the dataset it is scoped to."""
    init_cache()
    token, raw = await create_embed_token(session, map_id, owner_id)
    await session.commit()
    dataset_id = await session.scalar(
        select(MapLayer.dataset_id).where(MapLayer.map_id == map_id)
    )
    assert await validate_embed_token_access(raw, dataset_id, session)
    return token.id, raw, dataset_id


async def _state(session, raw, dataset_id, token_id) -> tuple[bool, bool]:
    """Whether the token's row is active, and whether it validates."""
    session.expire_all()
    active = await session.scalar(
        select(EmbedToken.is_active).where(EmbedToken.id == token_id)
    )
    return active, await validate_embed_token_access(raw, dataset_id, session)


async def _narrowable(client: AsyncClient, ctx: dict, start: str) -> None:
    """Put the fixture's map at ``start``: public, or internal with a group."""
    url = f"/maps/{ctx['map']}"
    resp = await client.put(url, json={"visibility": start}, headers=ctx["owner"])
    assert resp.status_code == 200, resp.text
    if start == "internal":
        shared = await _share(client, ctx["map"], [ctx["mine"]], ctx["owner"])
        assert shared.status_code == 200, shared.text


@pytest.mark.parametrize("start", ["public", "internal"])
async def test_a_refused_narrowing_save_leaves_the_embed_token_valid(
    client: AsyncClient,
    layered,  # noqa: F811
    test_db_session,
    start,
):
    await _narrowable(client, layered, start)
    map_id = uuid.UUID(layered["map"])
    token_id, raw, dataset_id = await _mint(
        test_db_session, map_id, uuid.UUID(layered["owner_id"])
    )

    refused = await client.put(
        f"/maps/{map_id}",
        json={"visibility": "private", "dashboard_config": _REFUSED_DASHBOARD},
        headers=layered["owner"],
    )

    assert refused.status_code == 422, refused.text
    assert await _state(test_db_session, raw, dataset_id, token_id) == (True, True)


@pytest.mark.parametrize("start", ["public", "internal"])
async def test_a_narrowing_save_revokes_the_embed_token(
    client: AsyncClient,
    layered,  # noqa: F811
    test_db_session,
    start,
):
    await _narrowable(client, layered, start)
    map_id = uuid.UUID(layered["map"])
    token_id, raw, dataset_id = await _mint(
        test_db_session, map_id, uuid.UUID(layered["owner_id"])
    )

    narrowed = await client.put(
        f"/maps/{map_id}",
        json={"visibility": "private"},
        headers={**layered["owner"], **OPT_IN},
    )

    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["visibility"] == (
        "private" if start == "public" else "restricted"
    )
    assert await _state(test_db_session, raw, dataset_id, token_id) == (False, False)


async def _published_map(session, *datasets: uuid.UUID) -> tuple[dict, uuid.UUID]:
    admin = await _admin(session)
    layers = [_layer(f"l{i}", dataset_id=str(d)) for i, d in enumerate(datasets)]
    entry = _map("qgis-map-revoke-order", *layers, visibility="public")
    [created] = (await _apply(session, admin, entry)).maps
    assert created.action == "create", created
    return entry, created.map_id


_LATE_REFUSAL = HTTPException(status_code=409, detail="refused late")


@pytest.mark.parametrize("change", ["narrow", "drop_layer"])
async def test_a_manifest_map_refused_after_its_write_keeps_its_embed_token(
    test_db_session, clean_tables, change
):
    admin = await _admin(test_db_session)
    parks = await _dataset(test_db_session, admin.id)
    trails = await _dataset(test_db_session, admin.id)
    entry, map_id = await _published_map(test_db_session, parks, trails)
    token_id, raw, _ = await _mint(test_db_session, map_id, admin.id)
    if change == "narrow":
        entry = {**entry, "visibility": "private"}
    else:
        entry = {**entry, "layers": entry["layers"][:1]}

    with patch.object(
        manifest_apply,
        "record_map_history_event",
        AsyncMock(side_effect=_LATE_REFUSAL),
    ):
        [refused] = (await _apply(test_db_session, admin, entry)).maps

    assert refused.action == "error", refused
    assert await _state(test_db_session, raw, parks, token_id) == (True, True)

    [applied] = (await _apply(test_db_session, admin, entry)).maps

    assert applied.action == "update", applied
    assert await _state(test_db_session, raw, parks, token_id) == (False, False)


async def _share_blocking_map(session, ctx: dict, second_attempt) -> None:
    map_id = uuid.UUID(ctx["map"])
    blocking = BlockingMap(id=map_id, name="blocking", can_share=True)
    reach = StoryReachError([blocking], 0, {map_id: {uuid.UUID(ctx["mine"])}})
    attempts = AsyncMock(side_effect=[reach, second_attempt])
    await sharing_blocking_maps(session, attempts, await _admin(session), "share_maps")


async def test_a_story_attempt_refused_after_sharing_a_map_keeps_its_embed_token(
    layered,  # noqa: F811
    test_db_session,
):
    map_id = uuid.UUID(layered["map"])
    token_id, raw, dataset_id = await _mint(
        test_db_session, map_id, uuid.UUID(layered["owner_id"])
    )

    with pytest.raises(HTTPException):
        await _share_blocking_map(test_db_session, layered, _LATE_REFUSAL)
    await test_db_session.rollback()

    assert await _state(test_db_session, raw, dataset_id, token_id) == (True, True)

    await _share_blocking_map(test_db_session, layered, None)
    await test_db_session.commit()

    assert await _state(test_db_session, raw, dataset_id, token_id) == (False, False)
