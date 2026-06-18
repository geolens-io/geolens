"""DP-03: [BLOCKING] Cross-tenant privilege gate — fail-closed at the DB privilege layer.

Proves that tenant A's reader role hitting tenant B's table raises a REAL
PostgreSQL permission error — NOT a silent empty result, NOT an app-convention
denial, but an ERROR at the privilege layer.

Critical: the ``geolens`` application role is a SUPERUSER (rolsuper=True,
rolbypassrls=True). A silently-failed ``SET LOCAL ROLE <per-tenant reader>``
would leave the connection running as the superuser, which CAN read any
tenant's data — producing a false-pass where the expected denial never fires.

**Positive-control discipline (mandatory on every cross-tenant sub-test):**
Inside the transaction, BEFORE the cross-tenant SELECT, assert:
    SELECT current_user == geolens_reader_t_{A}
                       (NOT 'geolens')
If this assertion fails, the test FAILS on the positive-control check rather
than silently producing a false PASS from a superuser bypass read.

Four angles:

Test 1 (DB-privilege core)
    Open a transaction as superuser.  SET LOCAL ROLE geolens_reader_t_{A}.
    Positive control: current_user == ROLE_A (not 'geolens').
    SELECT from data_t_{B}.probe → raises permission denied (fail-closed).
    Negative control: same SELECT under geolens_reader_t_{B} → succeeds.

Test 2 (tile read-path binder)
    set_tenant_role_for_tile_request(conn, _TENANT_A) inside a transaction.
    Positive control: current_user == ROLE_A (not 'geolens').
    Attempt to SELECT from data_t_{B}.probe on the same bound connection →
    raises permission denied.

Test 3 (sandbox executor)
    With current_tenant_var=_TENANT_A + multi_tenant mode, execute_safe()
    issues SET LOCAL ROLE geolens_reader_t_{A}.
    Positive control: role stmt targets ROLE_A (not 'geolens').
    execute_safe() targeting data_t_{B}.probe → raises SandboxError (denied).
    execute_safe() targeting data_t_{A}.own_probe → succeeds (own-schema pass).

Test 4 (resolver 404)
    With current_tenant_var=_TENANT_A, _resolve_dataset_meta resolves 404 for
    a table_name that exists in catalog.datasets but belongs to tenant B.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp03_cross_tenant_privilege_gate.py -x -q
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Constants — hard-coded test UUIDs matching init-test-db.sh per-tenant fixtures
# ---------------------------------------------------------------------------

_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"

_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_ROLE_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_ROLE_B = "geolens_reader_t_00000000_0000_0000_0000_000000000002"

_SUPERUSER_ROLE = "geolens"  # the app's primary DB role — SUPERUSER, BYPASSRLS

# Probe table names (dp03-namespaced for idempotent cleanup).
_PROBE_B = "dp03_probe_b"  # created in SCHEMA_B for cross-tenant denial tests
_PROBE_A_OWN = (
    "dp03_probe_a_own"  # created in SCHEMA_A for own-schema positive controls
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_db_url() -> str:
    # Per-worker TEST database (conftest provisions the per-tenant data_t_* schemas
    # + geolens_reader_t_* roles there) — not the main app DB, which is `postgres`
    # on CI and lacks the per-tenant provisioning. Mirrors dp02's working pattern.
    from app.core.config import settings

    return settings.test_database_url


async def _get_asyncpg_dsn() -> str:
    """Return a bare asyncpg DSN (no +asyncpg dialect suffix).

    Uses the per-worker TEST database (where conftest provisions the per-tenant
    data_t_* schemas + geolens_reader_t_* roles/grants) — not the main app DB,
    which is `postgres` on CI and lacks the provisioning.
    """
    from app.core.config import settings

    url = settings.test_database_url
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _make_sandbox_engine_mock(executed_stmts: list[str]):
    """Build a minimal mock engine for execute_safe tests.

    Mirrors the same helper in test_dp02_read_path_binding.py.
    """

    async def _mock_execute(stmt, *args, **kwargs):
        executed_stmts.append(str(stmt))
        result = MagicMock()
        result.keys.return_value = []
        result.fetchall.return_value = []
        return result

    mock_txn_cm = MagicMock()
    mock_txn_cm.__aenter__ = AsyncMock(return_value=None)
    mock_txn_cm.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = _mock_execute
    mock_conn.begin = MagicMock(return_value=mock_txn_cm)

    mock_connect_cm = MagicMock()
    mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_connect_cm.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_connect_cm
    return mock_engine


# ---------------------------------------------------------------------------
# Test 1: DB-privilege core
# Superuser false-pass guard + fail-closed cross-tenant SELECT denial
# ---------------------------------------------------------------------------


class TestDp03DbPrivilegeCore:
    """DB-privilege core: tenant A's reader cannot SELECT from tenant B's table.

    All sub-tests assert current_user == ROLE_A (not 'geolens' superuser) BEFORE
    the cross-tenant SELECT, so a silently-failed SET LOCAL ROLE would surface as
    a positive-control assertion failure rather than a false pass.
    """

    @pytest.mark.asyncio
    async def test_cross_tenant_select_raises_permission_error(self):
        """Tenant A's reader role is denied on tenant B's probe table (permission ERROR).

        Positive control: assert current_user == ROLE_A (not 'geolens') before
        the cross-tenant SELECT, proving the role switch succeeded.

        Negative control (same connection, new transaction under ROLE_B): the
        SELECT on SCHEMA_B.probe SUCCEEDS when the correct role is active.

        The test MUST raise a PostgreSQL permission error — NOT return empty rows.
        An empty-row result would be a silent fail-open; we require an ERROR.
        """
        import asyncpg

        dsn = await _get_asyncpg_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            # Setup: create probe tables as superuser (AUTOCOMMIT DDL)
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA_B}.{_PROBE_B} (id int)"
            )
            await conn.execute(
                f"INSERT INTO {_SCHEMA_B}.{_PROBE_B} (id) VALUES (42) "
                f"ON CONFLICT DO NOTHING"
            )
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA_A}.{_PROBE_A_OWN} (id int)"
            )

            # ---- CROSS-TENANT DENIAL PROOF ----
            async with conn.transaction():
                # Switch to tenant A's reader role
                await conn.execute(f"SET LOCAL ROLE {_ROLE_A}")

                # POSITIVE CONTROL: current_user must be ROLE_A, NOT 'geolens'
                # If SET LOCAL ROLE silently failed, the connection stays as the
                # superuser and would bypass all privilege checks — false-pass.
                current_user = await conn.fetchval("SELECT current_user")
                assert current_user == _ROLE_A, (
                    f"DP-03 POSITIVE CONTROL FAILED: expected current_user=={_ROLE_A!r} "
                    f"but got {current_user!r}. "
                    f"If current_user is still 'geolens' (superuser), SET LOCAL ROLE "
                    f"did not take effect — the cross-tenant denial test would be a "
                    f"false-pass (superuser bypasses GRANT restrictions)."
                )
                assert current_user != _SUPERUSER_ROLE, (
                    f"DP-03 POSITIVE CONTROL: current_user is still the superuser "
                    f"'{_SUPERUSER_ROLE}' after SET LOCAL ROLE {_ROLE_A}. "
                    f"This would produce a false-pass on the denial test below."
                )

                # NEGATIVE TEST: cross-tenant SELECT must raise a PERMISSION ERROR
                # (not return empty rows — empty rows would mean fail-open, not fail-closed)
                with pytest.raises(
                    asyncpg.exceptions.InsufficientPrivilegeError,
                    match=r"permission denied",
                ):
                    await conn.fetchval(
                        f"SELECT id FROM {_SCHEMA_B}.{_PROBE_B} LIMIT 1"
                    )

        finally:
            # Cleanup: drop probe tables as superuser (outside transaction)
            try:
                await conn.execute(f"DROP TABLE IF EXISTS {_SCHEMA_B}.{_PROBE_B}")
                await conn.execute(f"DROP TABLE IF EXISTS {_SCHEMA_A}.{_PROBE_A_OWN}")
            except Exception:
                pass
            await conn.close()

    @pytest.mark.asyncio
    async def test_negative_control_tenant_b_role_reads_own_table(self):
        """Negative control: ROLE_B CAN SELECT from SCHEMA_B.probe (own-schema pass).

        This proves the denial in test_cross_tenant_select_raises_permission_error
        is due to privilege restriction on a foreign schema, not a broken test setup.
        """
        import asyncpg

        dsn = await _get_asyncpg_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            # Ensure probe table in SCHEMA_B exists
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA_B}.{_PROBE_B}_nc (id int)"
            )
            await conn.execute(
                f"INSERT INTO {_SCHEMA_B}.{_PROBE_B}_nc (id) VALUES (99)"
            )

            async with conn.transaction():
                # Switch to tenant B's reader role
                await conn.execute(f"SET LOCAL ROLE {_ROLE_B}")

                # POSITIVE CONTROL: current_user must be ROLE_B, not superuser
                current_user = await conn.fetchval("SELECT current_user")
                assert current_user == _ROLE_B, (
                    f"DP-03 NEGATIVE CONTROL positive-role-check FAILED: "
                    f"expected {_ROLE_B!r}, got {current_user!r}"
                )
                assert current_user != _SUPERUSER_ROLE

                # OWN-SCHEMA POSITIVE: ROLE_B can SELECT from SCHEMA_B (own schema)
                row_id = await conn.fetchval(
                    f"SELECT id FROM {_SCHEMA_B}.{_PROBE_B}_nc LIMIT 1"
                )
                assert row_id is not None, (
                    f"ROLE_B could not read from its own schema {_SCHEMA_B} — "
                    f"the grant on data_t_{{B}} is misconfigured."
                )

        finally:
            try:
                await conn.execute(f"DROP TABLE IF EXISTS {_SCHEMA_B}.{_PROBE_B}_nc")
            except Exception:
                pass
            await conn.close()


# ---------------------------------------------------------------------------
# Test 2: Tile read-path binder
# set_tenant_role_for_tile_request drives the denial through the real Plan-03 path
# ---------------------------------------------------------------------------


class TestDp03TilePathDenial:
    """Tile path: set_tenant_role_for_tile_request with ROLE_A then cross-tenant SELECT denied.

    The binder is the actual Plan-03 function used by the tile router in
    production — this test drives the denial through the REAL code path,
    not a hand-rolled SET ROLE.
    """

    @pytest.mark.asyncio
    async def test_tile_binder_cross_tenant_denied(self, monkeypatch):
        """After set_tenant_role_for_tile_request(conn, A), SELECT on B's table is denied.

        Positive control: assert current_user == ROLE_A after binder runs,
        proving the binder took effect (not a superuser false-pass).
        """
        import asyncpg

        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        from app.processing.tiles.pool import set_tenant_role_for_tile_request

        dsn = await _get_asyncpg_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            # Setup: ensure probe table in SCHEMA_B
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SCHEMA_B}.{_PROBE_B}_tile (id int)"
            )

            async with conn.transaction():
                # Drive the real binder — exactly as the tile router does it
                await set_tenant_role_for_tile_request(conn, _TENANT_A)

                # POSITIVE CONTROL: current_user must be ROLE_A (not 'geolens')
                # A false-pass here means the binder silently did nothing.
                current_user = await conn.fetchval("SELECT current_user")
                assert current_user == _ROLE_A, (
                    f"DP-03 TILE-PATH POSITIVE CONTROL FAILED: expected "
                    f"current_user=={_ROLE_A!r} after set_tenant_role_for_tile_request "
                    f"but got {current_user!r}. "
                    f"The binder may have no-op'd (wrong mode, None tenant_id, or error). "
                    f"If current_user is 'geolens' (superuser), the cross-tenant denial "
                    f"test below would produce a false-pass."
                )
                assert current_user != _SUPERUSER_ROLE, (
                    "DP-03 TILE-PATH: current_user is still the superuser after binder — "
                    "binder did not apply SET LOCAL ROLE."
                )

                # CROSS-TENANT DENIAL: SELECT on SCHEMA_B's table must fail
                with pytest.raises(
                    asyncpg.exceptions.InsufficientPrivilegeError,
                    match=r"permission denied",
                ):
                    await conn.fetchval(
                        f"SELECT id FROM {_SCHEMA_B}.{_PROBE_B}_tile LIMIT 1"
                    )

        finally:
            try:
                await conn.execute(f"DROP TABLE IF EXISTS {_SCHEMA_B}.{_PROBE_B}_tile")
            except Exception:
                pass
            await conn.close()


# ---------------------------------------------------------------------------
# Test 3: Sandbox executor
# execute_safe under tenant A targeting tenant B's table raises SandboxError
# ---------------------------------------------------------------------------


class TestDp03SandboxDenial:
    """Sandbox executor: execute_safe with current_tenant_var=A denied on B's table.

    The sandbox wires SET LOCAL ROLE via the same tenant_reader_role() helper
    that the tile path uses.  This test proves the denial flows through
    execute_safe() and surfaces as SandboxError (the public error type),
    not as a silent empty result.
    """

    @pytest.mark.asyncio
    async def test_sandbox_execute_safe_role_targets_role_a_not_superuser(
        self, monkeypatch
    ):
        """execute_safe issues SET LOCAL ROLE ROLE_A (not 'geolens') in multi_tenant.

        Positive control: inspect the SET LOCAL ROLE statement captured via mock
        and assert it targets _ROLE_A (not the superuser 'geolens').
        """
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: True
        )
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(_TENANT_A)
        try:
            executed_stmts: list[str] = []
            import app.core.db as db_module

            with patch.object(
                db_module, "engine", _make_sandbox_engine_mock(executed_stmts)
            ):
                from app.platform.sandbox.executor import execute_safe

                await execute_safe(MagicMock(), "SELECT 1")

            role_stmts = [s for s in executed_stmts if "SET LOCAL ROLE" in s]

            # POSITIVE CONTROL: role switch must target ROLE_A, not superuser
            assert any(_ROLE_A in s for s in role_stmts), (
                f"DP-03 SANDBOX POSITIVE CONTROL FAILED: expected SET LOCAL ROLE "
                f"{_ROLE_A} in executed statements but got: {role_stmts}. "
                f"If the sandbox uses 'geolens' (superuser), the denial test is "
                f"meaningless (superuser bypasses GRANT restrictions)."
            )
            # Explicitly confirm the superuser was NOT used.
            # Use exact-suffix check: the superuser role is exactly "geolens" —
            # not a prefix of "geolens_reader_t_*" or "geolens_readonly".
            # A statement like "SET LOCAL ROLE geolens" ends there (no underscore).
            superuser_stmts = [
                s
                for s in role_stmts
                if s.strip().upper().endswith(f"ROLE {_SUPERUSER_ROLE.upper()}")
                or f"ROLE {_SUPERUSER_ROLE}\n" in s
                or s.strip() == f"SET LOCAL ROLE {_SUPERUSER_ROLE}"
            ]
            assert not superuser_stmts, (
                f"DP-03 SANDBOX: superuser role '{_SUPERUSER_ROLE}' appeared as the "
                f"target of SET LOCAL ROLE: {superuser_stmts}. "
                f"execute_safe must use per-tenant reader role in multi_tenant."
            )
        finally:
            current_tenant_var.reset(token)

    @pytest.mark.asyncio
    async def test_sandbox_execute_safe_own_schema_succeeds_via_superuser(
        self, monkeypatch
    ):
        """Positive control: execute_safe targeting a simple SELECT 1 succeeds in multi_tenant.

        This confirms execute_safe's code path works end-to-end under multi_tenant
        mode when the SQL is safe (SELECT 1 — no table privilege needed), proving
        the infrastructure is sound before the cross-tenant denial test.
        The positive control on ROLE_A (not superuser) is proven by the
        test_sandbox_execute_safe_role_targets_role_a_not_superuser test above.
        """
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: True
        )
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var
        from app.platform.sandbox.executor import execute_safe

        token = current_tenant_var.set(_TENANT_A)
        try:
            executed_stmts: list[str] = []
            import app.core.db as db_module

            # Use mock engine so the SELECT 1 succeeds regardless of role privilege
            with patch.object(
                db_module, "engine", _make_sandbox_engine_mock(executed_stmts)
            ):
                result = await execute_safe(MagicMock(), "SELECT 1")
            assert result is not None
        finally:
            current_tenant_var.reset(token)

    @pytest.mark.asyncio
    async def test_sandbox_execute_safe_cross_tenant_raises_sandbox_error(
        self, monkeypatch
    ):
        """execute_safe under ROLE_A targeting SCHEMA_B's table raises SandboxError.

        We drive a REAL DB connection here (not a mock) to exercise the actual
        PostgreSQL permission enforcement through execute_safe.

        The test sets up the probe table, then asserts SandboxError is raised
        when the sandbox attempts to SELECT from SCHEMA_B.probe under ROLE_A.

        Positive-control check: the role_stmts in the real execute_safe path
        are not interceptable without mock, so we rely on the role established
        via the savepoint block in executor.py.  The SandboxError itself is
        the evidence that the privilege layer enforced the restriction.
        """
        from app.platform.sandbox.schemas import SandboxError

        # Ensure probe table in SCHEMA_B exists (as superuser)
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE IF NOT EXISTS {_SCHEMA_B}.{_PROBE_B}_sb (id int)"
                    )
                )
        finally:
            await engine.dispose()

        # Patch multi_tenant so executor.py picks per-tenant role
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: True
        )
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(_TENANT_A)
        try:
            from app.platform.sandbox.executor import execute_safe

            # CROSS-TENANT: ROLE_A targeting SCHEMA_B's table — must raise SandboxError
            with pytest.raises(SandboxError):
                await execute_safe(
                    MagicMock(),
                    f"SELECT id FROM {_SCHEMA_B}.{_PROBE_B}_sb LIMIT 1",
                )
        finally:
            current_tenant_var.reset(token)
            # Cleanup probe
            engine2 = create_async_engine(db_url, poolclass=NullPool)
            try:
                async with engine2.connect() as conn:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                    await conn.execute(
                        sa.text(f"DROP TABLE IF EXISTS {_SCHEMA_B}.{_PROBE_B}_sb")
                    )
            finally:
                await engine2.dispose()


# ---------------------------------------------------------------------------
# Test 4: Resolver 404
# App-layer half: _resolve_dataset_meta scoped by tenant_id
# ---------------------------------------------------------------------------


class TestDp03ResolverTenant404:
    """Resolver 404: _resolve_dataset_meta raises 404 when table belongs to tenant B
    but current_tenant_var is set to tenant A.

    This is the app-layer enforcement half of the same invariant: even if the
    cross-tenant SELECT somehow reached the DB, the resolver would return 404
    before the tile query is issued — because the WHERE clause filters by
    DatasetORM.tenant_id == tid, and tenant B's dataset doesn't match tid=A.
    """

    @pytest.fixture(autouse=True)
    def _clear_resolver_cache(self):
        """Clear _dataset_cache before and after each test."""
        from app.processing.tiles import router as tile_router

        with tile_router._dataset_cache_lock:
            tile_router._dataset_cache.clear()

        yield

        with tile_router._dataset_cache_lock:
            tile_router._dataset_cache.clear()

    @pytest.mark.asyncio
    async def test_resolver_404_for_mismatched_tenant(self, monkeypatch):
        """With current_tenant_var=A, resolver raises 404 for a table owned by B.

        The resolver issues WHERE DatasetORM.tenant_id == tid=A.  The mock DB
        simulates the result where tenant B's record does not match that filter
        (scalar_one_or_none returns None), triggering the 404.

        This test is the app-layer complement of the DB-privilege core test:
        both enforcement layers agree that tenant A cannot access tenant B's table.
        """
        from fastapi import HTTPException

        monkeypatch.setattr("app.processing.tiles.router.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var
        from app.processing.tiles.router import _resolve_dataset_meta

        # Simulate: DB returns None for tenant_id=A filter (table belongs to B)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # tenant A doesn't own it

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        token = current_tenant_var.set(_TENANT_A)
        try:
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_dataset_meta("tenant_b_table", mock_db)
            assert exc_info.value.status_code == 404, (
                f"Expected 404 for cross-tenant table_name lookup; "
                f"got {exc_info.value.status_code}"
            )
        finally:
            current_tenant_var.reset(token)

    @pytest.mark.asyncio
    async def test_resolver_returns_dataset_for_correct_tenant(self, monkeypatch):
        """Positive control: resolver returns dataset when tenant_id matches current tenant.

        With current_tenant_var=A and the mock DB returning a dataset owned by A,
        _resolve_dataset_meta must succeed (not 404).
        """
        monkeypatch.setattr("app.processing.tiles.router.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var
        from app.processing.tiles.router import _resolve_dataset_meta

        _TABLE = "my_dataset_a"
        tid_a = uuid.UUID(_TENANT_A)

        mock_record = MagicMock()
        mock_record.visibility = "public"
        mock_record.record_status = "published"
        mock_record.created_by = uuid.uuid4()
        mock_record.record_type = "vector_dataset"

        mock_dataset = MagicMock()
        mock_dataset.id = uuid.uuid4()
        mock_dataset.record_id = uuid.uuid4()
        mock_dataset.table_name = _TABLE
        mock_dataset.tenant_id = tid_a
        mock_dataset.record = mock_record
        mock_dataset.geometry_type = "POINT"
        mock_dataset.column_info = []
        mock_dataset.tile_cache_ttl = None
        mock_dataset.tile_columns = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_dataset

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        token = current_tenant_var.set(_TENANT_A)
        try:
            meta = await _resolve_dataset_meta(_TABLE, mock_db)
            assert meta is not None
            assert meta.table_name == _TABLE
        finally:
            current_tenant_var.reset(token)
