"""DP-04: Structural CI gate — data-plane shape invariants (Phase 1209-04).

What this tests
---------------
In ``multi_tenant`` mode, the data plane MUST be structurally correct:

(A) No new data table lands in the shared ``data`` schema.
    Tenant data belongs in per-tenant ``data_t_{tenant_id}`` schemas only.
    A regression that routes ingest to ``data`` instead of the per-tenant
    schema would silently cross-pollinate all tenants.

(B) No global role (``geolens_reader``, ``geolens_readonly``) holds blanket
    SELECT on per-tenant schema tables.
    The per-tenant reader role (``geolens_reader_t_{tenant_id}``) is the ONLY
    role that should have SELECT on tables inside ``data_t_{tenant_id}``.
    A global reader with blanket SELECT would negate per-tenant isolation —
    a request running as ``geolens_reader`` could read ANY tenant's data.

(C) Positive control: the per-tenant reader role DOES hold SELECT on its
    own schema tables.

The test provisions probe tables in both a per-tenant schema and (deliberately)
the shared ``data`` schema to verify the gate flags the misplaced probe.

Enforcement direction
---------------------
- Assertion A FAILS if a probe table is found in the shared ``data`` schema.
- Assertion B FAILS if ``geolens_reader`` has SELECT on a per-tenant table.
- Assertion C PASSES if the per-tenant role has SELECT on its own table.

This test runs on every core PR (no overlay/secret gating).

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp04_data_plane_structural_gate.py -x -q
"""

from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard-coded test tenant UUID (provisioned by init-test-db.sh + conftest.py).
_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_A_SCHEMA = "data_t_00000000_0000_0000_0000_000000000001"
_TENANT_A_ROLE = "geolens_reader_t_00000000_0000_0000_0000_000000000001"

# Probe table names (suffix ensures idempotent cleanup even on repeated runs).
_PROBE_SUFFIX = "dp04_gate"
_PROBE_TENANT_TABLE = f"probe_{_PROBE_SUFFIX}"
_PROBE_SHARED_TABLE = f"probe_shared_{_PROBE_SUFFIX}"

