"""OCG-02: ci.yml paths-filter guard tests.

Parses the alembic filter list from .github/workflows/ci.yml and asserts:
1. Every glob in the alembic filter matches at least one real file on disk
   (dead-glob detection — the deleted ``backend/app/models/**`` would fail).
2. The dead glob ``backend/app/models/**`` is NOT present (regression guard).
3. At least one glob covers real model modules (e.g. backend/app/core/db/models.py
   or the backend/app/**/models.py family) so a model-only PR triggers alembic check.

It also guards the ``backend`` filter (fix(#1088)): every ``scripts/`` file a
backend test reads by literal path must be in that filter, or the suite that
asserts against the file skips on the very PR that changes it.

fix(#1778): the currency check above only scanned for
``scripts/...`` literals — it had no ``frontend/...`` or ``e2e/...`` half, so
several frontend files and one e2e spec that backend cross-language/parity
tests read by literal path drifted out of the ``backend`` filter with nothing
noticing. Both halves now share one scanner (``_referenced_by_backend_tests``)
parameterized by pattern.

These tests run locally (filesystem + YAML parse only; no Docker, no DB).
They are the locally-verifiable proof of the CI fix (OCG-02).

References: OCG-02, #1088
"""

from __future__ import annotations

import glob
import pathlib
import re
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
CI_YML_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _parse_filter_globs(filter_name: str) -> list[str]:
    """Return the list of path globs from a named paths-filter in ci.yml."""
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

    globs: list[str] = filters.get(filter_name, [])
    assert globs, f"{filter_name} filter is empty — expected at least one glob"
    return globs


def _parse_alembic_filter_globs() -> list[str]:
    """Return the list of path globs from the 'alembic' filter in ci.yml."""
    return _parse_filter_globs("alembic")


