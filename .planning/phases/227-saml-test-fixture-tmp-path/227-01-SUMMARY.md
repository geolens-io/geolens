---
phase: 227-saml-test-fixture-tmp-path
plan: 01
subsystem: testing
tags: [pytest, saml, fixture-hygiene, test-infra]

# Dependency graph
requires: []
provides:
  - "generate_fixtures.main() accepts output_dir: Path | None = None parameter"
  - "5 idp_response_*.xml.b64 files restored to HEAD baseline (clean working tree)"
  - "Plan 02 can import main and pass output_dir=session_dir to write into tmp_path"
affects:
  - "227-02 (autouse swap + git mv rename — depends on parameterized generator)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optional output_dir with HERE-default: main(output_dir: Path | None = None) → target = output_dir if output_dir is not None else HERE"

key-files:
  created: []
  modified:
    - backend/tests/fixtures/saml/generate_fixtures.py

key-decisions:
  - "Commit restore + generator refactor as single commit (D-10 steps 1+2 combined) — working tree clean after restore, no intermediate state to capture"
  - "target.mkdir(parents=True, exist_ok=True) added after cert/key guard so caller-supplied tmp dirs are created idempotently"
  - "All 6 HERE/idp_response_ references in main() replaced with target/idp_response_ (5 write_bytes lines + 2 shutil.copyfile args on separate lines)"

patterns-established:
  - "Optional output_dir parameter with module-constant default: usable for any script that supports both CLI and in-process invocation"

requirements-completed:
  - TESTFIX-01

# Metrics
duration: 10min
completed: 2026-05-01
---

# Phase 227 Plan 01: restore baseline + parameterize generate_fixtures.main() Summary

**generate_fixtures.main() now accepts output_dir: Path | None = None; writing to tmp_path or HERE depending on caller; 5 committed fixture files restored to HEAD baseline for a clean Plan 02 rename**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-01T00:00:00Z
- **Completed:** 2026-05-01T00:10:00Z
- **Tasks:** 2
- **Files modified:** 1 (generate_fixtures.py; 5 fixture files restored to HEAD via git checkout)

## Accomplishments

- Restored 5 dirty `idp_response_*.xml.b64` files to HEAD baseline via `git checkout --` (no content editing, no commit needed — files matched HEAD)
- Added `output_dir: Path | None = None` parameter to `generate_fixtures.main()`
- Inserted `target = output_dir if output_dir is not None else HERE` + `target.mkdir(parents=True, exist_ok=True)` after the cert/key guard
- Substituted all 6 `HERE / "idp_response_*"` references in `main()` to `target / "idp_response_*"` (5 write_bytes + 2 shutil.copyfile args)
- Smoke-tested `main(output_dir=Path('/tmp/saml_smoke_227'))` — all 5 fixtures landed in tmp dir, not in `backend/tests/fixtures/saml/`
- Verified 18 existing SAML tests still pass (autouse still calls `main()` with no args → target = HERE)

## Task Commits

1. **Task 01: Restore dirty fixture files to HEAD** — no commit (files restored to HEAD via `git checkout --`; no diff to commit)
2. **Task 02: Refactor generate_fixtures.main()** — `1fe02f7e` (refactor)

**Plan metadata commit:** (created below with SUMMARY + STATE + ROADMAP)

## Files Created/Modified

- `backend/tests/fixtures/saml/generate_fixtures.py` — signature changed to `main(output_dir: Path | None = None)`, target binding inserted, 6 HERE→target substitutions in main() body

## Decisions Made

- Combined Task 01 restore + Task 02 generator refactor into a single commit (D-10 suggested combining steps 1+2 was acceptable — no useful intermediate state)
- Ran `git checkout --` on the 5 fixture files after the pytest run (post-test restore, belt-and-suspenders) so the committed files match HEAD when Plan 02 begins its `git mv`

## Deviations from Plan

None — plan executed exactly as written.

The post-pytest dirt on the 5 fixture files (expected behavior — autouse re-ran in-place) was handled by restoring them to HEAD a second time at the end of verification, per the `<verification>` step 6 in the plan.

## Issues Encountered

None.

## Dependency Hand-off Contract for Plan 02

Plan 02 may safely:

```python
from tests.fixtures.saml.generate_fixtures import main as generate_saml_fixtures
generate_saml_fixtures(output_dir=session_dir)
```

where `session_dir` is a `pathlib.Path` from `tmp_path_factory.mktemp("saml_responses")`. All 5 fixtures (`idp_response_signed.xml.b64`, `idp_response_replay.xml.b64`, `idp_response_expired.xml.b64`, `idp_response_unsigned.xml.b64`, `idp_response_xsw.xml.b64`) will be written into `session_dir`, not into `backend/tests/fixtures/saml/`.

Plan 02 can also `git mv` the 5 `idp_response_*.xml.b64` files cleanly to `.xml.b64.template` because the working tree for those files is at HEAD (verified: `git diff --quiet -- backend/tests/fixtures/saml/idp_response_*.xml.b64` exits 0).

## Next Phase Readiness

- Plan 02 (`227-02`) can proceed: rename 5 `.xml.b64` → `.xml.b64.template` via `git mv`, swap the autouse to the `saml_response_dir` session fixture, rewrite `_load_fixture_b64` with template fallback, migrate 9 callsites, add CI guard
- No blockers

## Self-Check

**Files exist:**
- `backend/tests/fixtures/saml/generate_fixtures.py` — modified with output_dir param

**Commits exist:**
- `1fe02f7e` — refactor(227): route generate_fixtures.main() output through output_dir param

## Self-Check: PASSED

---
*Phase: 227-saml-test-fixture-tmp-path*
*Completed: 2026-05-01*