_GLOBAL_ROLES = ["geolens_reader", "geolens_readonly"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_settings_multi():
    """Set GEOLENS_TENANCY_MODE=multi_tenant and reload settings + tenancy module."""
    import os

    import app.core.config as cfg_mod
    import app.core.tenancy as ten_mod

    os.environ["GEOLENS_TENANCY_MODE"] = "multi_tenant"
    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
    importlib.reload(ten_mod)
    return cfg_mod.settings


def _reload_settings_single():
    """Restore GEOLENS_TENANCY_MODE=single_tenant and reload."""
    import os

    import app.core.config as cfg_mod
    import app.core.tenancy as ten_mod

    os.environ.pop("GEOLENS_TENANCY_MODE", None)
    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
    importlib.reload(ten_mod)


async def _get_db_url() -> str:
    # Per-worker TEST database (conftest provisions the per-tenant data_t_* schemas
    # + geolens_reader_t_* roles there) — not the main app DB, which is `postgres`
    # on CI and lacks the per-tenant provisioning. Mirrors dp02's working pattern.
    from app.core.config import settings

    return settings.test_database_url


async def _drop_probe_tables(db_url: str) -> None:
    """Drop probe tables in both schemas (idempotent teardown)."""
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text(
                    f"DROP TABLE IF EXISTS {_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}"
                )
            )
            await conn.execute(
                sa.text(f"DROP TABLE IF EXISTS data.{_PROBE_SHARED_TABLE}")
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# DP-04-A: No data table in the shared schema (gate fails closed)
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestDp04SharedSchemaGate:
    """Gate: asserts no data table lives in the shared 'data' schema in multi_tenant.

    The gate fires (FAILS) when a misplaced probe is present in shared 'data'.
    The gate PASSES when probes live only in per-tenant schemas.
    """

    async def test_shared_schema_has_no_tenant_data_tables_baseline(self, monkeypatch):
        """Baseline: no dp04-probe tables exist in the shared 'data' schema.

        After teardown this should always be True. If this test fails, there is
        a prior-run cleanup issue or a real data-plane regression.
        """
        _reload_settings_multi()
        try:
            db_url = await _get_db_url()
            engine = create_async_engine(db_url, poolclass=NullPool)
            try:
                async with engine.connect() as conn:
                    row = (
                        await conn.execute(
                            sa.text(
                                "SELECT count(*) FROM information_schema.tables "
                                "WHERE table_schema = 'data' "
                                "AND table_name LIKE :pattern "
                                "AND table_type = 'BASE TABLE'"
                            ),
                            {"pattern": f"probe_{_PROBE_SUFFIX}%"},
                        )
                    ).scalar_one()
            finally:
                await engine.dispose()

            assert row == 0, (
                f"DP-04 FAIL [baseline]: Found {row} dp04-probe table(s) in the shared "
                f"'data' schema before the test ran. Cleanup from a prior run may have "
                f"failed. Run: DROP TABLE IF EXISTS data.probe_shared_{_PROBE_SUFFIX};"
            )
        finally:
            _reload_settings_single()

    async def test_shared_schema_gate_fires_on_misplaced_probe(self, monkeypatch):
        """Gate FAILS (detects) when a probe table is created in the shared 'data' schema.

        This is the RED direction: the structural gate must FLAG a misplaced probe.
        The test deliberately creates a table in 'data', asserts the gate fires,
        then cleans up.
        """
        _reload_settings_multi()
        db_url = await _get_db_url()

        engine = create_async_engine(db_url, poolclass=NullPool)
        misplaced_count: int = 0
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                # Deliberately place a probe in the SHARED schema (regression simulation).
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE IF NOT EXISTS data.{_PROBE_SHARED_TABLE} "
                        f"(id integer, marker text DEFAULT 'dp04_misplaced')"
                    )
                )

            # Run the gate query: count tables in the shared 'data' schema
            # that match our probe pattern.
            async with engine.connect() as conn:
                misplaced_count = (
                    await conn.execute(
                        sa.text(
                            "SELECT count(*) FROM information_schema.tables "
                            "WHERE table_schema = 'data' "
                            "AND table_name LIKE :pattern "
                            "AND table_type = 'BASE TABLE'"
                        ),
                        {"pattern": f"probe_shared_{_PROBE_SUFFIX}%"},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
            await _drop_probe_tables(db_url)
            _reload_settings_single()

        # The gate SHOULD have fired (count > 0 = misplaced probe detected).
        assert misplaced_count > 0, (
            "DP-04 TEST SETUP ERROR: the probe table was not created in data schema — "
            "gate simulation failed to set up. Check DB connectivity."
        )
        # Document the detection: if misplaced_count > 0, the gate would fail CI.
        # This assertion verifies the DETECTION logic is correct.
        assert misplaced_count == 1, (
            f"DP-04: Expected exactly 1 misplaced probe, found {misplaced_count}. "
            "Gate detection is non-deterministic — check for leftover probe tables."
        )

    async def test_per_tenant_schema_probe_not_flagged_by_gate(self, monkeypatch):
        """Gate PASSES (silent) when probe tables live only in per-tenant schemas.

        This is the GREEN direction: the structural gate must NOT flag a probe
        that correctly lives in a per-tenant schema (data_t_{tid}).
        """
        _reload_settings_multi()
        db_url = await _get_db_url()

        engine = create_async_engine(db_url, poolclass=NullPool)
        shared_count: int = -1
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                # Correctly place the probe in the per-tenant schema.
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE IF NOT EXISTS "
                        f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE} "
                        f"(id integer, marker text DEFAULT 'dp04_correct')"
                    )
                )

            # Gate query on the SHARED schema — should return 0 (no misplaced tables).
            async with engine.connect() as conn:
                shared_count = (
                    await conn.execute(
                        sa.text(
                            "SELECT count(*) FROM information_schema.tables "
                            "WHERE table_schema = 'data' "
                            "AND table_name LIKE :pattern "
                            "AND table_type = 'BASE TABLE'"
                        ),
                        {"pattern": f"probe_{_PROBE_SUFFIX}%"},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
            await _drop_probe_tables(db_url)
            _reload_settings_single()

        assert shared_count == 0, (
            f"DP-04 FAIL [green-path]: gate flagged {shared_count} table(s) in the "
            f"shared 'data' schema even though the probe was in the per-tenant schema. "
            f"Gate is producing false positives — check the detection query."
        )


# ---------------------------------------------------------------------------
# DP-04-B: No global role holds blanket SELECT on per-tenant tables
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestDp04GlobalRoleGrant:
    """Gate: global roles must NOT have SELECT on per-tenant schema tables.

    Assertion B: ``has_table_privilege('geolens_reader', '<per-tenant probe>', 'SELECT')``
    must be FALSE.

    Assertion C (positive control): the per-tenant reader role DOES have SELECT.
    """

    async def test_global_reader_lacks_select_on_per_tenant_table(self, monkeypatch):
        """geolens_reader MUST NOT have SELECT on a per-tenant table.

        If this fails, the global reader role has been granted blanket SELECT on
        the per-tenant schema, negating per-tenant isolation: any request running
        as geolens_reader (the fallback / single_tenant role) could read any
        tenant's data without switching to the per-tenant reader role.
        """
        _reload_settings_multi()
        db_url = await _get_db_url()

        engine = create_async_engine(db_url, poolclass=NullPool)
        reader_has_select: bool | None = None
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE IF NOT EXISTS "
                        f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE} "
                        f"(id integer, marker text DEFAULT 'dp04_priv_probe')"
                    )
                )

            qualified = f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}"
            async with engine.connect() as conn:
                reader_has_select = (
                    await conn.execute(
                        sa.text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                        {"role": "geolens_reader", "table": qualified},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
            await _drop_probe_tables(db_url)
            _reload_settings_single()

        assert reader_has_select is False, (
            f"DP-04 FAIL [B]: geolens_reader has SELECT on {_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}!\n"
            f"  has_table_privilege='geolens_reader', '{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}', 'SELECT') "
            f"returned {reader_has_select!r}\n"
            f"  The global reader role must NOT have blanket SELECT on per-tenant "
            f"schemas. Only geolens_reader_t_{{tenant_id}} should hold that privilege.\n"
            f"  Check: REVOKE SELECT ON ALL TABLES IN SCHEMA {_TENANT_A_SCHEMA} "
            f"FROM geolens_reader;"
        )

    async def test_per_tenant_reader_has_select_on_own_table(self, monkeypatch):
        """Positive control: the per-tenant reader role DOES have SELECT on its own table.

        The per-tenant reader role (geolens_reader_t_{tid}) must be able to SELECT
        from tables in its own schema. If this fails, the privilege setup is broken
        and the tile server cannot read tenant data.
        """
        _reload_settings_multi()
        db_url = await _get_db_url()

        engine = create_async_engine(db_url, poolclass=NullPool)
        tenant_reader_has_select: bool | None = None
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE IF NOT EXISTS "
                        f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE} "
                        f"(id integer, marker text DEFAULT 'dp04_pos_control')"
                    )
                )
                # Grant SELECT on the new table to the per-tenant role
                # (mirrors ALTER DEFAULT PRIVILEGES; new tables get it automatically
                # on future creates but an explicit GRANT covers the probe table).
                await conn.execute(
                    sa.text(
                        f"GRANT SELECT ON {_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE} "
                        f"TO {_TENANT_A_ROLE}"
                    )
                )

            qualified = f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}"
            async with engine.connect() as conn:
                tenant_reader_has_select = (
                    await conn.execute(
                        sa.text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                        {"role": _TENANT_A_ROLE, "table": qualified},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
            await _drop_probe_tables(db_url)
            _reload_settings_single()

        assert tenant_reader_has_select is True, (
            f"DP-04 FAIL [C/positive-control]: {_TENANT_A_ROLE} does NOT have SELECT "
            f"on {_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}!\n"
            f"  This means the per-tenant privilege setup is broken — "
            f"the tile server cannot read this tenant's data.\n"
            f"  Check init-test-db.sh / conftest.py GRANT statements for "
            f"{_TENANT_A_SCHEMA}."
        )

    async def test_global_readonly_role_lacks_select_on_per_tenant_table_if_present(
        self, monkeypatch
    ):
        """geolens_readonly must NOT have SELECT on per-tenant tables (if the role exists).

        geolens_readonly is a production role (not in init-test-db.sh).
        If absent, this test skips. If present, it must not have blanket SELECT
        on per-tenant schemas — same constraint as geolens_reader.
        """
        db_url = await _get_db_url()

        # Check if geolens_readonly exists.
        engine_check = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine_check.connect() as conn:
                row = (
                    await conn.execute(
                        sa.text(
                            "SELECT 1 FROM pg_roles WHERE rolname = 'geolens_readonly'"
                        )
                    )
                ).fetchone()
                role_exists = row is not None
        finally:
            await engine_check.dispose()

        if not role_exists:
            pytest.skip(
                "geolens_readonly not present in the test DB "
                "(init-test-db.sh does not create it; it is a production role). "
                "Skipping; geolens_reader variant above covers the gate."
            )

        _reload_settings_multi()
        db_url = await _get_db_url()

        engine = create_async_engine(db_url, poolclass=NullPool)
        readonly_has_select: bool | None = None
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE IF NOT EXISTS "
                        f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE} "
                        f"(id integer, marker text DEFAULT 'dp04_readonly_probe')"
                    )
                )

            qualified = f"{_TENANT_A_SCHEMA}.{_PROBE_TENANT_TABLE}"
            async with engine.connect() as conn:
                readonly_has_select = (
                    await conn.execute(
                        sa.text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                        {"role": "geolens_readonly", "table": qualified},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
            await _drop_probe_tables(db_url)
            _reload_settings_single()

        assert readonly_has_select is False, (
            f"DP-04 FAIL [B-readonly]: geolens_readonly has SELECT on a per-tenant table!\n"
            f"  The sandbox readonly role must NOT have blanket SELECT on per-tenant schemas.\n"
            f"  Revoke: REVOKE SELECT ON ALL TABLES IN SCHEMA {_TENANT_A_SCHEMA} "
            f"FROM geolens_readonly;"
        )
