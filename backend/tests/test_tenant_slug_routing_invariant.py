"""Tenant host slugs are deterministic database routing keys."""

from __future__ import annotations

import importlib.util
import inspect
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.modules.tenancy.models import Tenant

_MIGRATION_PATH = (
    Path(__file__).parent.parent / "alembic" / "versions" / "0023_tenant_slug_unique.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0023_tenant_slug_unique",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_diagnoses_duplicates_and_adopts_cloud_index():
    migration = _load_migration()
    source = _MIGRATION_PATH.read_text()

    assert migration.revision == "0023_tenant_slug_unique"
    assert migration.down_revision == "0022_tenant_audit_job_isolation"
    assert "HAVING count(*) > 1" in source
    assert "cannot make tenant routing slugs unique" in source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_slug" in source
    assert "DROP INDEX IF EXISTS catalog.ix_tenants_slug" in source
    assert "LIMIT 1" not in inspect.getsource(migration.upgrade)


def test_tenant_model_declares_unique_routing_index():
    index = next(
        candidate
        for candidate in Tenant.__table__.indexes
        if candidate.name == "uq_tenants_slug"
    )
    assert index.unique is True
    assert [column.name for column in index.columns] == ["slug"]


async def test_live_database_rejects_duplicate_host_slugs(test_db_session):
    slug = f"routing-{uuid.uuid4().hex}"
    await test_db_session.execute(
        sa.text(
            "INSERT INTO catalog.tenants (id, slug, name) "
            "VALUES (:id, :slug, 'Routing tenant A')"
        ),
        {"id": uuid.uuid4(), "slug": slug},
    )

    with pytest.raises(IntegrityError):
        async with test_db_session.begin_nested():
            await test_db_session.execute(
                sa.text(
                    "INSERT INTO catalog.tenants (id, slug, name) "
                    "VALUES (:id, :slug, 'Routing tenant B')"
                ),
                {"id": uuid.uuid4(), "slug": slug},
            )
