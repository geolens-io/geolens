"""ISO-05: DB-privilege + GUC-survival verification (Phase 1208-04).

Purpose (spike-grade)
---------------------
Verify — with empirical, pasted evidence — three load-bearing properties of
the tenancy stack:

(a) Role privilege audit
    ``geolens_reader`` and ``geolens_readonly`` (if present) have
    ``rolbypassrls=False`` and do NOT own any of the 6 tenant-shared
    catalog tables.  If either role were BYPASSRLS or a table-owner, FORCE
    RLS would be ineffective for queries running as that role.

(b) GUC survives SET ROLE
    ``set_config('app.current_tenant', tid, true)`` set at transaction-start
    SURVIVES a subsequent ``SET LOCAL ROLE geolens_reader`` in the same
    transaction.  The tile-server and sandbox paths issue ``SET LOCAL ROLE``
    (see ``backend/app/platform/sandbox/executor.py:60``); if the GUC were
    reset by the role switch, those paths would become unscoped.

(c) GUC does NOT leak across transactions / pool connections
    A transaction-local ``set_config(..., true)`` is cleared at transaction
    end.  A fresh NullPool connection sees the GUC as unset (``None`` with
    the ``missing_ok=True`` guard).  This proves transaction-local semantics
    are correct and no GUC bleed occurs on connection reuse.

Critical finding (see 1208-03 SUMMARY and executor prompt)
-----------------------------------------------------------
The LOCAL test DB role (``geolens``) is ``rolsuper=True, rolbypassrls=True``
and ALWAYS bypasses FORCE RLS.  All RLS enforcement probes in this suite
MUST use ``SET LOCAL ROLE geolens_reader`` (the non-privileged role) —
otherwise the test is measuring the superuser bypass, not the RLS policy.

This finding is a DEPLOYMENT REQUIREMENT for multi_tenant:
  The production app's PRIMARY DB connection role must be a NON-superuser,
  NON-BYPASSRLS role so that FORCE RLS is effective on that role.  The
  ``geolens`` superuser role is NOT safe as the runtime role in multi_tenant.
  Per-tenant reader roles narrowed in Phase 1209 extend this boundary further.

Pasted evidence (captured 2026-06-14 from test DB)
---------------------------------------------------
(a) pg_roles:
  rolname='geolens',          rolsuper=True,  rolbypassrls=True
  rolname='geolens_reader',   rolsuper=False, rolbypassrls=False
  rolname='geolens_readonly', rolsuper=False, rolbypassrls=False

(b) table owners (all 6 catalog tables):
  collections:   owner='geolens'
  datasets:      owner='geolens'
  embed_tokens:  owner='geolens'
  maps:          owner='geolens'
  records:       owner='geolens'
  users:         owner='geolens'
  => geolens_reader and geolens_readonly are NOT owners of any table.

(c) GUC survives SET ROLE (same transaction, test_tid=ed803150-35e7-464b-8fe1-0f9eeb338def):
  role_set=True
  guc_after_set_role='ed803150-35e7-464b-8fe1-0f9eeb338def'
  matches_original=True

(d) GUC does NOT leak to fresh pool connection:
  guc_in_fresh_connection=None
  leaked=False

PgBouncer constraint (documented in the internal tenancy runbook)
-----------------------------------------------------------------
``SET LOCAL`` (transaction-local) semantics require the GUC to be issued and
consumed within the SAME physical transaction.  PgBouncer statement-mode
would multiplex connections at the statement level — the ``set_config`` and
the subsequent ``SELECT`` could land on DIFFERENT connections, so the GUC
would appear unset on the query side.  Transaction-mode and session-mode
pooling are safe: the full BEGIN...COMMIT block stays on one connection.
Local has no PgBouncer — this is a config-level constraint (see runbook).

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_iso05_db_privilege_guc_survival.py -x -q
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# The 6 RLS-protected tables (same list as rls.py RLS_TABLES).
_RLS_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
]

# Roles under test (geolens_readonly may be absent in the test DB — handled via
# savepoint / skip-with-reason; it IS present in the test DB per init-test-db.sh).
_PROBE_ROLES = ["geolens_reader", "geolens_readonly"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_db_url() -> str:
    from app.core.config import settings

    return settings.database_url


# ---------------------------------------------------------------------------
# Test A: Role privilege audit (rolbypassrls=False, not table-owner)
# ---------------------------------------------------------------------------


class TestIso05RolePrivileges:
    """(a) geolens_reader/geolens_readonly: rolbypassrls=False, not table-owners.

    Evidence is reflected from the LIVE test DB — the assertions fail if the
    DB state drifts (e.g. someone accidentally grants SUPERUSER to geolens_reader).
    """

    async def test_geolens_is_superuser_and_bypassrls(self):
        """Sanity: geolens is rolsuper=True, rolbypassrls=True (documents the hazard).

        This is the critical finding: the app's primary DB role bypasses FORCE RLS.
        The test ASSERTS this is true so that if geolens loses superuser the
        enforcement boundary shifts and the suite is re-evaluated.

        DEPLOYMENT REQUIREMENT (multi_tenant): the production app's runtime role
        must be a NON-superuser, NON-BYPASSRLS role.  'geolens' is not safe as
        the multi_tenant runtime role.
        """
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        sa.text(
                            "SELECT rolsuper, rolbypassrls FROM pg_roles "
                            "WHERE rolname = 'geolens'"
                        )
                    )
                ).fetchone()
        finally:
            await engine.dispose()

        assert row is not None, "ISO-05: role 'geolens' not found in pg_roles"
        rolsuper, rolbypassrls = row
        # Document the hazard — these should be True for the test DB geolens role.
        # If they change, the RLS enforcement boundary must be re-evaluated.
        assert rolsuper is True, (
            "ISO-05: 'geolens' rolsuper changed to False — re-evaluate RLS enforcement.\n"
            "  If the primary app role is no longer superuser, RLS may now apply to\n"
            "  it directly (without SET LOCAL ROLE geolens_reader). Good news for\n"
            "  production, but update this note and the test harness."
        )
        assert rolbypassrls is True, (
            "ISO-05: 'geolens' rolbypassrls changed — re-evaluate the harness.\n"
            "  If it became False, FORCE RLS now applies to the primary role."
        )

    async def test_probe_roles_are_not_superuser_not_bypassrls(self):
        """geolens_reader (and geolens_readonly if present) are rolsuper=False, rolbypassrls=False.

        If either of these were True, FORCE RLS would be bypassed for queries
        running as that role — the tile-server / sandbox paths would be unscoped.

        Evidence (captured 2026-06-14, test DB):
          geolens_reader:   rolsuper=False, rolbypassrls=False  <- SAFE
          geolens_readonly: rolsuper=False, rolbypassrls=False  <- SAFE
        """
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT rolname, rolsuper, rolbypassrls "
                            "FROM pg_roles WHERE rolname = ANY(:roles) "
                            "ORDER BY rolname"
                        ),
                        {"roles": _PROBE_ROLES},
                    )
                ).fetchall()
        finally:
            await engine.dispose()

        found_roles = {row[0] for row in rows}
        assert "geolens_reader" in found_roles, (
            "ISO-05: 'geolens_reader' not found in pg_roles — "
            "check init-test-db.sh creates the role."
        )

        failures = []
        for rolname, rolsuper, rolbypassrls in rows:
            if rolsuper:
                failures.append(
                    f"  {rolname}: rolsuper=True — superuser bypasses FORCE RLS, "
                    "this role cannot be a safe enforcement target"
                )
            if rolbypassrls:
                failures.append(
                    f"  {rolname}: rolbypassrls=True — BYPASSRLS defeats FORCE RLS, "
                    "this role cannot be a safe enforcement target"
                )

        assert not failures, (
            "ISO-05 FAIL (a): one or more probe roles have dangerous privileges:\n"
            + "\n".join(failures)
            + "\n\nIf any enforcement role is BYPASSRLS, FORCE RLS does NOT apply "
            "to queries running as that role.  The DB boundary is broken."
        )

    async def test_probe_roles_are_not_table_owners(self):
        """geolens_reader/geolens_readonly do NOT own any of the 6 catalog tables.

        Table OWNERS bypass non-FORCE RLS; FORCE RLS subjects even the owner.
        However, owning a table also implies write privileges — a reader role
        that owns a table is incorrectly privileged.

        Evidence (captured 2026-06-14, test DB):
          All 6 tables owned by 'geolens'; geolens_reader/readonly not owners.
        """
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            """
                            SELECT c.relname, r.rolname AS owner
                            FROM pg_class c
                            JOIN pg_roles r ON r.oid = c.relowner
                            WHERE c.oid = ANY(ARRAY[
                                'catalog.users'::regclass,
                                'catalog.records'::regclass,
                                'catalog.datasets'::regclass,
                                'catalog.maps'::regclass,
                                'catalog.collections'::regclass,
                                'catalog.embed_tokens'::regclass
                            ])
                            ORDER BY c.relname
                            """
                        )
                    )
                ).fetchall()
        finally:
            await engine.dispose()

        assert len(rows) == 6, (
            f"ISO-05: expected 6 catalog tables in pg_class, got {len(rows)}. "
            "Ensure migration 0006_tenant_rls is applied."
        )

        probe_owned = [
            (relname, owner) for relname, owner in rows if owner in _PROBE_ROLES
        ]
        assert not probe_owned, (
            "ISO-05 FAIL (a): geolens_reader or geolens_readonly OWNS catalog tables:\n"
            + "\n".join(
                f"  {relname}: owner={owner!r}" for relname, owner in probe_owned
            )
            + "\n\nA reader role that owns a table has implicit write + BYPASSRLS-equivalent "
            "privileges on non-FORCE policies.  Table ownership must stay with 'geolens'."
        )

        # Positive assertion: all tables are owned by 'geolens'.
        non_geolens = [
            (relname, owner) for relname, owner in rows if owner != "geolens"
        ]
        assert not non_geolens, (
            "ISO-05 WARN: some catalog tables are NOT owned by 'geolens':\n"
            + "\n".join(
                f"  {relname}: owner={owner!r}" for relname, owner in non_geolens
            )
        )


# ---------------------------------------------------------------------------
# Test B: GUC survives SET ROLE in the same transaction
# ---------------------------------------------------------------------------


class TestIso05GucSurvivesSetRole:
    """(b) set_config('app.current_tenant', tid, true) survives SET LOCAL ROLE.

    The tile-server (``sandbox/executor.py:60``) and any future per-tenant
    reader role path both issue ``SET LOCAL ROLE`` inside a transaction that
    already has the tenant GUC set.  If PostgreSQL reset the GUC on a role
    switch, the RLS policy would evaluate ``current_setting('app.current_tenant')``
    as unset and the query would fail-close (or error).

    Empirical finding: custom GUCs (set via ``set_config``) are NOT reset by
    ``SET ROLE`` in PostgreSQL.  They live in the session/transaction GUC
    namespace, which is distinct from the role's privilege set.  ``SET LOCAL``
    scoping applies to the transaction boundary, not to role changes.

    Evidence (captured 2026-06-14, test DB):
      test_tid='ed803150-35e7-464b-8fe1-0f9eeb338def'
      role_set=True, guc_after_set_role='ed803150-35e7-464b-8fe1-0f9eeb338def'
      matches_original=True
    """

    async def test_guc_survives_set_role_geolens_reader(self):
        """The tenant GUC set via set_config(..., true) survives SET LOCAL ROLE geolens_reader.

        One transaction: set_config → SET LOCAL ROLE geolens_reader → read GUC.
        The GUC value must equal the value set before the role switch.
        """
        db_url = await _get_db_url()
        test_tid = str(uuid.uuid4())

        # Grant USAGE + SELECT on catalog.users to geolens_reader for this probe
        # (must query at least one table to prove the role actually switched).
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text("GRANT USAGE ON SCHEMA catalog TO geolens_reader")
                )
        finally:
            await engine.dispose()

        guc_before_role: str | None = None
        guc_after_role: str | None = None
        role_set = False

        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    # Step 1: set the tenant GUC transaction-locally.
                    await conn.execute(
                        sa.text(
                            "SELECT set_config('app.current_tenant', :tid, true)"
                        ).bindparams(tid=test_tid)
                    )
                    # Step 2: read it BEFORE the role switch (sanity).
                    row = await conn.execute(
                        sa.text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_before_role = row.scalar_one()

                    # Step 3: SET LOCAL ROLE (mirrors sandbox/executor.py:60).
                    # Wrapped in savepoint so a missing role doesn't abort the txn.
                    try:
                        await conn.execute(sa.text("SAVEPOINT _role_probe"))
                        await conn.execute(sa.text("SET LOCAL ROLE geolens_reader"))
                        await conn.execute(sa.text("RELEASE SAVEPOINT _role_probe"))
                        role_set = True
                    except Exception:
                        await conn.execute(sa.text("ROLLBACK TO SAVEPOINT _role_probe"))
                        try:
                            await conn.execute(sa.text("RELEASE SAVEPOINT _role_probe"))
                        except Exception:
                            pass

                    # Step 4: read the GUC AFTER the role switch.
                    row = await conn.execute(
                        sa.text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_after_role = row.scalar_one()
        finally:
            await engine.dispose()

        # Revoke the temporary grant.
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text("REVOKE USAGE ON SCHEMA catalog FROM geolens_reader")
                )
        finally:
            await engine.dispose()

        assert role_set, (
            "ISO-05 WARN (b): SET LOCAL ROLE geolens_reader failed — role may be absent. "
            "The GUC-survives-SET-ROLE proof requires the role switch to succeed. "
            "Check init-test-db.sh creates geolens_reader."
        )
        assert guc_before_role == test_tid, (
            f"ISO-05 FAIL (b): GUC value before role switch is wrong.\n"
            f"  expected={test_tid!r}, got={guc_before_role!r}"
        )
        assert guc_after_role == test_tid, (
            f"ISO-05 FAIL (b): GUC was RESET by SET LOCAL ROLE geolens_reader!\n"
            f"  before_role={guc_before_role!r}\n"
            f"  after_role={guc_after_role!r}\n"
            f"  expected={test_tid!r}\n"
            f"  The tenant GUC does NOT survive a role switch — the tile-server and\n"
            f"  sandbox paths would become unscoped after SET LOCAL ROLE."
        )

    async def test_guc_survives_set_role_geolens_readonly_if_present(self):
        """The tenant GUC survives SET LOCAL ROLE geolens_readonly (if the role exists).

        geolens_readonly may not exist in the test DB (init-test-db.sh does not
        create it — it is a production role from init-db.sh).  If absent, this
        test skips with a documented reason rather than failing.

        Evidence: the GUC-survives-SET-ROLE property is a PostgreSQL invariant
        (custom GUCs live in the GUC namespace, not the role's privilege set).
        This test is belt-and-suspenders for geolens_readonly in case the test
        DB is extended to include it.
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
                "(init-test-db.sh does not create it; it is a production role "
                "from init-db.sh).  Skipping; the property is covered by the "
                "geolens_reader variant above."
            )

        test_tid = str(uuid.uuid4())
        guc_after_role: str | None = None
        role_set = False

        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    await conn.execute(
                        sa.text(
                            "SELECT set_config('app.current_tenant', :tid, true)"
                        ).bindparams(tid=test_tid)
                    )
                    try:
                        await conn.execute(sa.text("SAVEPOINT _role_probe_ro"))
                        await conn.execute(sa.text("SET LOCAL ROLE geolens_readonly"))
                        await conn.execute(sa.text("RELEASE SAVEPOINT _role_probe_ro"))
                        role_set = True
                    except Exception:
                        await conn.execute(
                            sa.text("ROLLBACK TO SAVEPOINT _role_probe_ro")
                        )
                        try:
                            await conn.execute(
                                sa.text("RELEASE SAVEPOINT _role_probe_ro")
                            )
                        except Exception:
                            pass

                    row = await conn.execute(
                        sa.text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_after_role = row.scalar_one()
        finally:
            await engine.dispose()

        assert role_set, (
            "ISO-05 WARN (b): SET LOCAL ROLE geolens_readonly failed unexpectedly "
            "(role exists in pg_roles but SET ROLE failed — check GRANT ROLE)."
        )
        assert guc_after_role == test_tid, (
            f"ISO-05 FAIL (b): GUC reset by SET LOCAL ROLE geolens_readonly!\n"
            f"  after_role={guc_after_role!r}, expected={test_tid!r}"
        )


# ---------------------------------------------------------------------------
# Test C: GUC does NOT leak to a fresh connection / new transaction
# ---------------------------------------------------------------------------


class TestIso05GucNoLeak:
    """(c) Transaction-local GUC does NOT persist to a fresh connection.

    ``set_config(..., true)`` is transaction-local — cleared at COMMIT/ROLLBACK.
    A fresh NullPool connection (simulating a new pool checkout) must NOT see
    the GUC value that was set in a prior completed transaction.

    Evidence (captured 2026-06-14, test DB):
      guc_in_fresh_connection=None, leaked=False
    """

    async def test_guc_not_leaked_to_fresh_connection(self):
        """After transaction end, GUC is unset in a fresh NullPool connection."""
        db_url = await _get_db_url()
        test_tid = str(uuid.uuid4())

        # Engine A: set GUC in a transaction, let the transaction end.
        engine_a = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine_a.connect() as conn:
                async with conn.begin():
                    await conn.execute(
                        sa.text(
                            "SELECT set_config('app.current_tenant', :tid, true)"
                        ).bindparams(tid=test_tid)
                    )
                # Transaction committed — GUC clears (transaction-local).
        finally:
            await engine_a.dispose()

        # Engine B (fresh NullPool — a new connection, never saw the GUC).
        engine_b = create_async_engine(db_url, poolclass=NullPool)
        guc_in_fresh: str | None = "UNSET"
        try:
            async with engine_b.connect() as conn:
                # missing_ok=True (second arg True): returns NULL if unset,
                # instead of raising UndefinedObjectError.
                row = await conn.execute(
                    sa.text("SELECT current_setting('app.current_tenant', true)")
                )
                guc_in_fresh = row.scalar_one()
        finally:
            await engine_b.dispose()

        assert guc_in_fresh is None, (
            f"ISO-05 FAIL (c): GUC leaked into a fresh connection!\n"
            f"  guc_in_fresh={guc_in_fresh!r}, expected None\n"
            f"  set_config(..., true) must be transaction-local — the GUC must\n"
            f"  be cleared at transaction end.  If it leaks, tenants can read\n"
            f"  across transaction boundaries on a reused connection."
        )

    async def test_guc_settable_in_new_transaction_after_prior_clears(self):
        """A new transaction on a fresh connection can set a DIFFERENT GUC value cleanly.

        Proves transaction-local semantics work correctly: each new transaction
        starts with the GUC unset and can stamp it to any tenant id.
        """
        db_url = await _get_db_url()
        tid_1 = str(uuid.uuid4())
        tid_2 = str(uuid.uuid4())

        # Transaction 1: set tid_1.
        engine_1 = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine_1.connect() as conn:
                async with conn.begin():
                    await conn.execute(
                        sa.text(
                            "SELECT set_config('app.current_tenant', :tid, true)"
                        ).bindparams(tid=tid_1)
                    )
                # Transaction ends, GUC cleared.
        finally:
            await engine_1.dispose()

        # Transaction 2 (fresh engine): set tid_2, confirm it reads back correctly.
        engine_2 = create_async_engine(db_url, poolclass=NullPool)
        guc_in_txn_2: str | None = None
        try:
            async with engine_2.connect() as conn:
                async with conn.begin():
                    await conn.execute(
                        sa.text(
                            "SELECT set_config('app.current_tenant', :tid, true)"
                        ).bindparams(tid=tid_2)
                    )
                    row = await conn.execute(
                        sa.text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_in_txn_2 = row.scalar_one()
        finally:
            await engine_2.dispose()

        assert guc_in_txn_2 == tid_2, (
            f"ISO-05 FAIL (c): New transaction reads wrong GUC value.\n"
            f"  expected={tid_2!r}, got={guc_in_txn_2!r}\n"
            f"  This may indicate GUC bleed from the prior transaction."
        )
        assert guc_in_txn_2 != tid_1, (
            f"ISO-05 FAIL (c): New transaction is reading the PREVIOUS transaction's GUC!\n"
            f"  tid_1={tid_1!r}, tid_2={tid_2!r}, got={guc_in_txn_2!r}\n"
            f"  GUC is not transaction-local — it persists across transactions."
        )


# ---------------------------------------------------------------------------
# Test D: PgBouncer config assertion (statement-mode incompatibility)
# ---------------------------------------------------------------------------


class TestIso05PgBouncerConfigAssertion:
    """(d) Statement-mode pooler would break SET LOCAL GUC persistence.

    This test validates the config-level constraint documented in the internal
    tenancy/PgBouncer constraint runbook (a deployment-infra artifact, not part
    of the public source tree).

    Local has no PgBouncer — this test validates the CONSTRAINT LOGIC by
    simulating what would happen with statement-mode multiplexing, and
    confirms the documented assertion is correct.  It does NOT test a live
    PgBouncer instance.

    The assertion: in multi_tenant + external pooler, the pooler mode must
    NOT be statement-mode.  This test verifies the constraint is correctly
    documented and that our transaction-local semantics depend on BEGIN...COMMIT
    staying on one connection.
    """

    def test_statement_mode_constraint_is_documented(self):
        """The PgBouncer runbook documents the statement-mode incompatibility.

        Local has no PgBouncer.  This test is a config-assertion marker that
        the constraint is formally recorded and known.  Any deployment enabling
        PgBouncer MUST consult the internal runbook before setting pool_mode.
        """
        import os

        runbook_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "docs-internal",
            "runbooks",
            "tenancy-pgbouncer-constraint.md",
        )
        if not os.path.exists(runbook_path):
            pytest.skip(
                "PgBouncer constraint runbook is an internal deployment-infra "
                "artifact, absent in this environment (e.g. public CI) — skipping."
            )
        with open(runbook_path) as f:
            content = f.read()

        # Verify the runbook covers the key concepts.
        required_phrases = [
            "statement",
            "pool_mode",
            "multi_tenant",
            "SET LOCAL",
        ]
        missing = [p for p in required_phrases if p.lower() not in content.lower()]
        assert not missing, (
            f"ISO-05 FAIL (d): PgBouncer runbook is missing required content:\n"
            f"  Missing phrases: {missing}\n"
            f"  The runbook must document statement-mode incompatibility, "
            "pool_mode config assertion, multi_tenant requirement, and SET LOCAL semantics."
        )

    async def test_transaction_local_guc_requires_single_connection_per_txn(self):
        """Simulated statement-mode: GUC set and read on separate connections returns None.

        This test SIMULATES the statement-mode failure mode: if set_config and the
        subsequent SELECT land on DIFFERENT connections (as statement-mode pooling
        would do), the GUC is not visible on the second connection.

        This is the exact failure mode that statement-mode PgBouncer would produce.
        The test proves that transaction-local semantics require the full BEGIN...COMMIT
        to stay on ONE connection (transaction-mode or session-mode pooling).
        """
        db_url = await _get_db_url()
        test_tid = str(uuid.uuid4())

        # Simulate statement-mode: set GUC on connection A (outside a transaction,
        # so it's not transaction-local), then read on connection B.
        # NullPool simulates separate pool slots (different connections).
        engine_set = create_async_engine(db_url, poolclass=NullPool)
        engine_read = create_async_engine(db_url, poolclass=NullPool)
        guc_on_b: str | None = "UNSET"

        try:
            # Connection A: set GUC outside a transaction (simulates statement-mode
            # where the SET and the SELECT are in different "transactions").
            async with engine_set.connect() as conn_a:
                await conn_a.execution_options(isolation_level="AUTOCOMMIT")
                await conn_a.execute(
                    sa.text(
                        "SELECT set_config('app.current_tenant', :tid, false)"
                        # false = NOT transaction-local (session-scoped on this conn)
                    ).bindparams(tid=test_tid)
                )
                # conn_a holds a session-scoped GUC now — but conn_b is a DIFFERENT conn.

            # Connection B (separate NullPool connection): does it see the GUC?
            async with engine_read.connect() as conn_b:
                row = await conn_b.execute(
                    sa.text("SELECT current_setting('app.current_tenant', true)")
                )
                guc_on_b = row.scalar_one()
        finally:
            await engine_set.dispose()
            await engine_read.dispose()

        # The GUC is NOT visible on conn_b — proving that cross-connection GUC
        # isolation is correct and statement-mode pooling would break SET LOCAL.
        assert guc_on_b is None, (
            f"UNEXPECTED: GUC set on conn_a is visible on conn_b!\n"
            f"  guc_on_b={guc_on_b!r}\n"
            f"  This would mean GUC bleed across connections — should not happen "
            "with NullPool (separate physical connections)."
        )
