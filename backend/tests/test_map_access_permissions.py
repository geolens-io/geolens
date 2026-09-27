"""Map route access follows the permission policy and mutation ownership gate."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from app.core.persistent_config import ROLE_PERMISSIONS
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.maps import router
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.service import check_map_ownership
from app.platform import extensions

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("_clean_registry")]


@pytest.mark.parametrize(
    "role,granted,owner,expected",
    [
        ("viewer", True, True, True),
        ("cartographer", True, True, True),
        ("viewer", True, False, False),
        ("cartographer", True, False, False),
        ("viewer", False, True, False),
        ("editor", True, True, True),
        ("editor", True, False, False),
        ("editor", False, True, False),
        ("admin", True, False, True),
        ("admin", False, False, False),
    ],
)
async def test_map_access_matches_mutation_guards(
    monkeypatch, role, granted, owner, expected
):
    user = SimpleNamespace(id=uuid4())
    map_obj = Map(
        id=uuid4(),
        created_by=user.id if owner else uuid4(),
        visibility="public",
    )
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(role,)]
    db.execute.return_value = result
    monkeypatch.setattr(
        ROLE_PERMISSIONS,
        "get",
        AsyncMock(return_value={role: {"edit_metadata": granted}}),
    )
    monkeypatch.setattr(router, "get_map", AsyncMock(return_value=map_obj))

    response = await router.get_map_access_endpoint(map_obj.id, user, db)

    assert response.can_view is True
    assert response.can_edit is expected
    request = Request({"type": "http", "method": "PATCH", "path": "/maps/"})
    if expected:
        await require_permission("edit_metadata")(request, user, db)
        await check_map_ownership(map_obj, user, db)
    else:
        with pytest.raises(HTTPException) as exc:
            await require_permission("edit_metadata")(request, user, db)
            await check_map_ownership(map_obj, user, db)
        assert exc.value.status_code == 403


@pytest.mark.parametrize("granted", [True, False])
async def test_map_access_honors_permission_extension(monkeypatch, granted):
    user = SimpleNamespace(id=uuid4())
    map_obj = Map(id=uuid4(), created_by=user.id, visibility="public")
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [("editor",)]
    db.execute.return_value = result
    monkeypatch.setattr(
        ROLE_PERMISSIONS,
        "get",
        AsyncMock(return_value={"editor": {"edit_metadata": not granted}}),
    )
    monkeypatch.setattr(router, "get_map", AsyncMock(return_value=map_obj))
    extension = SimpleNamespace(check_permission=AsyncMock(return_value=granted))
    extensions._extensions["permission"] = extension

    response = await router.get_map_access_endpoint(map_obj.id, user, db)

    assert response.can_edit is granted
    extension.check_permission.assert_awaited_once()
    args, kwargs = extension.check_permission.call_args
    assert args == (db, user, "edit_metadata")
    assert kwargs["user_roles"] == {"editor"}
    assert kwargs["permission_matrix"]["editor"]["edit_metadata"] is not granted


async def test_anonymous_map_access_cannot_edit(monkeypatch):
    map_obj = Map(id=uuid4(), created_by=uuid4(), visibility="public")
    db = AsyncMock()
    monkeypatch.setattr(router, "get_map", AsyncMock(return_value=map_obj))

    response = await router.get_map_access_endpoint(map_obj.id, None, db)

    assert response.can_view is True
    assert response.can_edit is False
    db.execute.assert_not_awaited()
