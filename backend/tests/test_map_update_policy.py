"""``apply_map_update`` called without the PUT handler around it."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.maps.models import Map, MapEditHistoryEvent, MapShareToken
from app.modules.catalog.maps.schemas import MapUpdate
from app.modules.catalog.maps.service import create_share_token
from app.modules.catalog.maps.service_update import apply_map_update

from tests.factories import get_user_id


async def _admin_and_map(
    session: AsyncSession, visibility: str
) -> tuple[User, uuid.UUID]:
    admin_id = await get_user_id(session, settings.geolens_admin_username)
    map_obj = Map(
        name=f"Update policy {uuid.uuid4().hex[:6]}",
        visibility=visibility,
        created_by=admin_id,
    )
    session.add(map_obj)
    await session.commit()
    return await session.get(User, admin_id), map_obj.id


async def _history_count(session: AsyncSession, map_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(MapEditHistoryEvent)
        .where(MapEditHistoryEvent.map_id == map_id)
    )


@pytest.mark.parametrize("record_history", [True, False])
async def test_history_is_written_only_when_asked(
    test_db_session: AsyncSession, record_history: bool
) -> None:
    admin, map_id = await _admin_and_map(test_db_session, "private")
    map_obj = await test_db_session.get(Map, map_id)

    saved, *_ = await apply_map_update(
        test_db_session,
        map_obj,
        MapUpdate(name="Renamed", zoom=7),
        admin,
        record_history=record_history,
        ip_address=None,
    )
    await test_db_session.commit()

    assert saved.name == "Renamed"
    expected = 2 if record_history else 0
    assert await _history_count(test_db_session, map_id) == expected


async def test_leaving_public_revokes_the_share_token(
    test_db_session: AsyncSession,
) -> None:
    admin, map_id = await _admin_and_map(test_db_session, "public")
    share = await create_share_token(test_db_session, map_id, admin.id)
    await test_db_session.commit()
    share_id = share.id
    map_obj = await test_db_session.get(Map, map_id)

    await apply_map_update(
        test_db_session,
        map_obj,
        MapUpdate(visibility="private"),
        admin,
        record_history=False,
        ip_address=None,
    )
    await test_db_session.commit()

    test_db_session.expire_all()
    assert (await test_db_session.get(Map, map_id)).visibility == "private"
    assert (await test_db_session.get(MapShareToken, share_id)).is_active is False
