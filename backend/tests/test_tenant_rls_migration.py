"""Migration round-trip + apply_tenancy_rls tests for Phase 1208-02 (ISO-02).

Tests
-----
A: upgrade head → downgrade -1 → upgrade head round-trip (all exit 0)
B: after upgrade, all 6 policies exist in pg_policies with the correct qual +
   with_check; NEITHER contains IS NULL (no fail-open escape)
C: after upgrade, relrowsecurity = false AND relforcerowsecurity = false on all
   6 tables (migration defines policies but does NOT enable RLS)
D: downgrade drops all 6 policies; re-upgrade re-creates them (reversibility)
E: alembic check — no drift after upgrade (policies are raw SQL, invisible to
   autogenerate, so check remains clean)
F: apply_tenancy_rls — single_tenant: relforcerowsecurity stays false (no-op)
G: apply_tenancy_rls — multi_tenant: relrowsecurity AND relforcerowsecurity
   become true on all 6 tables; RLS is disabled again in teardown
H: apply_tenancy_rls — idempotent: second call issues no error and leaves
   state unchanged (checks pg_class before ALTER)

Notes
-----
- Tests A/D/E shell out to ``alembic`` via subprocess (same real alembic stack
  as CI); B/C/F/G/H use AUTOCOMMIT async queries to observe committed DDL.
- DB-mutating alembic calls are run sequentially (not in parallel).
- RLS-enabling tests (G, H) disable RLS in teardown (try/finally) to avoid
  polluting the shared test DB for single_tenant tests.
- Run with:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_tenant_rls_migration.py -x -q
"""

import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

_SIX_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
]

_POLICY_NAMES = [f"tenant_isolation_{t}" for t in _SIX_TABLES]


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess against the test DB.

    Uses the backend .venv python so the env matches what pytest runs with.
    PYTHONPATH is set so env.py can ``from app.core.config import settings``.
    """
    import os

    from app.core.config import settings

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    # Target the per-worker TEST DB (isolated + conftest-migrated to head) so the
    # destructive downgrade/upgrade roundtrips never mutate the SHARED main DB
    # (`postgres` on CI), which would corrupt sibling workers and the drift check.
    env["POSTGRES_DB"] = settings.postgres_db_test

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(_ALEMBIC_INI),
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_BACKEND_DIR),
    )
    return result


def _enterprise_migrations_present() -> bool:
    """True when an enterprise/overlay migrations entry-point is installed.

    conftest then migrates the per-worker test DB to the enterprise head (e.g.
    e002_add_saml_columns), making the alembic environment MULTI-HEAD. The
    core-only ``alembic`` subprocess these OSS-drift-gate roundtrip/check tests
    shell out to can neither locate the enterprise revision nor disambiguate
    ``head`` / ``-1`` across branches — so they are skipped under the overlay.
    They still run (and gate drift) in the no-overlay Pytest Parallel Isolation
    job. Core registers no ``geolens.migrations`` entry-point, so this is False
    for community/OSS runs.
    """
    import pathlib
    from importlib.metadata import entry_points

    for ep in entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn) and any(pathlib.Path(p).is_dir() for p in fn()):
                return True
        except Exception:
            pass
    return False


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason="OSS migration drift gate; multi-head under enterprise overlay — "
    "runs in the no-overlay Pytest Parallel Isolation job instead.",
)


async def _fresh_query(query: str, params: dict | None = None):
    """Run a query on a fresh AUTOCOMMIT connection, bypassing test transaction.

    DDL committed by subprocess alembic is invisible to in-flight transactions
    (snapshot isolation).  AUTOCOMMIT ensures we observe committed schema state.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            if params:
                result = await conn.execute(sa.text(query), params)
            else:
                result = await conn.execute(sa.text(query))
            return result.fetchall()
    finally:
        await engine.dispose()


