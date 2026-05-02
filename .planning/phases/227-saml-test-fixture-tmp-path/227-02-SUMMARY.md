---
phase: 227-saml-test-fixture-tmp-path
plan: 02
subsystem: testing
tags: [pytest, saml, fixture-hygiene, test-infra, ci, tmp_path_factory]

# Dependency graph
requires:
  - phase: 227-01
    provides: "generate_fixtures.main(output_dir) parameter — Plan 02 calls it in-process"
provides:
  - "5 idp_response_*.xml.b64 renamed to .xml.b64.template via git mv (R100, pure rename)"
  - "saml_response_dir session fixture in test_saml_overlay.py routing generator output to tmp_path_factory"
  - "_load_fixture_b64(name, response_dir) with template fallback: response_dir first, FIXTURE_DIR/*.template second"
  - "CI guard step 'Verify SAML fixtures unchanged after pytest' in ci.yml backend-test job"
  - "Wave 0 unit test test_load_fixture_b64_falls_back_to_template (TESTFIX-03 fallback semantic)"
  - "git diff --quiet -- backend/tests/fixtures/saml/ exits 0 after full pytest run"
affects:
  - "227-03 (phase close — all 3 TESTFIX requirements now satisfied)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "tmp_path_factory.mktemp session fixture for generator output (first use in this repo)"
    - "In-process generator import inside try/except (ImportError, OSError) with stderr diagnostic"
    - "Template-fallback resolution: response_dir / name first, FIXTURE_DIR / f'{name}.template' second"
    - "CI git diff --quiet guard with ::error:: annotation pointing to phase by name"

key-files:
  created: []
  modified:
    - backend/tests/fixtures/saml/idp_response_signed.xml.b64.template
    - backend/tests/fixtures/saml/idp_response_expired.xml.b64.template
    - backend/tests/fixtures/saml/idp_response_replay.xml.b64.template
    - backend/tests/fixtures/saml/idp_response_unsigned.xml.b64.template
    - backend/tests/fixtures/saml/idp_response_xsw.xml.b64.template
    - backend/tests/test_saml_overlay.py
    - .github/workflows/ci.yml

key-decisions:
  - "Rename 5 .xml.b64 files to .xml.b64.template via git mv — preserves history, R100 pure rename, committed templates serve as deterministic CI fallback"
  - "saml_response_dir is request-scoped (NOT autouse) so non-SAML test runs skip the generator startup cost"
  - "except (ImportError, OSError) only — subprocess.CalledProcessError not needed in in-process path"
  - "Pathspec in CI step is tests/fixtures/saml/ (relative to backend/) matching job-level working-directory default"
  - "Wave 0 test uses tmp_path (empty dir) to assert template-fallback branch — explicit regression guard for TESTFIX-03"

patterns-established:
  - "tmp_path_factory.mktemp('saml_responses') for session-scoped generator output dirs"
  - "In-process fixture generator import: from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures"
  - "CI fixture-cleanliness guard: git diff --quiet -- <relative-pathspec> after pytest with ::error:: annotation on failure"

requirements-completed:
  - TESTFIX-01
  - TESTFIX-02
  - TESTFIX-03

# Metrics
duration: 25min
completed: 2026-05-02
---

# Phase 227 Plan 02: full hygiene refactor Summary

**Stopped SAML fixture in-place mutation: renamed 5 .xml.b64 to .xml.b64.template, swapped autouse for saml_response_dir session fixture writing to tmp_path_factory, rewrote _load_fixture_b64 with template fallback, migrated 9 callsites, added CI guard; git diff --quiet on backend/tests/fixtures/saml/ exits 0 after a full SAML pytest run**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-02T02:36:31Z
- **Completed:** 2026-05-02T02:44:30Z
- **Tasks:** 3
- **Files modified:** 7 (5 fixture renames + test file + ci.yml)

## Accomplishments

- Renamed 5 `idp_response_*.xml.b64` → `idp_response_*.xml.b64.template` via `git mv` (R100 pure renames, history preserved, no content edits)
- Deleted `_regenerate_saml_fixtures` autouse (36 lines removed including `subprocess.run` and its swallowed `CalledProcessError`)
- Added `saml_response_dir` session fixture writing to `tmp_path_factory.mktemp("saml_responses")` with in-process generator call and `try/except (ImportError, OSError)` fallback diagnostic
- Rewrote `_load_fixture_b64(name, response_dir)` with template-fallback resolution: tries `response_dir / name` first, reads `FIXTURE_DIR / f"{name}.template"` on miss
- Migrated all 9 `_load_fixture_b64` callsites to 2-arg form and added `saml_response_dir` to 8 enclosing function signatures
- Added Wave 0 unit test `test_load_fixture_b64_falls_back_to_template` using empty `tmp_path` to assert the fallback path
- Inserted CI guard step `Verify SAML fixtures unchanged after pytest` in `ci.yml` `backend-test` job between `Run tests with coverage` and `Upload backend coverage report`; pathspec uses `tests/fixtures/saml/` (relative to `backend/` per job-level `working-directory` default)
- All 19 SAML tests pass; `git diff --quiet -- backend/tests/fixtures/saml/` exits 0 immediately after a full `pytest tests/test_saml_overlay.py` run

