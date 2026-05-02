---
phase: 227-saml-test-fixture-tmp-path
slug: saml-test-fixture-tmp-path
verified: 2026-05-01T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
requirements_coverage:
  TESTFIX-01: satisfied
  TESTFIX-02: satisfied
  TESTFIX-03: satisfied
---

# Phase 227: saml-test-fixture-tmp-path Verification Report

**Phase Goal:** Stop the committed SAML fixture files from being rewritten on every `pytest` run. Refactor the session-scoped `_regenerate_saml_fixtures` autouse fixture in `backend/tests/test_saml_overlay.py` so the signed XML responses land in a pytest `tmp_path` for the test session instead of mutating `backend/tests/fixtures/saml/idp_response_*.xml.b64`. Rename the committed fixtures to `.xml.b64.template` (immutable templates) or remove them entirely; resolve the docstring's "CI fallback when pysaml2 unavailable" claim by either restoring it for real or deleting the claim.
**Verified:** 2026-05-01T00:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `git status` is clean after a full `pytest backend/tests/test_saml_overlay.py` run; CI step asserts fixture cleanliness post-pytest | ✓ VERIFIED | `pytest tests/test_saml_overlay.py -v` ran green (19 passed); `git status --porcelain backend/tests/fixtures/saml/` returned empty; CI uses `git status --porcelain -- tests/fixtures/saml/` (stronger than `git diff --quiet` per WR-02 fix at commit b5700992) |
| 2 | `_regenerate_saml_fixtures` is gone; `saml_response_dir` session fixture writes to `tmp_path_factory.mktemp("saml_responses")`; no test path writes into tracked fixtures dir | ✓ VERIFIED | `grep -c "_regenerate_saml_fixtures" test_saml_overlay.py` → 0; `grep -c "saml_response_dir" test_saml_overlay.py` → 19; `grep -c "tmp_path_factory" test_saml_overlay.py` → 4; `grep -c "subprocess" test_saml_overlay.py` → 0; `grep -c "autouse=True" test_saml_overlay.py` → 0 |
| 3 | The 5 `idp_response_*.xml.b64` files are renamed to `.xml.b64.template`; `_load_fixture_b64(name, response_dir)` reads regenerated first, falls back to template; Wave 0 test `test_load_fixture_b64_falls_back_to_template` exists | ✓ VERIFIED | `git ls-files backend/tests/fixtures/saml/ | grep -cE '\.xml\.b64$'` → 0; `git ls-files backend/tests/fixtures/saml/ | grep -cE '\.xml\.b64\.template$'` → 5; helper signature `def _load_fixture_b64(name: str, response_dir: Path) -> str:` confirmed; fallback path `FIXTURE_DIR / f"{name}.template"` confirmed in body; `test_load_fixture_b64_falls_back_to_template` exists and passes |
| 4 | Existing SAML overlay tests continue to pass — `pytest backend/tests/test_saml_overlay.py -v` is green | ✓ VERIFIED | Ran locally: 19 passed in 6.45s; this is 18 original + 1 new Wave 0 test |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/tests/fixtures/saml/generate_fixtures.py` | `main(output_dir: Path \| None = None)` parameter; 6 `target /` references replacing all `HERE /` in `main()` | ✓ VERIFIED | Signature confirmed at line 291; `target = output_dir if output_dir is not None else HERE` at line 300; all 6 `target / "idp_response_*"` references confirmed (5 write_bytes + 2 shutil.copyfile args); `main()` with no args defaults to `HERE` |
| `backend/tests/fixtures/saml/idp_response_signed.xml.b64.template` | Renamed template fixture | ✓ VERIFIED | Present in `git ls-files`; commit 7102c416 shows R100 pure rename |
| `backend/tests/fixtures/saml/idp_response_expired.xml.b64.template` | Renamed template fixture | ✓ VERIFIED | Present in `git ls-files`; R100 pure rename confirmed |
| `backend/tests/fixtures/saml/idp_response_replay.xml.b64.template` | Renamed template fixture | ✓ VERIFIED | Present in `git ls-files`; R100 pure rename confirmed |
| `backend/tests/fixtures/saml/idp_response_unsigned.xml.b64.template` | Renamed template fixture | ✓ VERIFIED | Present in `git ls-files`; R100 pure rename confirmed |
| `backend/tests/fixtures/saml/idp_response_xsw.xml.b64.template` | Renamed template fixture | ✓ VERIFIED | Present in `git ls-files`; R100 pure rename confirmed |
| `backend/tests/test_saml_overlay.py` | `saml_response_dir` session fixture; refactored `_load_fixture_b64(name, response_dir)`; 8 migrated function signatures; 9 migrated callsites; Wave 0 test; deleted autouse | ✓ VERIFIED | All confirmed by grep counts; 19 tests pass |
| `.github/workflows/ci.yml` | CI guard step "Verify SAML fixtures unchanged after pytest" in `backend-test` job between `Run tests with coverage` and `Upload backend coverage report` | ✓ VERIFIED | Step at line 342 (Run tests at 332, guard at 342, Upload at 357 — ordering correct); uses `git status --porcelain -- tests/fixtures/saml/` (relative to `backend/` per job-level `working-directory`); YAML structure valid |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `saml_response_dir` fixture | `generate_fixtures.main(output_dir=session_dir)` | in-process import inside `try/except Exception` | ✓ WIRED | Import `from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures` at lines 72-74; `generate_saml_fixtures(output_dir=session_dir)` at line 75; exception handling at line 76 uses `except Exception` (WR-01 fix) |
| `_load_fixture_b64(name, response_dir)` | `FIXTURE_DIR / f"{name}.template"` fallback | `if regenerated.exists()` branch in helper body | ✓ WIRED | Confirmed at lines 167-171 of `test_saml_overlay.py`; `response_dir / name` checked first, `FIXTURE_DIR / f"{name}.template"` as fallback |
| `.github/workflows/ci.yml` `backend-test` job | `git status --porcelain -- tests/fixtures/saml/` post-pytest | Shell step inserted between Run tests and Upload coverage | ✓ WIRED | `DIRTY=$(git status --porcelain -- tests/fixtures/saml/)` at line 348; pathspec relative to `backend/` (correct per job `working-directory` default); `::error::` annotation with phase-227 reference at line 350 |

### Data-Flow Trace (Level 4)

Not applicable — this phase contains no UI components or API endpoints that render dynamic data. All artifacts are test infrastructure (pytest fixtures, CI config). The data flow is: `generate_fixtures.main(output_dir=session_dir)` writes to `tmp_path_factory.mktemp("saml_responses")` → `_load_fixture_b64("name", saml_response_dir)` reads from session dir → test POSTs fixture data to SAML ACS endpoint → assertion verified. Verified that no write path touches `backend/tests/fixtures/saml/` during test sessions.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full SAML test suite passes (19 tests) | `cd backend && uv run pytest tests/test_saml_overlay.py -v --tb=short` | 19 passed in 6.45s | ✓ PASS |
| Fixtures dir clean after pytest run | `git status --porcelain backend/tests/fixtures/saml/` after pytest | Empty output | ✓ PASS |
| No .xml.b64 files tracked (only .xml.b64.template) | `git ls-files backend/tests/fixtures/saml/ | grep -cE '\.xml\.b64$'` | 0 | ✓ PASS |
| 5 .xml.b64.template files tracked | `git ls-files backend/tests/fixtures/saml/ | grep -cE '\.xml\.b64\.template$'` | 5 | ✓ PASS |
| Old autouse completely removed | `grep -c "_regenerate_saml_fixtures" test_saml_overlay.py` | 0 | ✓ PASS |
| All 9 callsites migrated to 2-arg form | `grep -cE '_load_fixture_b64\("idp_response_[a-z_]+\.xml\.b64", saml_response_dir\)' test_saml_overlay.py` | 9 | ✓ PASS |
| Wave 0 fallback test exists | `grep -c "def test_load_fixture_b64_falls_back_to_template" test_saml_overlay.py` | 1 | ✓ PASS |
| CI step in correct position | `awk` line-number check on step ordering | Run tests (332) < Guard (342) < Upload (357) | ✓ PASS |
| Rename commits are R100 pure renames | `git log --summary 7102c416` | 5 R100 renames, 0 insertions, 0 deletions | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TESTFIX-01 | 227-01, 227-02 | `_regenerate_saml_fixtures` autouse writes to `tmp_path` instead of mutating committed fixture files | ✓ SATISFIED | Old autouse deleted; `saml_response_dir` session fixture routes generator output to `tmp_path_factory.mktemp("saml_responses")`; no write path touches tracked fixtures dir |
| TESTFIX-02 | 227-02 | `git status` clean after full `pytest backend/tests/test_saml_overlay.py` run | ✓ SATISFIED | Verified locally: `git status --porcelain backend/tests/fixtures/saml/` empty after 19-test run; CI guard step in place using `git status --porcelain` (catches both modifications and new untracked files per WR-02 fix) |
| TESTFIX-03 | 227-02 | Committed `.xml.b64` files renamed to `.xml.b64.template`; docstring CI-fallback claim resolved | ✓ SATISFIED | 5 pure R100 renames via `git mv` confirmed; `_load_fixture_b64` template-fallback path wired; `test_load_fixture_b64_falls_back_to_template` Wave 0 test passes; module docstring updated to describe working fallback behavior accurately |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | — |

Anti-pattern scan of `backend/tests/test_saml_overlay.py` and `backend/tests/fixtures/saml/generate_fixtures.py`:
- No `TODO/FIXME/PLACEHOLDER` comments in phase-227-modified code.
- No `return null`, `return {}`, `return []` stubs in the new fixture or helper.
- The `except Exception` catch at line 76 is intentional and documented (Phase 227 WR-01 fix) — not a silent swallow pattern.
- `import tempfile` remains inside `main()` (REVIEW.md IN-01 info-level nit, not a blocker) — pre-existing style inconsistency; `tmpdir` cleanup not implemented (IN-02 nit) — also pre-existing, not a blocker.

### Human Verification Required

None. All success criteria are programmatically verifiable and were verified by running the actual test suite and git commands. The one manual-only item documented in the VALIDATION.md (deliberately break the autouse on a temp branch, push to draft PR, observe the CI guard step fail) is correctly marked as deferred/non-blocking in the SUMMARY.md — it is an optional confidence test of the CI enforcement path, not a gate for phase completion.

### Bonus Checks

**Docstring resolution (D-03):** The module docstring in `backend/tests/test_saml_overlay.py` lines 1-31 accurately describes the new `saml_response_dir` + template fallback behavior, explicitly stating that committed templates are the CI fallback when pysaml2/xmlsec1 are unavailable, and that `git status` stays clean after pytest. The factually-wrong "gitignored from the worktree's perspective" text from HEAD is gone. VERIFIED.

**CI guard (D-08):** Step "Verify SAML fixtures unchanged after pytest" is at line 342 in `ci.yml`, inserted between `Run tests with coverage` (332) and `Upload backend coverage report` (357). Uses `git status --porcelain -- tests/fixtures/saml/` (WR-02 improvement over `git diff --quiet`). Error message references "phase 227 (saml-test-fixture-tmp-path)" explicitly. VERIFIED.

**WR-01 fix:** `except (ImportError, OSError)` broadened to `except Exception` with explanatory comment listing `subprocess.CalledProcessError`, `RuntimeError`, and pysaml2 internal errors as covered cases. Verified at `test_saml_overlay.py:76`. VERIFIED.

**WR-02 fix:** `git diff --quiet` replaced with `git status --porcelain` in the CI step, ensuring untracked `.xml.b64` writes (the most likely regression vector) are also caught. Verified at `ci.yml:348`. VERIFIED.

**D-09 / R100 renames:** All 5 fixture renames show as pure R100 renames in `git log --summary 7102c416` (0 insertions, 0 deletions). VERIFIED.

### Gaps Summary

No gaps. All 4 ROADMAP success criteria are satisfied, all 3 requirement IDs (TESTFIX-01, TESTFIX-02, TESTFIX-03) have implementation evidence, the review warnings (WR-01, WR-02) were fixed inline at commit b5700992 before phase submission, and the SAML test suite runs green with a clean working tree post-pytest.

One deviation from SC#1 wording is present: the ROADMAP says "a CI step asserts `git diff --quiet backend/tests/fixtures/saml/`" but the implementation uses `git status --porcelain -- tests/fixtures/saml/` instead. This deviation is a strict improvement (catches untracked writes that `git diff --quiet` misses) and was the explicit intent of the WR-02 fix. No override needed — the SC spirit is fully met.

---

_Verified: 2026-05-01T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