def _referenced_by_backend_tests(pattern: re.Pattern[str]) -> dict[str, list[str]]:
    """Map each path matching *pattern* that a backend test names to the tests
    naming it.

    Literal-path reads only. A test that shells out to (or imports) a path it
    never names is invisible here, which is the limit of this guard, not a
    reason to skip it.
    """
    found: dict[str, list[str]] = {}
    tests_dir = REPO_ROOT / "backend" / "tests"
    for path in sorted(tests_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".sh"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        for ref in set(pattern.findall(text)):
            if (REPO_ROOT / ref).is_file():
                found.setdefault(ref, []).append(path.name)
    return found


_SCRIPTS_PATTERN = re.compile(r"scripts/[A-Za-z0-9_./-]+\.(?:sh|py|yml|yaml)")

# fix(#1778): ``tsx`` MUST precede ``ts`` in the
# extension alternation. The greedy path class backtracks into whichever
# alternative matches first, so ``ts`` before ``tsx`` silently resolves
# ``AuditLogViewer.tsx`` to the nonexistent ``AuditLogViewer.ts`` — the
# ``is_file()`` check below then drops it, which is exactly how this file
# went uncovered by the scanner (and the filter) for as long as it did.
_FRONTEND_PATTERN = re.compile(
    r"(?:frontend|e2e)/[A-Za-z0-9_./-]+\.(?:tsx|ts|json|conf|js|html|md)"
)


def _scripts_referenced_by_backend_tests() -> dict[str, list[str]]:
    """Map each ``scripts/`` path a backend test names to the tests naming it."""
    return _referenced_by_backend_tests(_SCRIPTS_PATTERN)


def _frontend_referenced_by_backend_tests() -> dict[str, list[str]]:
    """Map each ``frontend/``/``e2e/`` path a backend test names to the tests
    naming it."""
    return _referenced_by_backend_tests(_FRONTEND_PATTERN)


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

    def test_clean_db_boot_inputs_are_covered(self):
        """Every script bind-mounted by the clean-DB smoke must trigger it."""
        globs = _parse_alembic_filter_globs()

        for required in (
            "backend/scripts/test_alembic_upgrade_clean_db.sh",
            "scripts/init-db.sh",
            "scripts/lib/configure-runtime-db-role.sh",
        ):
            assert required in globs, (
                f"{required} is missing from the alembic filter, so a change "
                f"to a clean-DB boot input can skip the smoke. Current globs: {globs}"
            )


class TestPullRequestDiffBase:
    """fix(#1094): the PR diff base must not be the stale pull_request.base.sha."""

    def _changes_steps(self) -> list[dict]:
        with CI_YML_PATH.open() as fh:
            ci: dict[str, Any] = yaml.safe_load(fh)
        return ci["jobs"]["changes"]["steps"]

    def test_paths_filter_is_given_an_explicit_base(self):
        """Without a `base` input the action uses pull_request.base.sha.

        That value is frozen when the PR is opened, while GitHub rebuilds the
        refs/pull/N/merge ref every time main moves, so the diff silently grows
        to include everything that landed in between. #1027 changed 4 files and
        its filter reported 117, which switched Backend Tests on for unrelated
        backend/** work and made a green job say nothing about the PR.
        """
        steps = self._changes_steps()
        filter_step = next(
            (s for s in steps if "dorny/paths-filter" in str(s.get("uses", ""))),
            None,
        )
        assert filter_step is not None, "paths-filter step not found in changes job"

        base = str(filter_step.get("with", {}).get("base", "")).strip()
        assert base, (
            "The paths-filter step has no 'base' input, so it falls back to the "
            "stale pull_request.base.sha and a PR's filter diff grows as main "
            "moves underneath it. See #1094."
        )

        producer_ids = {str(s.get("id", "")) for s in steps if s.get("id")}
        referenced = re.findall(r"steps\.([A-Za-z0-9_-]+)\.outputs", base)
        assert referenced, (
            f"'base' should come from a step output that resolves a merge base; "
            f"got {base!r}."
        )
        missing = [r for r in referenced if r not in producer_ids]
        assert not missing, (
            f"'base' references step id(s) {missing} that do not exist in the "
            f"changes job. Known ids: {sorted(producer_ids)}"
        )

    def test_diff_base_is_resolved_from_the_merge_ref_parent(self):
        """The resolver must derive the base from the merge ref, not the payload.

        Reading github.event.pull_request.base.sha back out of the payload would
        reintroduce #1094 with extra steps.
        """
        steps = self._changes_steps()
        resolver = next(
            (s for s in steps if str(s.get("id", "")) == "diffbase"),
            None,
        )
        assert resolver is not None, (
            "No step with id 'diffbase' in the changes job. Something removed "
            "the #1094 base resolver."
        )
        script = str(resolver.get("run", ""))
        assert "HEAD^1" in script, (
            "The diff-base resolver no longer reads the merge ref's first "
            f"parent. Script was:\n{script}"
        )
        assert "base.sha" not in script.replace(" ", ""), (
            "The diff-base resolver reads pull_request.base.sha, which is the "
            "stale value #1094 exists to stop using."
        )


class TestBackendFilterCoversReferencedScripts:
    """fix(#1088): guard the backend filter against the skipped-suite trap."""

    def test_every_backend_glob_matches_at_least_one_real_file(self):
        """No dead globs in the backend filter.

        Caught a real one while #1088 was being written: two backend/scripts/
        entrypoints were added here as 'scripts/...' paths, which match nothing
        (backend/** already covers them). A dead glob is silent — it neither
        triggers the job nor reports an error.
        """
        globs = _parse_filter_globs("backend")
        missing = [
            g for g in globs if not glob.glob(str(REPO_ROOT / g), recursive=True)
        ]
        assert not missing, (
            "These globs in the 'backend' paths-filter match NO real files:\n"
            + "\n".join(f"  - {g}" for g in missing)
        )

    def test_scripts_read_by_backend_tests_are_in_the_backend_filter(self):
        """Every scripts/ file a backend test reads must trigger Backend Tests.

        #1027 changed scripts/backup-entrypoint.sh. The backup filter covered
        the script, so Backup Restore Round-trip ran and passed; the backend
        filter did not, so test_backup_staging_tar_skew.py — the test written
        to catch exactly that breakage — was skipped on the PR that broke it.
        A skipped required job reads as green, which is how the PR looked
        ready to merge.
        """
        referenced = _scripts_referenced_by_backend_tests()
        assert referenced, (
            "Found no scripts/ references in backend/tests — the scan is "
            "probably broken, since several tests read them by literal path."
        )

        globs = _parse_filter_globs("backend")
        covered: set[str] = set()
        for pattern in globs:
            for match in glob.glob(str(REPO_ROOT / pattern), recursive=True):
                covered.add(str(pathlib.Path(match).relative_to(REPO_ROOT)))

        uncovered = {
            ref: tests for ref, tests in referenced.items() if ref not in covered
        }
        assert not uncovered, (
            "These scripts/ files are read by backend tests but are NOT in the "
            "'backend' paths-filter in .github/workflows/ci.yml. A PR changing "
            "only one of them skips Backend Tests, so the test that asserts "
            "against it never runs:\n"
            + "\n".join(
                f"  - {ref}  (read by {', '.join(sorted(tests))})"
                for ref, tests in sorted(uncovered.items())
            )
            + "\n\nAdd each path to the 'backend' filter."
        )

    def test_frontend_or_e2e_paths_read_by_backend_tests_are_in_the_backend_filter(
        self,
    ):
        """Every frontend/ or e2e/ file a backend test reads must trigger
        Backend Tests.

        fix(#1778): the currency check above only had a
        scripts/ half. Several frontend files and one e2e spec that backend
        cross-language/parity tests read by literal path — most notably
        frontend/src/components/admin/AuditLogViewer.tsx, which
        test_audit_action_registry.py's bidirectional audit-action parity
        gate reads — were absent from the 'backend' filter with nothing
        checking for it. A PR editing only that file matched the 'frontend'
        filter but not 'backend', so Backend Tests skipped and the parity
        gate never ran. Same "skipped required job reads as green" trap as
        the scripts/ test above.
        """
        referenced = _frontend_referenced_by_backend_tests()
        assert referenced, (
            "Found no frontend/ or e2e/ references in backend/tests — the "
            "scan is probably broken, since several tests read them by "
            "literal path."
        )

        globs = _parse_filter_globs("backend")
        covered: set[str] = set()
        for pattern in globs:
            for match in glob.glob(str(REPO_ROOT / pattern), recursive=True):
                covered.add(str(pathlib.Path(match).relative_to(REPO_ROOT)))

        uncovered = {
            ref: tests for ref, tests in referenced.items() if ref not in covered
        }
        assert not uncovered, (
            "These frontend/ or e2e/ files are read by backend tests but are "
            "NOT in the 'backend' paths-filter in .github/workflows/ci.yml. A "
            "PR changing only one of them skips Backend Tests, so the test "
            "that asserts against it never runs:\n"
            + "\n".join(
                f"  - {ref}  (read by {', '.join(sorted(tests))})"
                for ref, tests in sorted(uncovered.items())
            )
            + "\n\nAdd each path to the 'backend' filter."
        )
