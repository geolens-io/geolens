"""Shared steps for the write re-check race tests: a change to the caller's
standing, committed from a second session while the request is in flight."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
)
from app.modules.catalog.maps.models import Map, MapLayer
from tests.factories import create_dataset, create_user


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, target_id = await create_user(client, admin_auth_header, "editor")
    admin_headers, admin_id = await create_user(client, admin_auth_header, "admin")
    return {
        "owner": (owner_headers, uuid.UUID(owner_id)),
        "target": uuid.UUID(target_id),
        "admin": (admin_headers, uuid.UUID(admin_id)),
    }


async def _commit(statement) -> None:
    async with db_module.async_session() as session:
        await session.execute(statement)
        await session.commit()


def _transfer_dataset(dataset_id: uuid.UUID, owner_id: uuid.UUID):
    record_id = select(Dataset.record_id).where(Dataset.id == dataset_id)
    return (
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(created_by=owner_id)
    )


def _transfer_map(map_id: uuid.UUID, owner_id: uuid.UUID):
    return update(Map).where(Map.id == map_id).values(created_by=owner_id)


def _move_to_role(user_id: uuid.UUID, role: str):
    role_id = select(Role.id).where(Role.name == role).scalar_subquery()
    return update(UserRole).where(UserRole.user_id == user_id).values(role_id=role_id)


def _demote_to_viewer(user_id: uuid.UUID):
    return _move_to_role(user_id, "viewer")


def _deactivate(user_id: uuid.UUID):
    return (
        update(User)
        .where(User.id == user_id)
        .values(status="deactivated", is_active=False)
    )


def _then(guard: Callable[..., Awaitable], statement) -> Callable[..., Awaitable]:
    """``guard``, followed by committing ``statement`` from another session."""

    async def guarded(*args, **kwargs):
        result = await guard(*args, **kwargs)
        await _commit(statement)
        return result

    return guarded


async def _map_with_layer(
    session: AsyncSession, owner_id: uuid.UUID, *, visibility: str = "private"
) -> tuple[uuid.UUID, uuid.UUID]:
    dataset = await create_dataset(session, created_by=owner_id)
    map_obj = Map(name="Shared map", created_by=owner_id, visibility=visibility)
    session.add(map_obj)
    await session.flush()
    layer = MapLayer(map_id=map_obj.id, dataset_id=dataset.id, sort_order=0)
    session.add(layer)
    await session.commit()
    return map_obj.id, layer.id
