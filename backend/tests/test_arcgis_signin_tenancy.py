"""fix(#1758 codex r4): the ArcGIS sign-in lockout budget crosses tenants.

Esri locks an ArcGIS account after five failed sign-ins in fifteen minutes and
counts them per ACCOUNT. GeoLens allows three, so it can never be what locks
one. That guarantee only holds if the count is cluster-global, and the first
revision counted it from ``catalog.audit_logs``, which carries
``tenant_isolation_audit_logs``: in ``multi_tenant`` each tenant saw only its
own attempts, so two tenants could send six failures at one account between
them and lock it. The advisory lock did not close the gap either, because it
serializes rather than aggregates.

The fix is ``catalog.arcgis_signin_attempts``, a ledger deliberately outside
the RLS boundary. This module is the proof, and it is a separate file from
``test_arcgis_signin.py`` on purpose: joining ``_TENANCY_GLOBAL_STATE_MODULES``
pins every test in the file to the single tenancy xdist worker, and only these
three need that.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.rls import RLS_TABLES
from app.modules.catalog.sources.arcgis_signin import signin_account_key
from app.modules.catalog.sources.models import ArcGISSignInAttempt
from app.modules.catalog.sources.signin_guard import (
    _ARCGIS_SIGNIN_ATTEMPT_LIMIT,
    _signin_budgets_spent,
)

pytestmark = pytest.mark.anyio

_LEDGER = "arcgis_signin_attempts"


def test_the_ledger_is_deliberately_outside_the_rls_boundary():
    """A structural pin, so a later tenancy sweep has to argue with a test.

    Adding this table to ``RLS_TABLES`` would silently reintroduce exactly the
    defect it exists to fix, and the failure would be invisible until a second
    tenant attacked the same ArcGIS account.
    """
    assert _LEDGER not in RLS_TABLES
    assert "tenant_id" not in ArcGISSignInAttempt.__table__.c
    # And it carries nothing that could identify a tenant, a caller or an
    # account by name.
    assert set(ArcGISSignInAttempt.__table__.c.keys()) == {
        "id",
        "account_key",
        "attempted_at",
    }


async def test_the_live_ledger_has_no_row_level_security(test_db_session):
    row = (
        await test_db_session.execute(
            sa.text(
                """
                SELECT
                    relation.relrowsecurity,
                    relation.relforcerowsecurity,
                    (
                        SELECT count(*)
                        FROM pg_policies AS policy
                        WHERE policy.schemaname = 'catalog'
                          AND policy.tablename = relation.relname
                    ) AS policy_count
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'catalog'
                  AND relation.relname = :table
                """
            ),
            {"table": _LEDGER},
        )
    ).one()

    assert row.relrowsecurity is False
    assert row.relforcerowsecurity is False
    assert row.policy_count == 0


@pytest.mark.rls
async def test_two_tenants_share_one_budget_for_one_arcgis_account(multi_tenant_rls):
    """The behavioural proof, with RLS actually enforced.

    Tenant A spends the whole budget. Tenant B then asks the same question the
    endpoint asks and must be told the budget is spent, even though tenant B
    cannot see a single one of tenant A's audit rows.
    """
    ctx = multi_tenant_rls
    account_key = signin_account_key("portal.example.test", f"user-{uuid.uuid4().hex}")
    host = "portal.example.test"

    engine = create_async_engine(
        ctx.db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            # geolens_reader is the role the harness switches to inside a
            # tenant session; the harness grants SELECT on the RLS tables only,
            # so the ledger needs its own grant for this test to read it.
            await conn.execute(
                sa.text(f"GRANT SELECT ON catalog.{_LEDGER} TO geolens_reader")
            )
            # Tenant A spends the budget: one audit row and one ledger row per
            # attempt, exactly as the endpoint writes them.
            for _ in range(_ARCGIS_SIGNIN_ATTEMPT_LIMIT):
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.audit_logs "
                        "(id, user_id, tenant_id, action, resource_type, "
                        " details, created_at) "
                        "VALUES (:id, :user_id, :tenant_id, 'arcgis_signin', "
                        " 'service_url', CAST(:details AS jsonb), now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "user_id": ctx.user_a_id,
                        "tenant_id": ctx.tenant_a,
                        "details": json.dumps(
                            {
                                "token_service_host": host,
                                "result": "invalid_credentials",
                                "account_key": account_key,
                            }
                        ),
                    },
                )
                await conn.execute(
                    sa.text(
                        f"INSERT INTO catalog.{_LEDGER} "
                        "(id, account_key, attempted_at) "
                        "VALUES (:id, :account_key, now())"
                    ),
                    {"id": uuid.uuid4(), "account_key": account_key},
                )

        # Tenant B, under the tenant GUC and the non-privileged role, so RLS
        # is doing real work.
        async with ctx.tenant_session(ctx.tenant_b) as session:
            visible_audit_rows = await session.scalar(
                sa.text(
                    "SELECT count(*) FROM catalog.audit_logs "
                    "WHERE action = 'arcgis_signin'"
                )
            )
            # The positive control: without this, a passing assertion below
            # could just mean RLS was never enforced.
            assert visible_audit_rows == 0

            spent = await _signin_budgets_spent(
                session, ctx.user_b_id, host, account_key
            )

        assert spent is True
    finally:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text(f"DELETE FROM catalog.{_LEDGER} WHERE account_key = :key"),
                {"key": account_key},
            )
            await conn.execute(
                sa.text(
                    "DELETE FROM catalog.audit_logs "
                    "WHERE action = 'arcgis_signin' "
                    "  AND details ->> 'account_key' = :key"
                ),
                {"key": account_key},
            )
            await conn.execute(
                sa.text(f"REVOKE SELECT ON catalog.{_LEDGER} FROM geolens_reader")
            )
        await engine.dispose()
