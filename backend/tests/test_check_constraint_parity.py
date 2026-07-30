"""ORM CheckConstraint <-> database parity gate.

fix(#942): ``alembic check`` (the ``make alembic-check`` gate) does not
compare CHECK constraints at all, so an ORM ``CheckConstraint`` and its
migration twin can drift apart with every gate staying green — deleting
``chk_records_spatial_extent_type`` from either the model or migration 0030
alone was invisible to CI.

This test closes the hole by NAME, not by expression: it enumerates every
named ``CheckConstraint`` declared on the ORM metadata and asserts a
same-named CHECK constraint exists on the migrated test database
(``pg_constraint`` with ``contype = 'c'``). Expression text is deliberately
NOT compared — PostgreSQL normalizes and re-prints the SQL it stores
(casts, quoting, operator spelling), so a byte comparison against the ORM
string produces false failures. Name-existence is the reliable 80%: it
catches a constraint dropped or renamed on either side, which is the drift
mode that actually occurs.

Enumeration is from ``Base.metadata``, so a new ``CheckConstraint`` is
covered the day it lands with no second edit here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, text

pytestmark = pytest.mark.anyio


# Constraints declared on the ORM but deliberately NOT mirrored in the
# database. Empty today; add names here with a comment explaining why the
# mismatch is intentional, so an exemption is always explicit rather than
# the check silently not looking.
_ORM_ONLY_ALLOWLIST: frozenset[str] = frozenset()

# CHECK constraints that exist in the database but have no ORM declaration
# are fine (migrations may add DB-only guards); this gate is one-directional
# on purpose. NOT NULL checks and domain constraints are excluded by
# conname pattern below only insofar as they never collide with ORM names.


def _orm_check_constraints() -> dict[str, str]:
    """Return {constraint_name: table_name} for named ORM CheckConstraints."""
    from app.core.db import Base

    found: dict[str, str] = {}
    unnamed: list[str] = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            name = constraint.name
            if name is None or not isinstance(name, str):
                unnamed.append(f"{table.fullname}: {constraint.sqltext}")
                continue
            found[name] = table.fullname
    assert not unnamed, (
        "Unnamed ORM CheckConstraint(s) found — a nameless constraint cannot "
        "be checked for parity with the migrated schema. Give each one an "
        "explicit chk_* name:\n" + "\n".join(unnamed)
    )
    return found


async def _db_check_constraint_names(session) -> set[str]:
    result = await session.execute(
        text(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE con.contype = 'c'
              AND nsp.nspname = 'catalog'
            """
        )
    )
    return {row[0] for row in result}


def _missing_in_db(
    orm_constraints: dict[str, str], db_names: set[str]
) -> dict[str, str]:
    return {
        name: table
        for name, table in sorted(orm_constraints.items())
        if name not in db_names and name not in _ORM_ONLY_ALLOWLIST
    }


async def test_every_orm_check_constraint_exists_in_migrated_db(test_db_session):
    """Deleting a CheckConstraint from a migration but not the ORM fails here.

    The inverse edit (deleting from the ORM, keeping the migration) is caught
    too, indirectly: the constraint disappears from the enumeration, and the
    companion pinning tests for load-bearing constraints (e.g.
    test_antimeridian_extent.py for chk_records_spatial_extent_type) fail on
    behavior. See #942 for why ``alembic check`` cannot do this itself.
    """
    orm_constraints = _orm_check_constraints()
    assert orm_constraints, "ORM metadata unexpectedly declares no CheckConstraints"

    db_names = await _db_check_constraint_names(test_db_session)
    missing = _missing_in_db(orm_constraints, db_names)
    assert not missing, (
        "ORM CheckConstraint(s) with no same-named CHECK constraint in the "
        "migrated database — the migration side was dropped, renamed, or "
        "never written. Fix the migration chain (and run `make "
        "alembic-check` for the columns it CAN see), or add an explicit "
        "allowlist entry with rationale:\n"
        + "\n".join(
            f"  {name} (declared on {table})" for name, table in missing.items()
        )
    )

    stale_allowlist = _ORM_ONLY_ALLOWLIST - set(orm_constraints)
    assert not stale_allowlist, (
        "Allowlist entries with no matching ORM CheckConstraint — remove "
        f"them: {sorted(stale_allowlist)}"
    )


async def test_parity_gate_catches_a_dropped_constraint(test_db_session):
    """Negative control (issue #942 acceptance): dropping
    ``chk_records_spatial_extent_type`` from the database alone — the edit
    ``alembic check`` cannot see — is flagged. The DDL runs uncommitted and
    is rolled back, so the shared test database is untouched."""
    orm_constraints = _orm_check_constraints()
    assert "chk_records_spatial_extent_type" in orm_constraints

    await test_db_session.execute(
        text(
            "ALTER TABLE catalog.records "
            "DROP CONSTRAINT chk_records_spatial_extent_type"
        )
    )
    try:
        db_names = await _db_check_constraint_names(test_db_session)
        missing = _missing_in_db(orm_constraints, db_names)
        assert "chk_records_spatial_extent_type" in missing
    finally:
        await test_db_session.rollback()

    # And the constraint is back after the rollback.
    db_names = await _db_check_constraint_names(test_db_session)
    assert "chk_records_spatial_extent_type" in db_names
