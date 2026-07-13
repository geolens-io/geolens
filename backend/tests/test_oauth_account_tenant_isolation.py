"""Tenant boundary regression tests for external OAuth account links."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.rls import RLS_TABLES
from app.modules.auth.oauth.models import OAuthAccount

pytestmark = pytest.mark.xdist_group("tenancy_global_state")

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_MIGRATION_PATH = (
    _BACKEND_DIR / "alembic" / "versions" / "0019_tenant_control_plane_hardening.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0019_tenant_control_plane_hardening",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_extends_the_fail_closed_tenant_boundary():
    migration = _load_migration()
    source = _MIGRATION_PATH.read_text()

    assert migration.revision == "0019_tenant_control_plane_hardening"
    assert migration.down_revision == "0018_tenant_dataset_table_names"
    assert "oauth_accounts" in RLS_TABLES
    assert "tenant_isolation_oauth_accounts" in source
    assert "current_setting('app.current_tenant')::uuid" in source
    assert "trg_stamp_current_tenant_on_insert" in source
    assert migration._STAMP_TRIGGER < migration._PARENT_TRIGGER
    assert migration._PARENT_TRIGGER == "trg_validate_oauth_account_user_tenant"
    assert "enforce_oauth_account_user_tenant" in source
    assert "SECURITY INVOKER" in source
    assert "IS DISTINCT FROM linked_user_tenant" in source
    assert "uq_oauth_accounts_provider_subject_global" in source
    assert "uq_oauth_accounts_provider_subject_tenant" in source
    assert "GEOLENS_TENANCY_MODE" not in source
    assert "app.core" not in source


def test_model_uses_global_and_per_tenant_external_subject_uniqueness():
    table = OAuthAccount.__table__
    indexes = {index.name: index for index in table.indexes}

    assert table.c.tenant_id.nullable is True
    global_index = indexes["uq_oauth_accounts_provider_subject_global"]
    tenant_index = indexes["uq_oauth_accounts_provider_subject_tenant"]
    assert [column.name for column in global_index.columns] == [
        "provider_id",
        "subject",
    ]
    assert [column.name for column in tenant_index.columns] == [
        "tenant_id",
        "provider_id",
        "subject",
    ]
    assert "tenant_id IS NULL" in str(
        global_index.dialect_options["postgresql"]["where"]
    )
    assert "tenant_id IS NOT NULL" in str(
        tenant_index.dialect_options["postgresql"]["where"]
    )


async def _seed_same_subject_links(ctx) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    provider_id = uuid.uuid4()
    account_a_id = uuid.uuid4()
    account_b_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:10]
    engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.oauth_providers "
                    "(id, slug, display_name, provider_type, client_id, "
                    " client_secret_encrypted, scopes, default_role, enabled, "
                    " created_at, updated_at) "
                    "VALUES (:id, :slug, 'Tenant OAuth probe', 'oidc', "
                    " 'tenant-probe-client', 'encrypted-test-value', "
                    " 'openid profile email', 'viewer', true, now(), now())"
                ),
                {"id": provider_id, "slug": f"tenant-oauth-{suffix}"},
            )
            # Omit tenant_id deliberately: without an active tenant GUC the
            # stamp trigger is inert, then the ordered parent validator derives
            # the durable tenant from each linked user.
            for account_id, user_id in (
                (account_a_id, ctx.user_a_id),
                (account_b_id, ctx.user_b_id),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.oauth_accounts "
                        "(id, provider_id, user_id, subject, created_at) "
                        "VALUES (:id, :provider_id, :user_id, "
                        " 'same-idp-subject', now())"
                    ),
                    {
                        "id": account_id,
                        "provider_id": provider_id,
                        "user_id": user_id,
                    },
                )
    finally:
        await engine.dispose()
    return provider_id, account_a_id, account_b_id


async def _delete_provider(db_url: str, provider_id: uuid.UUID) -> None:
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.oauth_providers WHERE id = :id"),
                {"id": provider_id},
            )
    finally:
        await engine.dispose()


@pytest.mark.rls
async def test_same_idp_subject_resolves_to_each_tenants_own_user(
    multi_tenant_rls,
):
    ctx = multi_tenant_rls
    provider_id, account_a_id, account_b_id = await _seed_same_subject_links(ctx)
    try:
        async with ctx.tenant_session(ctx.tenant_a) as session:
            account_a = (
                await session.execute(
                    select(
                        OAuthAccount.id,
                        OAuthAccount.user_id,
                        OAuthAccount.tenant_id,
                    ).where(
                        OAuthAccount.provider_id == provider_id,
                        OAuthAccount.subject == "same-idp-subject",
                    )
                )
            ).one()
            assert account_a.id == account_a_id
            assert account_a.user_id == uuid.UUID(ctx.user_a_id)
            assert account_a.tenant_id == uuid.UUID(ctx.tenant_a)
            assert (
                await session.scalar(
                    select(sa.func.count())
                    .select_from(OAuthAccount)
                    .where(OAuthAccount.id == account_b_id)
                )
                == 0
            )

        async with ctx.tenant_session(ctx.tenant_b) as session:
            account_b = (
                await session.execute(
                    select(
                        OAuthAccount.id,
                        OAuthAccount.user_id,
                        OAuthAccount.tenant_id,
                    ).where(
                        OAuthAccount.provider_id == provider_id,
                        OAuthAccount.subject == "same-idp-subject",
                    )
                )
            ).one()
            assert account_b.id == account_b_id
            assert account_b.user_id == uuid.UUID(ctx.user_b_id)
            assert account_b.tenant_id == uuid.UUID(ctx.tenant_b)
            assert (
                await session.scalar(
                    select(sa.func.count())
                    .select_from(OAuthAccount)
                    .where(OAuthAccount.id == account_a_id)
                )
                == 0
            )
    finally:
        await _delete_provider(ctx.db_url, provider_id)


@pytest.mark.rls
async def test_active_tenant_stamp_cannot_link_a_global_user(multi_tenant_rls):
    """The post-stamp parent validator rejects NULL-parent tenant drift."""
    ctx = multi_tenant_rls
    provider_id = uuid.uuid4()
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:10]
    engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.users "
                    "(id, username, email, status, is_active, token_version, "
                    " auth_provider, tenant_id, created_at, updated_at) "
                    "VALUES (:id, :username, :email, 'active', true, 1, "
                    "        'local', NULL, now(), now())"
                ),
                {
                    "id": user_id,
                    "username": f"oauth-global-{suffix}",
                    "email": f"oauth-global-{suffix}@rls.test",
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.oauth_providers "
                    "(id, slug, display_name, provider_type, client_id, "
                    " client_secret_encrypted, scopes, default_role, enabled, "
                    " created_at, updated_at) "
                    "VALUES (:id, :slug, 'Stamp order probe', 'oidc', "
                    " 'stamp-order-client', 'encrypted-test-value', "
                    " 'openid profile email', 'viewer', true, now(), now())"
                ),
                {"id": provider_id, "slug": f"stamp-order-{suffix}"},
            )

        with pytest.raises(
            sa.exc.DBAPIError,
            match="OAuth account tenant does not match linked user tenant",
        ):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "SELECT set_config('app.current_tenant', :tenant_id, true)"
                    ),
                    {"tenant_id": ctx.tenant_a},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.oauth_accounts "
                        "(id, provider_id, user_id, subject, created_at) "
                        "VALUES (:id, :provider_id, :user_id, "
                        " 'global-parent-subject', now())"
                    ),
                    {
                        "id": account_id,
                        "provider_id": provider_id,
                        "user_id": user_id,
                    },
                )
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.oauth_providers WHERE id = :id"),
                {"id": provider_id},
            )
            await conn.execute(
                sa.text("DELETE FROM catalog.users WHERE id = :id"),
                {"id": user_id},
            )
        await engine.dispose()