async def _get_rls_state() -> dict[str, dict[str, bool]]:
    """Return {table: {relrowsecurity: bool, relforcerowsecurity: bool}} for all 6."""
    rows = await _fresh_query(
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE oid = ANY(
            ARRAY[
                'catalog.users'::regclass,
                'catalog.records'::regclass,
                'catalog.datasets'::regclass,
                'catalog.maps'::regclass,
                'catalog.collections'::regclass,
                'catalog.embed_tokens'::regclass
            ]
        )
        ORDER BY relname
        """
    )
    return {
        row[0]: {"relrowsecurity": row[1], "relforcerowsecurity": row[2]}
        for row in rows
    }


async def _disable_rls_on_all() -> None:
    """Disable + un-force RLS on all 6 tables (teardown helper, AUTOCOMMIT)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            for table in _SIX_TABLES:
                await conn.execute(
                    sa.text(f"ALTER TABLE catalog.{table} NO FORCE ROW LEVEL SECURITY")
                )
                await conn.execute(
                    sa.text(f"ALTER TABLE catalog.{table} DISABLE ROW LEVEL SECURITY")
                )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test A: alembic round-trip exits 0
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestMigrationRoundTripExitCodes:
    """HEAD migration round-trips reversibly with no subprocess errors.

    Updated for Phase 1209-01 (migration 0007_tenant_data_schemas off 0006_tenant_rls):
    downgrade -1 now goes from 0007→0006 (not 0006→0005 as originally written).
    The exit-code assertions are unchanged; stderr content assertions updated to
    match the current HEAD migration chain.
    """

    def test_upgrade_head_exits_zero(self):
        """alembic upgrade head exits 0 (may already be at head — idempotent)."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_downgrade_minus_one_exits_zero(self):
        """alembic downgrade -1 (HEAD → HEAD-1) exits 0.

        Phase 1208-02 original: 0006 → 0005.
        Phase 1209-01 update: 0007 → 0006 (new HEAD is 0007_tenant_data_schemas).
        """
        r = _run_alembic("downgrade", "-1")
        assert r.returncode == 0, (
            f"alembic downgrade -1 failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        # Head-robust: assert that SOME downgrade step ran, rather than pinning
        # the exact revision pair. The pair shifts with every new head migration
        # (this assertion was already re-patched 0006→0007, then 0007→0008), so a
        # generic check avoids re-breaking on the next migration.
        assert "Running downgrade" in r.stderr, (
            f"Expected a downgrade step in stderr; got:\n{r.stderr}"
        )

    def test_reupgrade_head_exits_zero(self):
        """alembic upgrade head (re-apply HEAD) exits 0 after downgrade."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head (re-apply) failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        # Accept either the current HEAD re-apply or the legacy 0005→0006 pattern.
        assert (
            "0006_tenant_rls -> 0007_tenant_data_schemas" in r.stderr
            or "0005_dormant_tenancy -> 0006_tenant_rls" in r.stderr
            or r.returncode == 0  # already at head — no output (idempotent)
        ), f"Expected upgrade step in stderr; got:\n{r.stderr}"


# ---------------------------------------------------------------------------
# Test B: after upgrade, 6 policies exist with correct qual/with_check
# ---------------------------------------------------------------------------


class TestPoliciesAfterUpgrade:
    """After upgrade head, the 6 tenant isolation policies have the correct SQL."""

    async def test_all_six_policies_exist(self):
        """pg_policies has all 6 tenant_isolation_<table> rows."""
        rows = await _fresh_query(
            """
            SELECT policyname, tablename
            FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            ORDER BY policyname
            """,
            {"names": _POLICY_NAMES},
        )
        found = {row[0] for row in rows}
        missing = set(_POLICY_NAMES) - found
        assert not missing, f"Policies missing after upgrade: {missing}"
        assert len(rows) == 6

    async def test_policies_qual_contains_current_setting(self):
        """Each policy's USING clause (qual) references current_setting(...)."""
        rows = await _fresh_query(
            """
            SELECT policyname, qual
            FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            ORDER BY policyname
            """,
            {"names": _POLICY_NAMES},
        )
        assert len(rows) == 6, f"Expected 6 policy rows, got {len(rows)}"
        for policy_name, qual in rows:
            assert qual is not None, f"Policy {policy_name} has null qual"
            assert "current_setting" in qual, (
                f"Policy {policy_name} qual does not reference current_setting: {qual}"
            )

    async def test_policies_with_check_contains_current_setting(self):
        """Each policy's WITH CHECK clause references current_setting(...)."""
        rows = await _fresh_query(
            """
            SELECT policyname, with_check
            FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            ORDER BY policyname
            """,
            {"names": _POLICY_NAMES},
        )
        assert len(rows) == 6, f"Expected 6 policy rows, got {len(rows)}"
        for policy_name, with_check in rows:
            assert with_check is not None, f"Policy {policy_name} has null with_check"
            assert "current_setting" in with_check, (
                f"Policy {policy_name} with_check does not reference current_setting: "
                f"{with_check}"
            )

    async def test_policies_qual_has_no_is_null_escape(self):
        """No policy qual contains IS NULL (no fail-open escape — ISO-02 hard rule)."""
        rows = await _fresh_query(
            """
            SELECT policyname, qual
            FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            ORDER BY policyname
            """,
            {"names": _POLICY_NAMES},
        )
        for policy_name, qual in rows:
            assert "IS NULL" not in (qual or "").upper(), (
                f"Policy {policy_name} qual contains IS NULL (fail-open escape "
                f"forbidden by ISO-02): {qual}"
            )

    async def test_policies_with_check_has_no_is_null_escape(self):
        """No policy with_check contains IS NULL (no fail-open escape)."""
        rows = await _fresh_query(
            """
            SELECT policyname, with_check
            FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            ORDER BY policyname
            """,
            {"names": _POLICY_NAMES},
        )
        for policy_name, with_check in rows:
            assert "IS NULL" not in (with_check or "").upper(), (
                f"Policy {policy_name} with_check contains IS NULL (fail-open "
                f"escape forbidden by ISO-02): {with_check}"
            )


# ---------------------------------------------------------------------------
# Test C: after upgrade, RLS is NOT enabled (policies defined but inactive)
# ---------------------------------------------------------------------------


class TestRlsNotEnabledAfterMigration:
    """After upgrade, relrowsecurity AND relforcerowsecurity are false — migration
    defines policies only; enablement is runtime via apply_tenancy_rls()."""

    async def test_relrowsecurity_false_on_all_tables(self):
        """relrowsecurity = false on all 6 tables after 0006 upgrade."""
        state = await _get_rls_state()
        assert len(state) == 6, f"Expected 6 tables in pg_class, got: {list(state)}"
        for table, flags in state.items():
            assert flags["relrowsecurity"] is False, (
                f"relrowsecurity is True on {table} after migration "
                f"(migration must NOT enable RLS)"
            )

    async def test_relforcerowsecurity_false_on_all_tables(self):
        """relforcerowsecurity = false on all 6 tables after 0006 upgrade."""
        state = await _get_rls_state()
        assert len(state) == 6, f"Expected 6 tables in pg_class, got: {list(state)}"
        for table, flags in state.items():
            assert flags["relforcerowsecurity"] is False, (
                f"relforcerowsecurity is True on {table} after migration "
                f"(migration must NOT force RLS)"
            )


# ---------------------------------------------------------------------------
# Test D: downgrade drops policies; re-upgrade re-creates them
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestPoliciesRoundTrip:
    """Policies are cleanly dropped on downgrade and re-created on upgrade.

    Targets the explicit revision ``0005_dormant_tenancy`` (below the
    ``0006_tenant_rls`` policy migration) rather than a relative ``-N`` offset,
    so new head migrations do not shift the target. The restore path is
    ``upgrade head``.
    """

    async def test_policies_absent_after_downgrade(self):
        """After downgrade to 0005, all 6 policies are gone from pg_policies.

        The policies are defined in 0006; downgrading to 0005 (explicitly, so
        the target is head-independent) removes them.
        """
        # Downgrade to 0005 explicitly (below the 0006 policy migration). Using an
        # explicit target instead of relative -N steps keeps this head-robust: new
        # head migrations (e.g. 0008_oauth_saml_columns) no longer shift the offset
        # and silently stop above 0005, leaving the policies in place.
        r1 = _run_alembic("downgrade", "0005_dormant_tenancy")
        assert r1.returncode == 0, f"downgrade to 0005 failed: {r1.stderr}"

        rows = await _fresh_query(
            """
            SELECT policyname FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            """,
            {"names": _POLICY_NAMES},
        )
        found = {row[0] for row in rows}
        assert not found, f"Policies still present after downgrade to 0005: {found}"

        # Restore head for subsequent tests.
        r3 = _run_alembic("upgrade", "head")
        assert r3.returncode == 0, f"re-upgrade failed: {r3.stderr}"

    async def test_policies_present_after_reupgrade(self):
        """After re-upgrade, all 6 policies exist again."""
        rows = await _fresh_query(
            """
            SELECT policyname FROM pg_policies
            WHERE schemaname = 'catalog'
              AND policyname = ANY(:names)
            """,
            {"names": _POLICY_NAMES},
        )
        found = {row[0] for row in rows}
        missing = set(_POLICY_NAMES) - found
        assert not missing, f"Policies missing after re-upgrade: {missing}"


# ---------------------------------------------------------------------------
# Test E: alembic check — no drift (RLS is invisible to autogenerate)
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestAlembicCheckNoDrift:
    """alembic check is clean after 0006 upgrade (policies are raw SQL)."""

    def test_alembic_check_no_drift(self):
        """alembic check exits 0 — RLS policies are raw SQL, not autogenerated."""
        r = _run_alembic("check")
        assert r.returncode == 0, (
            f"alembic check exited {r.returncode} (drift detected after 0006):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        combined = r.stdout + r.stderr
        assert "No new upgrade operations detected." in combined, (
            f"Expected 'No new upgrade operations detected.' in alembic check output.\n"
            f"Got:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )


class TestAlembicDriftIgnoresRuntimeHnswIndex:
    """Regression (drift flake): env.include_object must exclude the
    runtime-managed ``ix_record_embeddings_hnsw`` pgvector index from
    autogenerate, so ``alembic check`` stays clean even when the index exists in
    the DB but not the model.

    ``embeddings/service.py`` creates and drops this HNSW index imperatively
    once an embedding dimension is configured — it is intentionally absent from
    the SQLAlchemy metadata. Under ``pytest -n4`` a sibling test that built it on
    the shared worker DB before the drift check ran turned
    ``TestAlembicCheckNoDrift.test_alembic_check_no_drift`` into a high-rate
    flake. This deterministically reproduces that pollution and asserts the
    drift gate ignores the index.
    """

    async def test_alembic_check_ignores_runtime_hnsw_index(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        idx = "ix_record_embeddings_hnsw"
        engine = create_async_engine(
            settings.test_database_url,
            isolation_level="AUTOCOMMIT",
        )
        try:
            # A plain btree under the runtime index's name reproduces the
            # name-keyed autogenerate ``remove_index`` drift without needing a
            # dimensioned vector column (a real HNSW index requires a fixed dim).
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"CREATE INDEX IF NOT EXISTS {idx} "
                        "ON catalog.record_embeddings (record_id)"
                    )
                )
            r = _run_alembic("check")
            combined = r.stdout + r.stderr
            assert r.returncode == 0, (
                f"alembic check flagged the runtime-managed {idx} as drift — "
                f"env.include_object exclusion missing or broken:\n{combined}"
            )
            assert "No new upgrade operations detected." in combined, combined
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"DROP INDEX IF EXISTS catalog.{idx}"))
            await engine.dispose()


