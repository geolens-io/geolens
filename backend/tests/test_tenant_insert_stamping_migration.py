"""Migration and live PostgreSQL guards for tenant insert stamping.

The migration is raw SQL, so Alembic autogenerate cannot detect function or
trigger drift.  These tests pin the migration source, compare the live catalog
to a checked-in snapshot, and exercise the trigger function against PostgreSQL.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.rls import RLS_TABLES

pytestmark = pytest.mark.xdist_group("tenancy_global_state")

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_MIGRATION_PATH = (
    _BACKEND_DIR / "alembic" / "versions" / "0018_tenant_insert_stamping.py"
)
_SNAPSHOT_PATH = Path(__file__).parent / "tenant_insert_stamping_snapshot.json"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0018_tenant_insert_stamping",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_snapshot() -> dict:
    return json.loads(_SNAPSHOT_PATH.read_text())


def _captured_sql(mock_execute) -> list[str]:
    return [call.args[0].strip() for call in mock_execute.call_args_list]


def test_migration_source_pins_revision_and_exact_rls_table_boundary():
    migration = _load_migration()
    snapshot = _load_snapshot()

    assert migration.revision == "0018_tenant_insert_stamping"
    assert migration.down_revision == "0017_add_fk_support_indexes"
    # 0018 carries forward the original six-table boundary. Later linear
    # migrations may extend the current runtime boundary and snapshot.
    assert migration._TABLES == RLS_TABLES[:6]
    assert {item["table"] for item in snapshot["triggers"]} == set(RLS_TABLES)
    assert len(snapshot["triggers"]) == len(RLS_TABLES)


def test_upgrade_sql_is_mode_independent_and_fail_closed():
    migration = _load_migration()

    with patch.object(migration.op, "execute") as execute:
        migration.upgrade()

    statements = _captured_sql(execute)
    assert len(statements) == 8
    assert statements[0] == "SET LOCAL lock_timeout = '5s'"
    function_sql = statements[1]
    assert "SECURITY INVOKER" in function_sql
    assert "SECURITY DEFINER" not in function_sql
    assert "current_setting('app.current_tenant', true)" in function_sql
    assert "IF session_tenant_text IS NULL" in function_sql
    assert "session_tenant_text::uuid" in function_sql
    assert "USING ERRCODE = '42501'" in function_sql
    assert "NEW.tenant_id := session_tenant" in function_sql

    trigger_sql = statements[2:]
    assert trigger_sql == [
        "CREATE TRIGGER trg_stamp_current_tenant_on_insert "
        f"BEFORE INSERT ON catalog.{table} FOR EACH ROW EXECUTE FUNCTION "
        "catalog.stamp_current_tenant_on_insert()"
        for table in migration._TABLES
    ]

    source = _MIGRATION_PATH.read_text()
    assert "GEOLENS_TENANCY_MODE" not in source
    assert "app.core" not in source


def test_downgrade_sql_removes_exact_boundary_in_inverse_order():
    migration = _load_migration()

    with patch.object(migration.op, "execute") as execute:
        migration.downgrade()

    statements = _captured_sql(execute)
    assert statements[0] == "SET LOCAL lock_timeout = '5s'"
    assert statements[1:-1] == [
        f"DROP TRIGGER IF EXISTS trg_stamp_current_tenant_on_insert ON catalog.{table}"
        for table in reversed(migration._TABLES)
    ]
    assert statements[-1] == (
        "DROP FUNCTION IF EXISTS catalog.stamp_current_tenant_on_insert()"
    )


async def _reflect_live_boundary(db_url: str) -> tuple[dict, list[dict]]:
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            function_row = (
                (
                    await conn.execute(
                        sa.text(
                            """
                            SELECT
                                namespace.nspname AS schema,
                                procedure.proname AS name,
                                pg_get_function_identity_arguments(procedure.oid)
                                    AS arguments,
                                pg_get_function_result(procedure.oid) AS result,
                                language.lanname AS language,
                                procedure.prosecdef AS security_definer,
                                procedure.provolatile::text AS volatility,
                                procedure.proconfig AS config,
                                procedure.prosrc AS body
                            FROM pg_proc AS procedure
                            JOIN pg_namespace AS namespace
                              ON namespace.oid = procedure.pronamespace
                            JOIN pg_language AS language
                              ON language.oid = procedure.prolang
                            WHERE namespace.nspname = 'catalog'
                              AND procedure.proname =
                                  'stamp_current_tenant_on_insert'
                              AND procedure.pronargs = 0
                            """
                        )
                    )
                )
                .mappings()
                .one()
            )
            trigger_rows = (
                (
                    await conn.execute(
                        sa.text(
                            """
                            SELECT
                                table_namespace.nspname AS schema,
                                relation.relname AS table,
                                trigger.tgname AS name,
                                trigger.tgtype::integer AS type_mask,
                                trigger.tgenabled::text AS enabled,
                                function_namespace.nspname AS function_schema,
                                procedure.proname AS function_name
                            FROM pg_trigger AS trigger
                            JOIN pg_class AS relation
                              ON relation.oid = trigger.tgrelid
                            JOIN pg_namespace AS table_namespace
                              ON table_namespace.oid = relation.relnamespace
                            JOIN pg_proc AS procedure
                              ON procedure.oid = trigger.tgfoid
                            JOIN pg_namespace AS function_namespace
                              ON function_namespace.oid = procedure.pronamespace
                            WHERE NOT trigger.tgisinternal
                              AND function_namespace.nspname = 'catalog'
                              AND procedure.proname =
                                  'stamp_current_tenant_on_insert'
                            ORDER BY table_namespace.nspname, relation.relname
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
            return dict(function_row), [dict(row) for row in trigger_rows]
    finally:
        await engine.dispose()


