"""ISO-03 mode-aware RLS drift gate (Phase 1208-03).

Reflects ``pg_policies`` + ``pg_class.relrowsecurity/relforcerowsecurity`` for
the 6 tenant-shared control-plane tables and compares the live state to the
checked-in ``rls_snapshot.json``.  Fails CI if:

  - A policy is missing (operator dropped it).
  - A ``IS NULL`` escape crept into a qual or with_check (fail-open regression).
  - ``current_setting(...)`` is absent from a qual (policy predicate changed).
  - ``relrowsecurity`` / ``relforcerowsecurity`` don't match the per-mode
    expectation (RLS drifted on or off unexpectedly).

Test breakdown
--------------
A (single_tenant, no harness): policies PRESENT, RLS DISABLED (false/false) —
    the default mode, matches the snapshot's ``single_tenant`` block.

B (multi_tenant, via harness): FORCE ENABLED (true/true) — the harness enables
    RLS for the test body; teardown disables it again.

C (self-test): a simulated drift (missing policy or IS NULL in qual) fails the
    gate with a useful diff message — proves the gate has teeth.

``alembic check`` cannot see RLS — this pytest gate is the ONLY guard against
silent policy drops or RLS drift.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_rls_drift_gate.py -x -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Snapshot + constants
# ---------------------------------------------------------------------------

_SNAPSHOT_PATH = Path(__file__).parent / "rls_snapshot.json"

_SIX_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
]

_POLICY_NAMES = [f"tenant_isolation_{t}" for t in _SIX_TABLES]


def _load_snapshot() -> dict:
    return json.loads(_SNAPSHOT_PATH.read_text())


# ---------------------------------------------------------------------------
# DB helpers (AUTOCOMMIT so DDL + DML from teardown are immediately visible)
# ---------------------------------------------------------------------------


async def _reflect_policies(db_url: str) -> list[dict]:
    """Reflect pg_policies for the 6 tables from the live DB."""
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                sa.text(
                    """
                    SELECT policyname, tablename, qual, with_check
                    FROM pg_policies
                    WHERE schemaname = 'catalog'
                      AND policyname = ANY(:names)
                    ORDER BY policyname
                    """
                ),
                {"names": _POLICY_NAMES},
            )
            return [
                {
                    "policyname": r[0],
                    "tablename": r[1],
                    "qual": r[2],
                    "with_check": r[3],
                }
                for r in rows.fetchall()
            ]
    finally:
        await engine.dispose()


async def _reflect_rls_flags(db_url: str) -> dict[str, dict[str, bool]]:
    """Reflect relrowsecurity + relforcerowsecurity for the 6 tables."""
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                sa.text(
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
            )
            return {
                r[0]: {"relrowsecurity": bool(r[1]), "relforcerowsecurity": bool(r[2])}
                for r in rows.fetchall()
            }
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Shared policy assertion helpers
# ---------------------------------------------------------------------------


def _assert_policies_match_snapshot(
    live_policies: list[dict],
    snapshot: dict,
) -> None:
    """Compare live policy state to the snapshot; fail with a diff on mismatch."""
    snap_by_name = {p["policyname"]: p for p in snapshot["policies"]}

    live_names = {p["policyname"] for p in live_policies}
    missing = set(_POLICY_NAMES) - live_names
    assert not missing, (
        f"ISO-03 DRIFT: Policies missing from pg_policies — dropped or never created?\n"
        f"  Missing: {sorted(missing)}\n"
        f"  Present: {sorted(live_names)}\n"
        f"  Expected all 6 from 0006_tenant_rls migration."
    )
    assert len(live_policies) == 6, (
        f"Expected exactly 6 policies, got {len(live_policies)}: {live_names}"
    )

    for policy in live_policies:
        name = policy["policyname"]
        snap = snap_by_name[name]

        qual = policy["qual"] or ""
        with_check = policy["with_check"] or ""

        # 1. current_setting reference must be present (policy not replaced).
        assert snap["qual_contains"] in qual, (
            f"ISO-03 DRIFT: Policy {name!r} qual does not reference "
            f"'{snap['qual_contains']}'.\n"
            f"  Live qual:     {qual!r}\n"
            f"  Snapshot qual: {snap['qual']!r}\n"
            f"  The policy predicate may have changed — update rls_snapshot.json "
            f"intentionally after review."
        )
        assert snap["with_check_contains"] in with_check, (
            f"ISO-03 DRIFT: Policy {name!r} with_check does not reference "
            f"'{snap['with_check_contains']}'.\n"
            f"  Live with_check:     {with_check!r}\n"
            f"  Snapshot with_check: {snap['with_check']!r}"
        )

        # 2. IS NULL escape forbidden (fail-open regression — ISO-02).
        assert "IS NULL" not in qual.upper(), (
            f"ISO-03 DRIFT: Policy {name!r} qual contains IS NULL "
            f"(fail-open escape — forbidden by ISO-02).\n"
            f"  Live qual: {qual!r}\n"
            f"  Remove the OR … IS NULL clause."
        )
        assert "IS NULL" not in with_check.upper(), (
            f"ISO-03 DRIFT: Policy {name!r} with_check contains IS NULL "
            f"(fail-open escape — forbidden by ISO-02).\n"
            f"  Live with_check: {with_check!r}"
        )

        # 3. Full qual matches snapshot (catches any expression change).
        if snap.get("qual") is not None:
            assert qual == snap["qual"], (
                f"ISO-03 DRIFT: Policy {name!r} qual expression changed.\n"
                f"  Live:     {qual!r}\n"
                f"  Snapshot: {snap['qual']!r}\n"
                f"  If this is intentional, update rls_snapshot.json."
            )
        if snap.get("with_check") is not None:
            assert with_check == snap["with_check"], (
                f"ISO-03 DRIFT: Policy {name!r} with_check expression changed.\n"
                f"  Live:     {with_check!r}\n"
                f"  Snapshot: {snap['with_check']!r}\n"
                f"  If this is intentional, update rls_snapshot.json."
            )


def _assert_rls_flags_match_snapshot(
    live_flags: dict[str, dict[str, bool]],
    snapshot: dict,
    mode: str,
) -> None:
    """Compare live RLS flags to the snapshot for *mode* (single_tenant/multi_tenant)."""
    snap_flags = snapshot["rls_flags"][mode]

    assert set(live_flags.keys()) == set(snap_flags.keys()), (
        f"ISO-03 DRIFT: Unexpected table set in pg_class.\n"
        f"  Live:     {sorted(live_flags)}\n"
        f"  Snapshot: {sorted(snap_flags)}\n"
    )

    mismatches = []
    for table in sorted(snap_flags):
        expected = snap_flags[table]
        actual = live_flags.get(table, {})
        for flag in ("relrowsecurity", "relforcerowsecurity"):
            if actual.get(flag) != expected[flag]:
                mismatches.append(
                    f"  {table}.{flag}: live={actual.get(flag)!r}, "
                    f"expected={expected[flag]!r} (mode={mode})"
                )

    assert not mismatches, (
        f"ISO-03 DRIFT: RLS flag mismatch in mode '{mode}'.\n"
        + "\n".join(mismatches)
        + "\n\nIf RLS was intentionally toggled, update rls_snapshot.json."
    )


# ---------------------------------------------------------------------------
# Test A: single_tenant — policies PRESENT, RLS DISABLED
# ---------------------------------------------------------------------------


class TestSingleTenantSnapshot:
    """In the default single_tenant test mode: 6 policies exist, RLS disabled."""

    async def test_six_policies_present(self):
        """All 6 tenant_isolation_* policies exist in pg_policies."""
        from app.core.config import settings

        live = await _reflect_policies(settings.database_url)
        snap = _load_snapshot()
        _assert_policies_match_snapshot(live, snap)

    async def test_rls_disabled_single_tenant(self):
        """relrowsecurity=False + relforcerowsecurity=False in single_tenant."""
        from app.core.config import settings

        live_flags = await _reflect_rls_flags(settings.database_url)
        snap = _load_snapshot()
        _assert_rls_flags_match_snapshot(live_flags, snap, "single_tenant")

    async def test_no_is_null_in_quals(self):
        """No policy qual or with_check contains IS NULL (no fail-open escape)."""
        from app.core.config import settings

        live = await _reflect_policies(settings.database_url)
        for policy in live:
            qual = policy["qual"] or ""
            with_check = policy["with_check"] or ""
            assert "IS NULL" not in qual.upper(), (
                f"Policy {policy['policyname']!r} qual has IS NULL: {qual!r}"
            )
            assert "IS NULL" not in with_check.upper(), (
                f"Policy {policy['policyname']!r} with_check has IS NULL: {with_check!r}"
            )

    async def test_snapshot_file_is_valid_json(self):
        """rls_snapshot.json parses cleanly and has expected keys."""
        snap = _load_snapshot()
        assert snap["version"] == 1
        assert len(snap["policies"]) == 6
        assert "single_tenant" in snap["rls_flags"]
        assert "multi_tenant" in snap["rls_flags"]
        assert len(snap["rls_flags"]["single_tenant"]) == 6
        assert len(snap["rls_flags"]["multi_tenant"]) == 6


# ---------------------------------------------------------------------------
# Test B: multi_tenant (via harness) — FORCE ENABLED
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestMultiTenantSnapshot:
    """After apply_tenancy_rls: relrowsecurity=True + relforcerowsecurity=True."""

    async def test_rls_force_enabled_multi_tenant(self, multi_tenant_rls):
        """In multi_tenant (harness), all 6 tables have FORCE RLS enabled."""
        live_flags = await _reflect_rls_flags(multi_tenant_rls.db_url)
        snap = _load_snapshot()
        _assert_rls_flags_match_snapshot(live_flags, snap, "multi_tenant")

    async def test_policies_still_present_in_multi_tenant(self, multi_tenant_rls):
        """Policies remain present after apply_tenancy_rls (no side-effect on policies)."""
        live = await _reflect_policies(multi_tenant_rls.db_url)
        snap = _load_snapshot()
        _assert_policies_match_snapshot(live, snap)


# ---------------------------------------------------------------------------
# Test C: self-test — simulated drift triggers the gate (gate has teeth)
# ---------------------------------------------------------------------------


class TestDriftGateSelfTest:
    """Prove that the gate fails loudly when drift is simulated in-memory."""

    def test_missing_policy_fails_gate(self):
        """Simulating a missing policy raises AssertionError with a clear message."""
        snap = _load_snapshot()
        # Remove one policy from the live set.
        live = [
            p for p in snap["policies"] if p["policyname"] != "tenant_isolation_users"
        ]
        synthetic_live = [
            {
                "policyname": p["policyname"],
                "tablename": p["tablename"],
                "qual": p["qual"],
                "with_check": p["with_check"],
            }
            for p in live
        ]

        with pytest.raises(AssertionError, match="tenant_isolation_users"):
            _assert_policies_match_snapshot(synthetic_live, snap)

    def test_null_escape_in_qual_fails_gate(self):
        """Simulating IS NULL in a qual raises AssertionError with ISO-03 DRIFT message."""
        snap = _load_snapshot()
        # Inject a fail-open IS NULL escape into the first policy's qual.
        live = []
        for p in snap["policies"]:
            qual = p["qual"] or ""
            if p["policyname"] == "tenant_isolation_users":
                qual = f"({qual} OR tenant_id IS NULL)"
            live.append(
                {
                    "policyname": p["policyname"],
                    "tablename": p["tablename"],
                    "qual": qual,
                    "with_check": p["with_check"],
                }
            )

        with pytest.raises(AssertionError, match="IS NULL"):
            _assert_policies_match_snapshot(live, snap)

    def test_rls_flag_off_in_multi_tenant_fails_gate(self):
        """Simulating relforcerowsecurity=False in multi_tenant raises AssertionError."""
        snap = _load_snapshot()
        # Simulate RLS accidentally disabled on one table.
        live_flags = {
            t: {"relrowsecurity": True, "relforcerowsecurity": True}
            for t in _SIX_TABLES
        }
        live_flags["users"]["relforcerowsecurity"] = False

        with pytest.raises(AssertionError, match="users.relforcerowsecurity"):
            _assert_rls_flags_match_snapshot(live_flags, snap, "multi_tenant")

    def test_rls_flag_on_in_single_tenant_fails_gate(self):
        """Simulating relrowsecurity=True in single_tenant raises AssertionError."""
        snap = _load_snapshot()
        # Simulate RLS accidentally left on (would block all single_tenant queries).
        live_flags = {
            t: {"relrowsecurity": False, "relforcerowsecurity": False}
            for t in _SIX_TABLES
        }
        live_flags["datasets"]["relrowsecurity"] = True

        with pytest.raises(AssertionError, match="datasets.relrowsecurity"):
            _assert_rls_flags_match_snapshot(live_flags, snap, "single_tenant")
