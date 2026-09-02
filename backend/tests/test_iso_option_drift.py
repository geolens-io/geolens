"""Static-analysis test: the frontend ISO metadata dropdown option lists must
be a subset of the records CHECK constraints they feed.

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

  Contract direction: frontend_options ⊆ constraint_values. The constraint
  may accept values the frontend never offers (e.g. `public`/`internal` were
  missing from the old SENSITIVITY_OPTIONS, which is a UX gap, not a 500) --
  that is not what this guard checks.

  Fail-before is provable: add `'fortnightly'` back to
  `UPDATE_FREQUENCY_OPTIONS` (or `'secret'`/`'topSecret'`/`'unclassified'`
  back to `SENSITIVITY_OPTIONS`) in `iso-constants.ts` and this test fails,
  naming the offending value.
"""

from __future__ import annotations

import re

from app.modules.catalog.datasets.domain.models import Record
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
ISO_CONSTANTS_TS = REPO_ROOT / "frontend" / "src" / "lib" / "iso-constants.ts"


def _parse_frontend_option_list(const_name: str) -> set[str]:
    """Parse a `export const <const_name> = [...] as const;` string array.

    Static analysis only -- does not import or execute TypeScript.
    """
    source = ISO_CONSTANTS_TS.read_text(encoding="utf-8")
    match = re.search(
        rf"export\s+const\s+{const_name}\s*=\s*\[(.*?)\]\s*as\s+const",
        source,
        re.DOTALL,
    )
    assert match, (
        f"Could not find `export const {const_name} = [...] as const` in "
        f"{ISO_CONSTANTS_TS}. The parser may be broken, or the constant was "
        f"renamed or moved."
    )
    body = match.group(1)
    values = set(re.findall(r"'([A-Za-z]+)'", body))
    assert values, (
        f"Parsed zero values from {const_name} in {ISO_CONSTANTS_TS}. "
        f"The parser may have stopped matching -- check the regex against "
        f"the current source."
    )
    return values


def _parse_check_constraint_values(constraint_name: str) -> set[str]:
    """Parse the quoted string literals out of a named CHECK constraint on
    `Record.__table__`."""
    constraint = next(
        c for c in Record.__table__.constraints if c.name == constraint_name
    )
    values = set(re.findall(r"'([^']+)'", str(constraint.sqltext)))
    assert values, (
        f"Parsed zero values from {constraint_name}'s CHECK clause. "
        f"The parser may be broken -- fix this test first."
    )
    return values


def test_update_frequency_options_subset_of_check_constraint():
    """UPDATE_FREQUENCY_OPTIONS must be a subset of chk_records_update_frequency.

    An option outside the constraint's vocabulary passes frontend validation,
    reaches PATCH /datasets/{id}, and raises an unhandled CheckViolation that
    the global DBAPIError handler re-raises as a 500 (backend/app/api/main.py).
    """
    frontend = _parse_frontend_option_list("UPDATE_FREQUENCY_OPTIONS")
    backend = _parse_check_constraint_values("chk_records_update_frequency")

    only_in_frontend = frontend - backend

    assert not only_in_frontend, (
        f"iso-constants.ts UPDATE_FREQUENCY_OPTIONS offers a value "
        f"chk_records_update_frequency rejects (500 on save):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: remove the value from UPDATE_FREQUENCY_OPTIONS in "
        f"frontend/src/lib/iso-constants.ts, or widen the CHECK constraint "
        f"in backend/app/modules/catalog/datasets/domain/models.py (with a "
        f"matching Alembic migration)."
    )


def test_sensitivity_options_subset_of_check_constraint():
    """SENSITIVITY_OPTIONS must be a subset of chk_records_sensitivity.

    An option outside the constraint's vocabulary passes frontend validation,
    reaches PATCH /datasets/{id}, and raises an unhandled CheckViolation that
    the global DBAPIError handler re-raises as a 500 (backend/app/api/main.py).
    """
    frontend = _parse_frontend_option_list("SENSITIVITY_OPTIONS")
    backend = _parse_check_constraint_values("chk_records_sensitivity")

    only_in_frontend = frontend - backend

    assert not only_in_frontend, (
        f"iso-constants.ts SENSITIVITY_OPTIONS offers a value "
        f"chk_records_sensitivity rejects (500 on save):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: remove the value from SENSITIVITY_OPTIONS in "
        f"frontend/src/lib/iso-constants.ts, or widen the CHECK constraint "
        f"in backend/app/modules/catalog/datasets/domain/models.py (with a "
        f"matching Alembic migration)."
    )
