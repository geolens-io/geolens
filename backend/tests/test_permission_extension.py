"""Tests for PermissionExtension Protocol, default behavior, and overlay dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select


def _reset_registry():
    """Reset extension registry state between tests."""
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate tests from environment-discovered extension entry points."""
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


def test_default_permission_extension_registered():
    """Community mode returns the default and it satisfies the Protocol."""
    from app.platform.extensions import get_permission_extension
    from app.platform.extensions.defaults import DefaultPermissionExtension
    from app.platform.extensions.protocols import PermissionExtension

    extension = get_permission_extension()

    assert isinstance(extension, DefaultPermissionExtension)
    assert isinstance(extension, PermissionExtension)


@pytest.mark.asyncio
async def test_default_permission_extension_uses_effective_matrix():
    """Default check_permission preserves role-matrix grant behavior."""
    from app.platform.extensions.defaults import DefaultPermissionExtension

    extension = DefaultPermissionExtension()
    matrix = {
        "viewer": {"upload": False, "export": True},
        "editor": {"upload": True, "export": True},
    }

    assert (
        await extension.check_permission(
            MagicMock(),
            SimpleNamespace(id="user-1"),
            "upload",
            user_roles={"viewer"},
            permission_matrix=matrix,
        )
        is False
    )
    assert (
        await extension.check_permission(
            MagicMock(),
            SimpleNamespace(id="user-1"),
            "upload",
            user_roles={"viewer", "editor"},
            permission_matrix=matrix,
        )
        is True
    )


def test_default_permission_extension_filters_visible_records():
    """Default filter_visible keeps existing admin and anonymous behavior."""
    from app.modules.catalog.datasets.domain.models import DatasetGrant, Record
    from app.platform.extensions.defaults import DefaultPermissionExtension

    extension = DefaultPermissionExtension()
    stmt = select(Record)

    assert extension.filter_visible(stmt, None, {"admin"}, Record, DatasetGrant) is stmt

    filtered = extension.filter_visible(stmt, None, set(), Record, DatasetGrant)
    where_text = str(filtered.whereclause)
    assert "visibility" in where_text
    assert "record_status" in where_text


@pytest.mark.asyncio
async def test_overlay_permission_extension_is_dispatched():
    """An entry-point overlay can replace the singleton permission policy."""
    from app.modules.catalog.datasets.domain.models import DatasetGrant, Record
    from app.platform.extensions import get_permission_extension, load_extensions

    class TestPermissionExtension:
        async def check_permission(
            self,
            db,
            user,
            capability,
            *,
            user_roles,
            permission_matrix=None,
            resource=None,
        ):
            return capability == "allowed_action"

        def filter_visible(self, stmt, user, user_roles, record_cls, grant_cls=None):
            return stmt.where(record_cls.title == "Visible")

        async def can_access_dataset(
            self, db, dataset, dataset_id, user, *, user_roles
        ):
            return False

    def register(registry: dict) -> None:
        registry["permission"] = TestPermissionExtension()

    mock_ep = MagicMock()
    mock_ep.name = "geolens.permission.test"
    mock_ep.load.return_value = register

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        extension = get_permission_extension()

    assert (
        await extension.check_permission(
            MagicMock(),
            SimpleNamespace(id="user-1"),
            "allowed_action",
            user_roles={"viewer"},
        )
        is True
    )
    assert (
        await extension.check_permission(
            MagicMock(),
            SimpleNamespace(id="user-1"),
            "denied_action",
            user_roles={"admin"},
        )
        is False
    )

    filtered = extension.filter_visible(
        select(Record),
        SimpleNamespace(id="user-1"),
        {"viewer"},
        Record,
        DatasetGrant,
    )
    assert filtered is not None
    assert "title" in str(filtered.whereclause)


@pytest.mark.asyncio
async def test_require_permission_delegates_to_permission_extension():
    """require_permission denies when the registered extension denies."""
    import app.platform.extensions as ext_mod
    from app.modules.auth.dependencies import require_permission

    class DenyPermissionExtension:
        async def check_permission(
            self,
            db,
            user,
            capability,
            *,
            user_roles,
            permission_matrix=None,
            resource=None,
        ):
            assert capability == "upload"
            assert user_roles == {"viewer"}
            assert permission_matrix == {"viewer": {"upload": True}}
            return False

        def filter_visible(self, stmt, user, user_roles, record_cls, grant_cls=None):
            return stmt

        async def can_access_dataset(
            self, db, dataset, dataset_id, user, *, user_roles
        ):
            return True

    ext_mod._extensions["permission"] = DenyPermissionExtension()
    request = SimpleNamespace(
        state=SimpleNamespace(
            _user_roles={"viewer"},
            _effective_permissions={"viewer": {"upload": True}},
        )
    )
    checker = require_permission("upload")

    with pytest.raises(HTTPException) as exc:
        await checker(request, SimpleNamespace(id=uuid4()), MagicMock())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Missing permission: upload"


def test_apply_visibility_filter_delegates_to_permission_extension():
    """Catalog list filtering uses the registered extension hook."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.authorization import apply_visibility_filter
    from app.modules.catalog.datasets.domain.models import DatasetGrant, Record

    class VisibilityPermissionExtension:
        async def check_permission(
            self,
            db,
            user,
            capability,
            *,
            user_roles,
            permission_matrix=None,
            resource=None,
        ):
            return True

        def filter_visible(self, stmt, user, user_roles, record_cls, grant_cls=None):
            assert user_roles == {"viewer"}
            assert grant_cls is DatasetGrant
            return stmt.where(record_cls.title == "Visible")

        async def can_access_dataset(
            self, db, dataset, dataset_id, user, *, user_roles
        ):
            return True

    ext_mod._extensions["permission"] = VisibilityPermissionExtension()

    filtered = apply_visibility_filter(
        select(Record),
        SimpleNamespace(id=uuid4()),
        {"viewer"},
        Record,
        DatasetGrant,
    )

    assert "title" in str(filtered.whereclause)


@pytest.mark.asyncio
async def test_check_dataset_access_delegates_to_permission_extension():
    """Dataset detail authorization cannot bypass stricter overlay policy."""
    import app.platform.extensions as ext_mod
    from app.modules.catalog.authorization import check_dataset_access

    class DenyDatasetPermissionExtension:
        async def check_permission(
            self,
            db,
            user,
            capability,
            *,
            user_roles,
            permission_matrix=None,
            resource=None,
        ):
            return True

        def filter_visible(self, stmt, user, user_roles, record_cls, grant_cls=None):
            return stmt

        async def can_access_dataset(
            self, db, dataset, dataset_id, user, *, user_roles
        ):
            assert user_roles == {"viewer"}
            return False

    ext_mod._extensions["permission"] = DenyDatasetPermissionExtension()
    dataset = SimpleNamespace(record=SimpleNamespace(visibility="public"))

    with pytest.raises(HTTPException) as exc:
        await check_dataset_access(
            MagicMock(),
            dataset,
            uuid4(),
            SimpleNamespace(id=uuid4()),
            user_roles={"viewer"},
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Dataset not found"
