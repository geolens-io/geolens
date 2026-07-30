"""ORM CheckConstraint <-> database parity gate.

fix(#942): ``alembic check`` (the ``make alembic-check`` gate) does not
compare CHECK constraints at all, so an ORM ``CheckConstraint`` and its
migration twin can drift apart with every gate staying green — deleting
``chk_records_spatial_extent_type`` from either the model or migration 0030
alone was invisible to CI.

This gate closes the hole by (table, name) pair, not by expression:

- Forward: every named ``CheckConstraint`` declared on the ORM metadata must
  exist as a same-named CHECK on the SAME table in the migrated test
  database (``pg_constraint`` with ``contype = 'c'``). Matching on the pair
  rather than the bare name means a constraint moved to the wrong table
  cannot masquerade as parity (codex review on the #942 PR).
- Reverse: a CHECK in the database on an ORM-managed table with no ORM
  declaration is flagged too — that is exactly what an ORM-side deletion
  leaves behind — unless listed in the explicit DB-only allowlist.

Expression text is deliberately NOT compared — PostgreSQL normalizes and
re-prints the SQL it stores (casts, quoting, operator spelling), so a byte
comparison against the ORM string produces false failures. Pair-existence is
the reliable 80%: it catches a constraint dropped, renamed, or re-homed on
either side, which are the drift modes that actually occur.

Enumeration is from ``Base.metadata``, so a new ``CheckConstraint`` is
covered the day it lands with no second edit here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, text

pytestmark = pytest.mark.anyio


# Constraints declared on the ORM but deliberately NOT mirrored in the
# database. Empty today; add (table, name) pairs here with a comment
# explaining why the mismatch is intentional, so an exemption is always
# explicit rather than the check silently not looking.
_ORM_ONLY_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

# CHECK constraints that legitimately exist ONLY in the database (added by a
# migration with no ORM declaration) on tables the ORM manages. Same rule:
# explicit pair + comment, or the reverse leg fails.
_DB_ONLY_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()


def _orm_check_constraints() -> dict[tuple[str, str], str]:
    """Return {(table_fullname, constraint_name): table} for named constraints."""
    from app.core.db import Base

    found: dict[tuple[str, str], str] = {}
    unnamed: list[str] = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            name = constraint.name
            if name is None or not isinstance(name, str):
                unnamed.append(f"{table.fullname}: {constraint.sqltext}")
                continue
            found[(table.fullname, name)] = table.fullname
    assert not unnamed, (
        "Unnamed ORM CheckConstraint(s) found — a nameless constraint cannot "
        "be checked for parity with the migrated schema. Give each one an "
        "explicit chk_* name:\n" + "\n".join(unnamed)
    )
    return found


async def _db_check_constraint_pairs(session) -> set[tuple[str, str]]:
    """Return {(schema.table, conname)} for catalog-schema CHECK constraints.

    Excludes NOT NULL constraints (PG 18 represents them in pg_constraint as
    contype 'n', so contype='c' already covers only real CHECKs).
    """
    result = await session.execute(
        text(
            """
            SELECT nsp.nspname || '.' || rel.relname AS tbl, con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE con.contype = 'c'
              AND nsp.nspname = 'catalog'
            """
        )
    )
    return {(row[0], row[1]) for row in result}


async def test_every_orm_check_constraint_exists_in_migrated_db(test_db_session):
    """Deleting or re-homing a CheckConstraint on either side fails here."""
    orm_pairs = set(_orm_check_constraints())
    assert orm_pairs, "ORM metadata unexpectedly declares no CheckConstraints"

    db_pairs = await _db_check_constraint_pairs(test_db_session)

    missing = sorted(orm_pairs - db_pairs - _ORM_ONLY_ALLOWLIST)
    assert not missing, (
        "ORM CheckConstraint(s) with no same-named CHECK constraint on the "
        "same table in the migrated database — the migration side was "
        "dropped, renamed, or re-homed. Fix the migration chain, or add an "
        "explicit allowlist entry with rationale:\n"
        + "\n".join(f"  {name} (declared on {table})" for table, name in missing)
    )

    # Reverse leg: a DB CHECK on an ORM-managed table with no ORM declaration
    # is what an ORM-side deletion leaves behind.
    orm_tables = {table for table, _ in orm_pairs}
    db_only = sorted(
        pair
        for pair in db_pairs - orm_pairs - _DB_ONLY_ALLOWLIST
        if pair[0] in orm_tables
    )
    assert not db_only, (
        "CHECK constraint(s) in the database on ORM-managed tables with no "
        "ORM CheckConstraint declaration — either the ORM side was deleted "
        "(restore it) or the constraint is deliberately DB-only (add an "
        "explicit allowlist entry with rationale):\n"
        + "\n".join(f"  {name} (on {table})" for table, name in db_only)
    )

    for allowlist, label in (
        (_ORM_ONLY_ALLOWLIST, "_ORM_ONLY_ALLOWLIST"),
        (_DB_ONLY_ALLOWLIST, "_DB_ONLY_ALLOWLIST"),
    ):
        stale = sorted(allowlist & orm_pairs & db_pairs)
        assert not stale, (
            f"{label} entries that exist on both sides — the exemption is "
            f"dead, remove it: {stale}"
        )


async def test_parity_gate_catches_a_dropped_constraint(test_db_session):
    """Negative control (issue #942 acceptance): dropping
    ``chk_records_spatial_extent_type`` from the database alone — the edit
    ``alembic check`` cannot see — is flagged, on its declaring table. The
    DDL runs uncommitted and is rolled back, so the test database is
    untouched."""
    target = ("catalog.records", "chk_records_spatial_extent_type")
    orm_pairs = set(_orm_check_constraints())
    assert target in orm_pairs

    await test_db_session.execute(
        text(
            "ALTER TABLE catalog.records "
            "DROP CONSTRAINT chk_records_spatial_extent_type"
        )
    )
    try:
        db_pairs = await _db_check_constraint_pairs(test_db_session)
        assert target in (orm_pairs - db_pairs)
    finally:
        await test_db_session.rollback()

    # And the constraint is back after the rollback.
    db_pairs = await _db_check_constraint_pairs(test_db_session)
    assert target in db_pairs
