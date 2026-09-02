"""DB-backed drift test: the frontend ISO metadata dropdown option lists must
be a subset of the records CHECK constraints they feed, as those constraints
are actually enforced by the migrated database.

fix(#1778): the ISO metadata dropdowns offer four values the records CHECK
constraint rejects, so picking them 500s the whole pending-edit batch.

  `frontend/src/lib/iso-constants.ts` declares `UPDATE_FREQUENCY_OPTIONS` and
  `SENSITIVITY_OPTIONS`, rendered directly as `<SelectItem>` options in
  `SourceQualityTab.tsx`. Nothing validates a selection before it reaches
  `PATCH /datasets/{id}` -- `_apply_simple_field_assignments` does a bare
  `setattr(target, attr, value)`, and the only handler in the datasets PATCH
  path catches `ValueError`, not `IntegrityError`. A value the CHECK
  constraint rejects (`update_frequency`/`sensitivity_classification` on
  `Record`) surfaces as an unfiltered 500, and `savePendingDrafts` discards
  the server detail and shows a generic "Failed to save pending edits."
  toast naming no field.

  Contract direction: frontend_options is a subset of constraint_values. The
  constraint may accept values the frontend never offers (e.g.
  `public`/`internal` were missing from the old SENSITIVITY_OPTIONS, which is
  a UX gap, not a 500) -- that is not what this guard checks.

fix(#1778): codex review (round 2 on the PR that added this file) found two
gaps in the first version:

1. The backend vocabulary was read off `Record.__table__` -- the ORM's
   *declared* `CheckConstraint`, not what deployed PostgreSQL actually
   enforces. Widening the ORM constraint while a migration is missing or
   wrong would keep both subset tests green while the migrated database
   still rejects the value. `test_check_constraint_parity.py` only compares
   (table, name) pairs, not expressions, and Alembic autogenerate does not
   detect CHECK-expression drift either -- nothing else closes this. Fixed
   by reading `pg_get_constraintdef(oid)` from `pg_constraint` against the
   migrated test database (the same `test_db_session` fixture
   `test_check_constraint_parity.py` uses) and deriving the vocabulary from
   that text instead of the ORM's.
2. The frontend option regex was letter-only (`[A-Za-z]+`), so a value
   containing an underscore, hyphen, or digit (e.g. `'as_needed'`) was
   silently absent from the parsed set rather than caught as a real,
   comparable value -- both the nonempty assertion and the subset checks
   stayed green. Fixed by extracting the complete quoted contents
   (`[^']+`), matching the pattern already used on the constraint side.

  Fail-before is provable two ways: add `'fortnightly'` back to
  `UPDATE_FREQUENCY_OPTIONS` (or `'secret'`/`'topSecret'`/`'unclassified'`
  back to `SENSITIVITY_OPTIONS`) in `iso-constants.ts`, or widen
  `chk_records_update_frequency` on the ORM model without touching the
  migration -- either fails a subset test, naming the offending value.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Record
from tests.repo_paths import repo_root

pytestmark = pytest.mark.anyio

REPO_ROOT = repo_root(__file__)
ISO_CONSTANTS_TS = REPO_ROOT / "frontend" / "src" / "lib" / "iso-constants.ts"

# Matches the complete contents of a single-quoted string, whatever
# characters it contains -- not a letter-only class. An ISO option or a
# CHECK constraint's literal can contain digits or camelCase, and a typo can
# contain an underscore or hyphen; all of those must be captured as a real
# value to compare, never silently dropped.
_QUOTED_VALUE_RE = re.compile(r"'([^']+)'")


def _extract_option_array(const_name: str, source: str) -> set[str]:
    """Parse `export const <const_name> = [...] as const;` out of `source`
    and return the complete contents of every quoted string in the array.

    Static analysis only -- does not import or execute TypeScript. Takes
    `source` as text rather than reading the file directly so a test can
    exercise the parser against a synthetic snippet.
    """
    match = re.search(
        rf"export\s+const\s+{const_name}\s*=\s*\[(.*?)\]\s*as\s+const",
        source,
        re.DOTALL,
    )
    assert match, (
        f"Could not find `export const {const_name} = [...] as const` in "
        f"the given source. The parser may be broken, or the constant was "
        f"renamed or moved."
    )
    values = set(_QUOTED_VALUE_RE.findall(match.group(1)))
    assert values, (
        f"Parsed zero values from {const_name}. The parser may have "
        f"stopped matching -- check the regex against the current source."
    )
    return values


def _parse_frontend_option_list(const_name: str) -> set[str]:
    """Parse a `export const <const_name> = [...] as const;` string array
    out of the real `iso-constants.ts` file."""
    source = ISO_CONSTANTS_TS.read_text(encoding="utf-8")
    return _extract_option_array(const_name, source)


async def _parse_migrated_check_constraint_values(
    session, table_fullname: str, constraint_name: str
) -> set[str]:
    """Return the quoted string literals in a named CHECK constraint's
    definition, read from the migrated test database rather than the ORM.

    `pg_get_constraintdef` returns what PostgreSQL actually enforces (it
    rewrites `IN (...)` to `= ANY (ARRAY[...])`, but the string literals
    themselves survive verbatim), so this reflects a migration that failed
    to land even when the ORM's `CheckConstraint` was already widened.
    """
    schema, table = table_fullname.split(".", 1)
    result = await session.execute(
        text(
            """
            SELECT pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE con.contype = 'c'
              AND nsp.nspname = :schema
              AND rel.relname = :table
              AND con.conname = :name
            """
        ),
        {"schema": schema, "table": table, "name": constraint_name},
    )
    row = result.first()
    assert row is not None, (
        f"No CHECK constraint named {constraint_name!r} found on "
        f"{table_fullname} in the migrated test database. Either the "
        f"migration is missing, or the table/constraint name changed -- "
        f"see test_check_constraint_parity.py for the ORM<->DB name gate."
    )
    values = set(_QUOTED_VALUE_RE.findall(row[0]))
    assert values, (
        f"Parsed zero values from {constraint_name}'s migrated CHECK "
        f"definition ({row[0]!r}). The parser may be broken -- fix this "
        f"test first."
    )
    return values


async def test_update_frequency_options_subset_of_check_constraint(test_db_session):
    """UPDATE_FREQUENCY_OPTIONS must be a subset of the migrated
    chk_records_update_frequency.

    An option outside the constraint's vocabulary passes frontend validation,
    reaches PATCH /datasets/{id}, and raises an unhandled CheckViolation that
    the global DBAPIError handler re-raises as a 500 (backend/app/api/main.py).
    """
    frontend = _parse_frontend_option_list("UPDATE_FREQUENCY_OPTIONS")
    backend = await _parse_migrated_check_constraint_values(
        test_db_session, Record.__table__.fullname, "chk_records_update_frequency"
    )

    only_in_frontend = frontend - backend

    assert not only_in_frontend, (
        f"iso-constants.ts UPDATE_FREQUENCY_OPTIONS offers a value the "
        f"migrated chk_records_update_frequency rejects (500 on save):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: remove the value from UPDATE_FREQUENCY_OPTIONS in "
        f"frontend/src/lib/iso-constants.ts, or widen the CHECK constraint "
        f"in backend/app/modules/catalog/datasets/domain/models.py with a "
        f"matching Alembic migration."
    )


async def test_sensitivity_options_subset_of_check_constraint(test_db_session):
    """SENSITIVITY_OPTIONS must be a subset of the migrated
    chk_records_sensitivity.

    An option outside the constraint's vocabulary passes frontend validation,
    reaches PATCH /datasets/{id}, and raises an unhandled CheckViolation that
    the global DBAPIError handler re-raises as a 500 (backend/app/api/main.py).
    """
    frontend = _parse_frontend_option_list("SENSITIVITY_OPTIONS")
    backend = await _parse_migrated_check_constraint_values(
        test_db_session, Record.__table__.fullname, "chk_records_sensitivity"
    )

    only_in_frontend = frontend - backend

    assert not only_in_frontend, (
        f"iso-constants.ts SENSITIVITY_OPTIONS offers a value the migrated "
        f"chk_records_sensitivity rejects (500 on save):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: remove the value from SENSITIVITY_OPTIONS in "
        f"frontend/src/lib/iso-constants.ts, or widen the CHECK constraint "
        f"in backend/app/modules/catalog/datasets/domain/models.py with a "
        f"matching Alembic migration."
    )


def test_extract_option_array_does_not_silently_drop_non_letter_values():
    """Negative control for the old `[A-Za-z]+` class: a synthetic option
    containing an underscore must be captured as a real value, not silently
    erased from the parsed set.

    `'as_needed'` is deliberately not `'asNeeded'` (the real, valid
    UPDATE_FREQUENCY_OPTIONS/registry spelling) -- it stands in for the bug
    class the letter-only regex missed: a typo'd or foreign value that
    should show up as a violation, not vanish before the comparison runs.
    """
    synthetic_source = (
        "export const FAKE_OPTIONS = [\n"
        "  'continual',\n"
        "  'as_needed',\n"
        "  'unknown',\n"
        "] as const;\n"
    )

    parsed = _extract_option_array("FAKE_OPTIONS", synthetic_source)

    assert parsed == {"continual", "as_needed", "unknown"}, (
        f"Expected the synthetic array's three literal values, underscore "
        f"included, to all survive parsing; got {sorted(parsed)}"
    )

    # The real vocabulary spells this option 'asNeeded' (camelCase), so the
    # synthetic 'as_needed' must land as a genuine, reportable mismatch
    # against it -- not silently absent from `parsed` before this comparison
    # ever runs.
    real_update_frequency_vocabulary = {
        "continual",
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "biannually",
        "annually",
        "asNeeded",
        "irregular",
        "notPlanned",
        "unknown",
    }
    only_in_synthetic = parsed - real_update_frequency_vocabulary
    assert only_in_synthetic == {"as_needed"}, (
        f"Expected 'as_needed' to be caught as the sole value outside the "
        f"real vocabulary; got {sorted(only_in_synthetic)}"
    )