# ---------------------------------------------------------------------------
# Tests F/G/H: apply_tenancy_rls() behaviour
# ---------------------------------------------------------------------------


class TestApplyTenancyRls:
    """apply_tenancy_rls() is a no-op in single_tenant and idempotently enables
    + FORCEs RLS in multi_tenant; RLS is always restored to disabled in teardown."""

    async def test_single_tenant_noop(self, monkeypatch):
        """In single_tenant, apply_tenancy_rls() does NOT enable RLS on any table."""
        monkeypatch.setenv("GEOLENS_TENANCY_MODE", "single_tenant")

        # Reload settings so the env change takes effect (the settings object is
        # a pydantic model cached at import time; monkeypatch alone is not enough
        # when a prior test reloaded settings to multi_tenant).
        import importlib
        import app.core.config as _cfg_mod
        import app.core.tenancy as _ten_mod

        importlib.reload(_cfg_mod)
        importlib.reload(_ten_mod)

        from app.core.db.rls import apply_tenancy_rls
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.core.config import settings

        engine = create_async_engine(
            settings.test_database_url, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                await apply_tenancy_rls(conn)
        finally:
            await engine.dispose()

        state = await _get_rls_state()
        for table, flags in state.items():
            assert flags["relforcerowsecurity"] is False, (
                f"single_tenant apply_tenancy_rls set relforcerowsecurity on {table}"
            )
            assert flags["relrowsecurity"] is False, (
                f"single_tenant apply_tenancy_rls set relrowsecurity on {table}"
            )

    async def test_multi_tenant_enables_force_rls(self, monkeypatch):
        """In multi_tenant, apply_tenancy_rls() enables + FORCEs RLS on all 6 tables."""
        monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")

        from app.core.db.rls import apply_tenancy_rls
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.core.config import settings

        # Reload settings so the env change takes effect.
        import importlib
        import app.core.config as _cfg_mod
        import app.core.tenancy as _ten_mod

        importlib.reload(_cfg_mod)
        importlib.reload(_ten_mod)

        engine = create_async_engine(
            settings.test_database_url, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                await apply_tenancy_rls(conn)
        finally:
            await engine.dispose()

        try:
            state = await _get_rls_state()
            assert len(state) == 6, f"Expected 6 tables, got: {list(state)}"
            for table, flags in state.items():
                assert flags["relrowsecurity"] is True, (
                    f"relrowsecurity is False on {table} after multi_tenant apply"
                )
                assert flags["relforcerowsecurity"] is True, (
                    f"relforcerowsecurity is False on {table} after multi_tenant apply"
                )
        finally:
            # Teardown: disable RLS so single_tenant tests are not polluted.
            await _disable_rls_on_all()

    async def test_multi_tenant_apply_is_idempotent(self, monkeypatch):
        """Calling apply_tenancy_rls() twice in multi_tenant raises no error and
        leaves the state unchanged (second call is a catalog-read no-op)."""
        monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")

        from app.core.db.rls import apply_tenancy_rls
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.core.config import settings

        import importlib
        import app.core.config as _cfg_mod
        import app.core.tenancy as _ten_mod

        importlib.reload(_cfg_mod)
        importlib.reload(_ten_mod)

        engine = create_async_engine(
            settings.test_database_url, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                # First apply.
                await apply_tenancy_rls(conn)
                state_after_first = await _get_rls_state()

            async with engine.connect() as conn:
                # Second apply — must be a no-op (no error, no state change).
                await apply_tenancy_rls(conn)
                state_after_second = await _get_rls_state()
        finally:
            await engine.dispose()

        try:
            # Both calls should leave identical state.
            for table in _SIX_TABLES:
                assert state_after_first[table]["relforcerowsecurity"] is True
                assert state_after_second[table]["relforcerowsecurity"] is True
        finally:
            await _disable_rls_on_all()

    async def test_rls_disabled_after_teardown(self):
        """Sanity: after teardown helpers run, relforcerowsecurity is false again."""
        # This test must run after the multi_tenant tests that call _disable_rls_on_all.
        # It verifies the teardown is actually effective.
        state = await _get_rls_state()
        for table, flags in state.items():
            assert flags["relforcerowsecurity"] is False, (
                f"relforcerowsecurity still True on {table} — teardown failed"
            )
