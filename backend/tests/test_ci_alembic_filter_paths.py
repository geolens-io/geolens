"""OCG-02: Alembic paths-filter guard test.

Parses the alembic filter list from .github/workflows/ci.yml and asserts:
1. Every glob in the alembic filter matches at least one real file on disk
   (dead-glob detection — the deleted ``backend/app/models/**`` would fail).
2. The dead glob ``backend/app/models/**`` is NOT present (regression guard).
3. At least one glob covers real model modules (e.g. backend/app/core/db/models.py
   or the backend/app/**/models.py family) so a model-only PR triggers alembic check.

These tests run locally (filesystem + YAML parse only; no Docker, no DB).
They are the locally-verifiable proof of the CI fix (OCG-02).

References: OCG-02
"""

from __future__ import annotations

import glob
import pathlib
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
CI_YML_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _parse_alembic_filter_globs() -> list[str]:
    """Return the list of path globs from the 'alembic' filter in ci.yml."""
    with CI_YML_PATH.open() as fh:
        ci: dict[str, Any] = yaml.safe_load(fh)

    # Navigate: jobs → changes → steps → uses dorny/paths-filter → with.filters
    changes_job = ci.get("jobs", {}).get("changes", {})
    steps: list[dict] = changes_job.get("steps", [])

    filter_step: dict | None = None
    for step in steps:
        if "dorny/paths-filter" in str(step.get("uses", "")):
            filter_step = step
            break

    assert filter_step is not None, (
        "Could not find the 'dorny/paths-filter' step in the changes job. "
        "If ci.yml structure changed, update this test's navigation logic."
    )

    filters_raw = filter_step.get("with", {}).get("filters", "")
    filters: dict[str, list[str]] = yaml.safe_load(filters_raw)

    alembic_globs: list[str] = filters.get("alembic", [])
    assert alembic_globs, "alembic filter is empty — expected at least one glob"
    return alembic_globs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAlembicFilterGlobs:
    """Guard tests for the alembic paths-filter globs in ci.yml."""

    def test_dead_glob_not_present(self):
        """backend/app/models/** must NOT be in the alembic filter.

        This directory was deleted in b63803c1. Its continued presence silently
        lets model-only PRs bypass the alembic drift check (OCG-02 root cause).
        """
        globs = _parse_alembic_filter_globs()
        dead = "backend/app/models/**"
        assert dead not in globs, (
            f"Dead glob '{dead}' is still in the alembic paths-filter. "
            f"Remove it — the directory backend/app/models/ does not exist. "
            f"Current globs: {globs}"
        )

    def test_every_glob_matches_at_least_one_real_file(self):
        """Every path glob in the alembic filter must match ≥1 existing file.

        A glob that matches nothing means no PR touching those files will trigger
        the alembic drift check — a silent CI gap (the original OCG-02 bug).
        """
        globs = _parse_alembic_filter_globs()
        missing: list[str] = []

        for pattern in globs:
            # Resolve relative to the repo root using glob.glob with recursive=True
            # (GitHub paths-filter uses pathlib-style ** wildcards).
            matches = glob.glob(str(REPO_ROOT / pattern), recursive=True)
            # Also try without the REPO_ROOT prefix for patterns that look like
            # shell globs with ** (glob.glob handles those with recursive=True).
            if not matches:
                missing.append(pattern)

        assert not missing, (
            "The following alembic filter globs match NO real files in the repo "
            "(dead globs — PRs touching only these paths skip alembic check):\n"
            + "\n".join(f"  - {g}" for g in missing)
            + f"\n\nAll globs: {globs}\nRepo root: {REPO_ROOT}"
        )

    def test_real_model_modules_are_covered(self):
        """At least one glob must cover the real model layout files.

        Asserts that the fixed globs (backend/app/**/models.py etc.) actually
        match a known model file so a model-only PR triggers the alembic job.
        """
        globs = _parse_alembic_filter_globs()

        # Check that at least one glob would match the canonical model path.
        canonical = pathlib.Path("backend/app/core/db/models.py")
        matched_by: list[str] = []
        for pattern in globs:
            if glob.glob(str(REPO_ROOT / pattern), recursive=True):
                # Check if this pattern's match-set includes the canonical path.
                full_matches = glob.glob(str(REPO_ROOT / pattern), recursive=True)
                canonical_abs = str(REPO_ROOT / canonical)
                if canonical_abs in full_matches:
                    matched_by.append(pattern)

        assert matched_by, (
            f"No alembic filter glob covers '{canonical}' — a model-only PR "
            f"touching this file would NOT trigger the alembic drift check. "
            f"Current globs: {globs}"
        )

    def test_alembic_migrations_dir_covered(self):
        """backend/alembic/** must still be in the filter.

        This is the core trigger for migration changes themselves.
        """
        globs = _parse_alembic_filter_globs()
        assert any("backend/alembic/**" in g for g in globs), (
            f"backend/alembic/** is missing from the alembic filter. "
            f"Current globs: {globs}"
        )
