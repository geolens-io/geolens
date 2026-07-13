"""Regression coverage for hosted control-plane and legacy child-table scope."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.modules.admin.service import AdminService
from app.modules.auth.dependencies import require_mode_permission
from app.modules.catalog.maps.service_public import revoke_share_token
from app.processing.ingest.manifest_service import _latest_in_flight_manifest_job
from app.processing.ingest.service import get_job_or_404


@pytest.fixture
def multi_tenant(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "expected"),
    [("single_tenant", "manage_settings"), ("multi_tenant", "manage_tenants")],
)
async def test_mode_permission_selects_fleet_capability(
    mode: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
):
    observed = []

    class _PermissionExtension:
        async def check_permission(
            self,
            _db,
            _user,
            capability,
            *,
            user_roles,
            permission_matrix=None,
            resource=None,
        ):
            observed.append(capability)
            return True

    monkeypatch.setattr(settings, "geolens_tenancy_mode", mode)
    monkeypatch.setattr(
        "app.modules.auth.dependencies.get_permission_extension",
        lambda: _PermissionExtension(),
    )
    checker = require_mode_permission(
        single_tenant="manage_settings", multi_tenant="manage_tenants"
    )
    request = SimpleNamespace(
        state=SimpleNamespace(
            _user_roles={"admin"},
            _effective_permissions={"admin": {expected: True}},
        )
    )

    await checker(
        request=request,
        current_user=SimpleNamespace(id=uuid.uuid4()),
        db=MagicMock(),
    )

    assert observed == [expected]


@pytest.mark.anyio
async def test_ingest_job_lookup_relies_on_durable_rls_scope(multi_tenant):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc:
        await get_job_or_404(
            db,
            uuid.uuid4(),
            SimpleNamespace(id=uuid.uuid4()),
        )

    assert exc.value.status_code == 404
    sql = str(db.execute.await_args.args[0])
    assert "catalog.ingest_jobs.id" in sql
    assert "SELECT catalog.users.id" not in sql


@pytest.mark.anyio
async def test_manifest_in_flight_lookup_relies_on_durable_rls_scope(multi_tenant):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    assert await _latest_in_flight_manifest_job(db, "shared-key") is None

    sql = str(db.execute.await_args.args[0])
    assert "catalog.ingest_jobs" in sql
    assert "SELECT catalog.users.id" not in sql


@pytest.mark.anyio
async def test_admin_job_count_relies_on_durable_rls_scope(multi_tenant):
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    list_result = MagicMock()
    list_result.all.return_value = []
    db = AsyncMock()
    db.execute.side_effect = [count_result, list_result]

    rows, total = await AdminService(db).list_jobs()

    assert rows == []
    assert total == 0
    count_sql = str(db.execute.await_args_list[0].args[0])
    assert "catalog.ingest_jobs" in count_sql
    assert "SELECT catalog.users.id" not in count_sql


@pytest.mark.anyio
async def test_share_token_revoke_joins_rls_visible_map(multi_tenant):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    assert await revoke_share_token(db, uuid.uuid4()) is None

    sql = str(db.execute.await_args.args[0])
    assert "JOIN catalog.maps" in sql


def test_collection_names_have_global_and_tenant_unique_indexes():
    from app.modules.catalog.collections.models import Collection

    indexes = {index.name: index for index in Collection.__table__.indexes}

    assert indexes["uq_collections_name_global"].unique is True
    assert indexes["uq_collections_name_tenant"].unique is True
    assert [
        column.name for column in indexes["uq_collections_name_tenant"].columns
    ] == [
        "tenant_id",
        "name",
    ]
