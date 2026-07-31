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
  leaves behind — unless listed in the explicit DB-only allowlist. The
  managed-table set comes from ``Base.metadata.tables``, not from the
  surviving constraint pairs, so deleting a one-check table's only
  ``CheckConstraint`` cannot remove the table from the comparison.

Both allowlists are themselves checked: an entry has to stay a *live*
one-sided mismatch. Once the constraint it excuses exists on both sides or on
neither, the exemption is dead and fails the gate, so a stale entry can never
pre-authorize the drift it was never meant to cover.

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


def _orm_managed_tables() -> set[str]:
    """Return every table fullname the ORM metadata declares.

    Derived from ``Base.metadata`` rather than from the constraint pairs
    (codex review on the #942 PR): a table whose *only* ``CheckConstraint``
    was deleted would otherwise vanish from the managed set, and the reverse
    leg would filter out the very leftover it exists to catch. Several tables
    are one-check today (``catalog.record_translations``,
    ``catalog.ingest_jobs``, ``catalog.map_layers``).
    """
    from app.core.db import Base

    return {table.fullname for table in Base.metadata.tables.values()}


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


def _parity_failures(
    orm_pairs: set[tuple[str, str]],
    db_pairs: set[tuple[str, str]],
    orm_tables: set[str],
    orm_only_allowlist: frozenset[tuple[str, str]] = _ORM_ONLY_ALLOWLIST,
    db_only_allowlist: frozenset[tuple[str, str]] = _DB_ONLY_ALLOWLIST,
) -> dict[str, list[tuple[str, str]]]:
    """Pure set comparison, so both legs are testable without a database."""
    return {
        "missing_in_db": sorted(orm_pairs - db_pairs - orm_only_allowlist),
        "db_only": sorted(
            pair
            for pair in db_pairs - orm_pairs - db_only_allowlist
            if pair[0] in orm_tables
        ),
        # An exemption is only justified while the mismatch it excuses is live.
        # Intersecting BOTH sides would let a dead entry survive once the
        # constraint vanishes from the side that justified it (codex review on
        # the #942 PR); the stale entry then silently suppresses real drift the
        # day that constraint is reintroduced.
        "dead_exemptions": sorted(
            (orm_only_allowlist - (orm_pairs - db_pairs))
            | (db_only_allowlist - (db_pairs - orm_pairs))
        ),
    }


async def test_every_orm_check_constraint_exists_in_migrated_db(test_db_session):
    """Deleting or re-homing a CheckConstraint on either side fails here."""
    orm_pairs = set(_orm_check_constraints())
    assert orm_pairs, "ORM metadata unexpectedly declares no CheckConstraints"

    db_pairs = await _db_check_constraint_pairs(test_db_session)
    failures = _parity_failures(orm_pairs, db_pairs, _orm_managed_tables())

    missing = failures["missing_in_db"]
    assert not missing, (
        "ORM CheckConstraint(s) with no same-named CHECK constraint on the "
        "same table in the migrated database — the migration side was "
        "dropped, renamed, or re-homed. Fix the migration chain, or add an "
        "explicit allowlist entry with rationale:\n"
        + "\n".join(f"  {name} (declared on {table})" for table, name in missing)
    )

    db_only = failures["db_only"]
    assert not db_only, (
        "CHECK constraint(s) in the database on ORM-managed tables with no "
        "ORM CheckConstraint declaration — either the ORM side was deleted "
        "(restore it) or the constraint is deliberately DB-only (add an "
        "explicit allowlist entry with rationale):\n"
        + "\n".join(f"  {name} (on {table})" for table, name in db_only)
    )

    dead = failures["dead_exemptions"]
    assert not dead, (
        "Allowlist entries that are no longer a live one-sided mismatch — the "
        "constraint now exists on both sides or on neither, so the exemption "
        f"is dead. Remove it: {dead}"
    )


def test_reverse_leg_flags_a_tables_only_orm_constraint_being_deleted():
    """Negative control for the reverse leg, with the managed-table set taken
    from ORM metadata rather than from the surviving constraint pairs (codex
    review on the #942 PR). Deleting the sole ``CheckConstraint`` on a
    one-check table — ``catalog.record_translations``, ``catalog.ingest_jobs``,
    and ``catalog.map_layers`` are all one-check today — must not make the
    table itself disappear from the comparison."""
    orm_tables = {"catalog.record_translations", "catalog.records"}
    # ORM side after the deletion: record_translations has no check left.
    orm_pairs = {("catalog.records", "chk_records_spatial_extent_type")}
    db_pairs = {
        ("catalog.records", "chk_records_spatial_extent_type"),
        ("catalog.record_translations", "chk_record_translations_lang"),
    }

    failures = _parity_failures(orm_pairs, db_pairs, orm_tables)

    assert failures["db_only"] == [
        ("catalog.record_translations", "chk_record_translations_lang")
    ]
    # Deriving the managed set from orm_pairs instead is what used to hide it.
    tables_from_pairs = {table for table, _ in orm_pairs}
    assert not _parity_failures(orm_pairs, db_pairs, tables_from_pairs)["db_only"]


def test_allowlist_entry_is_flagged_once_the_constraint_disappears():
    """A one-sided exemption whose constraint has since vanished from BOTH
    sides is dead and must be reported, or it silently pre-authorizes the same
    drift when that constraint is reintroduced (codex review on the #942 PR)."""
    exemption = ("catalog.records", "chk_gone")

    dead = _parity_failures(
        orm_pairs=set(),
        db_pairs=set(),
        orm_tables={"catalog.records"},
        orm_only_allowlist=frozenset({exemption}),
    )["dead_exemptions"]
    assert dead == [exemption]

    # Still one-sided (declared on the ORM, absent from the DB) → still live.
    live = _parity_failures(
        orm_pairs={exemption},
        db_pairs=set(),
        orm_tables={"catalog.records"},
        orm_only_allowlist=frozenset({exemption}),
    )
    assert not live["dead_exemptions"]
    assert not live["missing_in_db"]

    # Present on both sides → the exemption is dead the other way too.
    both = _parity_failures(
        orm_pairs={exemption},
        db_pairs={exemption},
        orm_tables={"catalog.records"},
        orm_only_allowlist=frozenset({exemption}),
    )
    assert both["dead_exemptions"] == [exemption]


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