## Task Commits

1. **Task 01: git mv 5 fixture files to .xml.b64.template** — `7102c416` (refactor)
2. **Task 02: Swap autouse, rewrite helper, migrate callsites, add Wave 0 test** — `81172a52` (refactor)
3. **Task 03: Add CI guard step** — `7b03e573` (ci)

## Files Created/Modified

- `backend/tests/fixtures/saml/idp_response_signed.xml.b64.template` — renamed from `.xml.b64` (pure rename, R100)
- `backend/tests/fixtures/saml/idp_response_expired.xml.b64.template` — renamed from `.xml.b64` (pure rename, R100)
- `backend/tests/fixtures/saml/idp_response_replay.xml.b64.template` — renamed from `.xml.b64` (pure rename, R100)
- `backend/tests/fixtures/saml/idp_response_unsigned.xml.b64.template` — renamed from `.xml.b64` (pure rename, R100)
- `backend/tests/fixtures/saml/idp_response_xsw.xml.b64.template` — renamed from `.xml.b64` (pure rename, R100)
- `backend/tests/test_saml_overlay.py` — module docstring rewritten; `import sys` added; autouse deleted; `saml_response_dir` fixture added; `_load_fixture_b64` rewritten with 2-arg signature + template fallback; `test_load_fixture_b64_falls_back_to_template` Wave 0 test added; 8 function signatures + 9 callsites migrated
- `.github/workflows/ci.yml` — CI guard step inserted between `Run tests with coverage` and `Upload backend coverage report`

## Decisions Made

- Combined fixture-rename commit (Task 01) and helper-rewrite commit (Task 02) as separate commits per D-10 ordering — bisect-friendly granularity
- `saml_response_dir` placed in `test_saml_overlay.py` (not `conftest.py`) — only this file reads these fixtures; co-location keeps blast radius zero and avoids pysaml2 import on non-SAML test runs
- `except (ImportError, OSError)` only — `subprocess.CalledProcessError` not included because `subprocess.run` is gone from the in-process path (D-05 rationale from CONTEXT.md)
- CI pathspec `tests/fixtures/saml/` (relative) not `backend/tests/fixtures/saml/` (absolute) — Pitfall 1 from RESEARCH.md: job inherits `defaults.run.working-directory: backend`

## Deviations from Plan

None — plan executed exactly as written.

Minor note: the plan's acceptance criterion `grep -c 'FIXTURE_DIR / f"{name}.template"' backend/tests/test_saml_overlay.py` returns `1` — we return `2` because the Wave 0 test's docstring at line 169 also contains this string (as a backtick-quoted rst reference). The code implementation is correct (one execution path in the helper body, one assertion in the test). No functional deviation.

## Verification Evidence (TESTFIX-01, TESTFIX-02, TESTFIX-03)

**TESTFIX-01** (generator output routed to tmp_path):
- `grep -c "def saml_response_dir(tmp_path_factory)" backend/tests/test_saml_overlay.py` → 1
- `grep -c "def _regenerate_saml_fixtures" backend/tests/test_saml_overlay.py` → 0
- `grep -c "subprocess" backend/tests/test_saml_overlay.py` → 0
- `grep -c "autouse=True" backend/tests/test_saml_overlay.py` → 0

**TESTFIX-02** (`git status` clean after pytest):
- `cd backend && uv run pytest tests/test_saml_overlay.py -v` → 19 passed
- `git diff --quiet -- backend/tests/fixtures/saml/` → exits 0 (CLEAN)
- CI step `Verify SAML fixtures unchanged after pytest` present in `ci.yml` at line 342

**TESTFIX-03** (rename + fallback + docstring):
- `git ls-files backend/tests/fixtures/saml/ | grep -cE '\.xml\.b64$'` → 0 (no .xml.b64 without .template)
- `git ls-files backend/tests/fixtures/saml/ | grep -cE '\.xml\.b64\.template$'` → 5
- `grep -c 'def _load_fixture_b64(name: str, response_dir: Path) -> str:' ...` → 1
- `uv run pytest tests/test_saml_overlay.py::test_load_fixture_b64_falls_back_to_template -v` → PASSED
- Module docstring updated to describe the new (working) fallback behavior; factually-wrong "gitignored from the worktree's perspective" handwave is gone

## Known Stubs

None.

## Threat Flags

None — production code untouched. No new network endpoints, auth paths, or schema changes. Test infrastructure refactor only.

## Issues Encountered

None.

## Next Phase Readiness

- All 3 phase requirements satisfied (TESTFIX-01, TESTFIX-02, TESTFIX-03)
- Phase 227 is the last plan — phase close can proceed
- Manual-only verification (deliberately break the autouse on a temp branch, push to draft PR, observe CI failure) is deferred per VALIDATION.md "Manual-Only Verifications" — not a blocker for phase close

---
*Phase: 227-saml-test-fixture-tmp-path*
*Completed: 2026-05-02*