async def test_live_postgres_boundary_matches_security_snapshot(test_db_session):
    from app.core.config import settings

    snapshot = _load_snapshot()
    function, triggers = await _reflect_live_boundary(settings.test_database_url)
    expected_function = snapshot["function"]

    for field in (
        "schema",
        "name",
        "arguments",
        "result",
        "language",
        "security_definer",
        "volatility",
        "config",
    ):
        assert function[field] == expected_function[field], (
            f"tenant-stamping function drifted at {field}: "
            f"live={function[field]!r}, expected={expected_function[field]!r}"
        )
    for fragment in expected_function["body_contains"]:
        assert fragment in function["body"], (
            f"tenant-stamping function body lost required fragment {fragment!r}"
        )
    assert " ".join(function["body"].split()) == expected_function["body_normalized"], (
        "tenant-stamping function body drifted from the reviewed snapshot"
    )

    assert triggers == snapshot["triggers"]


async def test_live_postgres_function_stamps_and_rejects_tenant_ids(
    test_db_session,
):
    """Exercise absent, matching, mismatching, and invalid GUC behavior live."""
    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    active_tenant = uuid.uuid4()
    other_tenant = uuid.uuid4()
    try:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text(
                    "CREATE TEMP TABLE tenant_stamp_probe ("
                    "id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                    "tenant_id uuid, payload text NOT NULL)"
                )
            )
            await conn.execute(
                sa.text(
                    "CREATE TRIGGER trg_stamp_current_tenant_on_insert "
                    "BEFORE INSERT ON tenant_stamp_probe FOR EACH ROW "
                    "EXECUTE FUNCTION catalog.stamp_current_tenant_on_insert()"
                )
            )

            # A missing GUC is the dormant single-tenant/migrator path.
            assert (
                await conn.scalar(
                    sa.text("SELECT current_setting('app.current_tenant', true)")
                )
                is None
            )
            absent_null = await conn.scalar(
                sa.text(
                    "INSERT INTO tenant_stamp_probe (payload) "
                    "VALUES ('absent-null') RETURNING tenant_id"
                )
            )
            absent_explicit = await conn.scalar(
                sa.text(
                    "INSERT INTO tenant_stamp_probe (tenant_id, payload) "
                    "VALUES (:tenant_id, 'absent-explicit') RETURNING tenant_id"
                ),
                {"tenant_id": other_tenant},
            )
            assert absent_null is None
            assert absent_explicit == other_tenant

            # PostgreSQL exposes a transaction-local custom GUC as an empty
            # string after reset; that is also an absent/dormant value.
            await conn.execute(
                sa.text("SELECT set_config('app.current_tenant', '', false)")
            )
            empty_guc = await conn.scalar(
                sa.text(
                    "INSERT INTO tenant_stamp_probe (tenant_id, payload) "
                    "VALUES (:tenant_id, 'empty-guc') RETURNING tenant_id"
                ),
                {"tenant_id": other_tenant},
            )
            assert empty_guc == other_tenant

            await conn.execute(
                sa.text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(active_tenant)},
            )

            stamped = await conn.scalar(
                sa.text(
                    "INSERT INTO tenant_stamp_probe (payload) "
                    "VALUES ('stamped') RETURNING tenant_id"
                )
            )
            matching = await conn.scalar(
                sa.text(
                    "INSERT INTO tenant_stamp_probe (tenant_id, payload) "
                    "VALUES (:tenant_id, 'matching') RETURNING tenant_id"
                ),
                {"tenant_id": active_tenant},
            )
            assert stamped == active_tenant
            assert matching == active_tenant

            with pytest.raises(sa.exc.DBAPIError) as mismatch_error:
                await conn.execute(
                    sa.text(
                        "INSERT INTO tenant_stamp_probe (tenant_id, payload) "
                        "VALUES (:tenant_id, 'mismatch')"
                    ),
                    {"tenant_id": other_tenant},
                )
            assert mismatch_error.value.orig.sqlstate == "42501"
            assert "tenant_id does not match the active tenant" in str(
                mismatch_error.value.orig
            )

            await conn.execute(
                sa.text("SELECT set_config('app.current_tenant', 'not-a-uuid', false)")
            )
            with pytest.raises(sa.exc.DBAPIError) as invalid_guc_error:
                await conn.execute(
                    sa.text(
                        "INSERT INTO tenant_stamp_probe (payload) "
                        "VALUES ('invalid-guc')"
                    )
                )
            assert invalid_guc_error.value.orig.sqlstate == "22P02"
    finally:
        await engine.dispose()
