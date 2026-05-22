---
phase: 1082-test-environmental
plan: "01"
subsystem: testing
tags: [pytest, ogrinfo, gdal, environmental-dependency, mock-out, reupload-idor, hygiene, td-04]

# Dependency graph
requires:
  - phase: 1081-test-fixture-assertion-drift
    provides: "Plan 1081-02 canonical AsyncMock patch pattern and lazy-import patch target rule"
provides:
  - "test_owner_gets_non_404_on_service_preview passes on macOS hosts without gdal-bin via caller-namespace AsyncMock patch"
  - "TD-04 closure: ogrinfo CLI environmental dependency removed from test_reupload_idor.py"
affects:
  - phase: 1083-close-gate
    via: "TD-04 row now satisfies PYTEST-BASELINE prerequisite; test counted as PASSING on macOS"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-top import distinction: when caller uses `from module import fn` at module top (not inside function body), patch the CALLER namespace (router_reupload.run_service_preview), not the defining module — the symbol is bound in the caller's namespace at module load time"

key-files:
  created: []
  modified:
    - backend/tests/test_reupload_idor.py

key-decisions:
  - "Patch target is CALLER namespace (app.modules.catalog.datasets.api.router_reupload.run_service_preview) for module-top imports — defining-module patch silently no-ops because the symbol is already bound"
  - "side_effect=IngestionError drives the production 502 path deterministically; return_value would push past the except block and produce 200 (wrong assertion outcome)"
  - "Shape (b) mock-out chosen over shape (a) skip-with-rationale: gdal-bin IS in Dockerfile so shutil.which skip would silently pass CI while failing on macOS dev — the false-green pattern TD-04 was named for"

patterns-established:
  - "Caller-namespace patch rule for module-top imports: import binding location determines correct patch target. Lazy (function-body) import → defining-module target (Plan 1081-02 rule). Module-top import → caller-namespace target (this plan). Same conceptual rule, two surface cases."

requirements-completed: [TD-04]

# Metrics
duration: 25min
completed: 2026-05-21
---

# Phase 1082 Plan 01: TD-04 (ogrinfo CLI Environmental Disposition) Summary

**AsyncMock caller-namespace patch on `run_service_preview` in `test_owner_gets_non_404_on_service_preview` removes the ogrinfo CLI host dependency, restoring green pytest signal on macOS dev hosts without gdal-bin while keeping the IDOR/auth invariant fully exercised**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-21T00:00:00Z
- **Completed:** 2026-05-21T00:25:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- `test_owner_gets_non_404_on_service_preview` now passes on macOS dev hosts without `gdal-bin`/`ogrinfo` on PATH (the v1017 audit's named TD-04 failure environment)
- IDOR/auth invariant (owner is NOT rejected by `check_dataset_access` → response is non-404, specifically 502 post-mock) preserved end-to-end; auth gate, SSRF gate, `build_gdal_source`, and IngestionError handler all remain exercised against real production code
- Disposition (mock-out, not skip-with-rationale) documented in test docstring with literal substring `"TD-04 disposition (mock-out"` per ROADMAP Phase 1082 SC-2
- Zero production code modified; zero skip decorators added

## Lines Added

**Edit 1 — New import (line 27, after `from app.platform.jobs.models import IngestJob`):**
```python
from app.processing.ingest.ogr import IngestionError
```

**Edit 2 — Docstring extended + `with patch(...)` wrapping `client.post(...)` (lines 403-460 post-edit):**

Docstring extended from 4-line to 30-line block documenting the TD-04 disposition, the module-top import distinction that requires caller-namespace patching, and the three grounds for rejecting skip-with-rationale.

Patch block added:
```python
with patch(
    "app.modules.catalog.datasets.api.router_reupload.run_service_preview",
    new=AsyncMock(side_effect=IngestionError("ogrinfo failed: mocked for TD-04")),
):
    resp = await client.post(...)
```

Assertions unchanged: `resp.status_code != 404` and `resp.status_code in (400, 502)`.

## Task Commits

1. **Task 1: Mock run_service_preview + extend docstring** - `8a1d2777` (test)

## Files Created/Modified

- `backend/tests/test_reupload_idor.py` - Added IngestionError import, extended docstring with TD-04 disposition rationale, wrapped `client.post()` in caller-namespace AsyncMock patch

## Decisions Made

### Patch Target: Caller Namespace (deviation from plan's stated target)

The plan specified `app.modules.catalog.sources.preview.run_service_preview` (defining-module path). This was incorrect for the module-top import case.

**Root cause:** `router_reupload.py:44` uses `from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview` — a module-top from-import that binds `run_service_preview` into `router_reupload`'s module namespace at load time. Patching the defining module (`app.modules.catalog.sources.preview.run_service_preview`) replaces the attribute on the `preview` module object but does NOT update the already-bound reference in `router_reupload`. The mock was silently no-oping: the real `ogrinfo` subprocess was still being called.

**Correct target:** `app.modules.catalog.datasets.api.router_reupload.run_service_preview` — the caller's namespace, where the function is looked up at call time.

**Contrast with Plan 1081-02:** `tasks_reupload.py` uses a **lazy from-import inside the function body** — the symbol is re-bound from the defining module on every call, so the defining-module target is correct there. This plan's case is different: module-top import → caller-namespace target is required.

The plan's scope_notes stated the defining-module patch "mirrors Plan 1081-02's lazy-import patch target rule — even though the caller's import at `router_reupload.py:44` is module-top" — this was incorrect. The lazy-import rule does NOT extend to module-top imports. The rule was applied, discovered to fail on first test run, and corrected automatically (Rule 1 bug fix).

**Docstring updated** to accurately document the caller-namespace target and the module-top import distinction, rather than misstating the defining-module rationale.

### Side-effect Choice: `IngestionError`, not `return_value`

Raising `IngestionError` from the mock drives the handler's `except IngestionError → HTTPException(502)` branch at `router_reupload.py:268-272`. Providing a `return_value` dict would push execution into the `SchemaDiff`/`IngestJob` creation path, producing a 200 response — which would fail the `status_code in (400, 502)` assertion.

### Shape (b) Mock-out, not Shape (a) Skip-with-rationale

Three grounds for rejecting shape (a) (per ROADMAP Phase 1082 SC #2 — documented in test docstring):
1. **CI/dev parity:** `gdal-bin` IS installed in the Dockerfile (lines 22-26, 70-74) — a `shutil.which("ogrinfo")` skip would silently skip on macOS dev but never on CI — exactly the false-green pattern the v1017 milestone audit named as the TD-04 problem.
2. **Test contract:** The test pins IDOR/auth (`check_dataset_access` does not block the owner). The `ogrinfo` call is downstream of the auth gate and its output is never inspected by the test. Mocking the incidental plumbing does not weaken the IDOR coverage.
3. **Milestone consistency:** Plan 1081-02 (same milestone) chose mock-out for the same defense-in-depth-vs-incidental-plumbing trade-off.

## Pytest Exit Codes

- `which ogrinfo` — empty (exit 1): confirmed TD-04 environment (macOS host without gdal-bin)
- `pytest tests/test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview -x` — exit 0: 1 passed
- `pytest tests/test_reupload_idor.py -x` — exit 0: 7 passed (6 IDOR-non-owner + 1 owner-allowed, no regressions)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected patch target from defining-module to caller-namespace**

- **Found during:** Task 1 (first test run after initial edit)
- **Issue:** Plan specified `app.modules.catalog.sources.preview.run_service_preview` as the patch target, citing Plan 1081-02's lazy-import rule. However, `router_reupload.py:44` uses a module-top from-import — the symbol is bound in `router_reupload`'s namespace at load time, not resolved lazily from the defining module on each call. The defining-module patch was a silent no-op: `FileNotFoundError: [Errno 2] No such file or directory: 'ogrinfo'` still surfaced, test still failed.
- **Fix:** Changed patch target to `app.modules.catalog.datasets.api.router_reupload.run_service_preview` (the caller's namespace). Updated both the docstring and inline comment to accurately describe the module-top import distinction.
- **Files modified:** `backend/tests/test_reupload_idor.py` (part of the same task commit)
- **Verification:** Test passes after correction; `grep -c "app.modules.catalog.datasets.api.router_reupload.run_service_preview" tests/test_reupload_idor.py` returns 2 (patch string + comment)
- **Committed in:** `8a1d2777` (part of task commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — incorrect patch target)
**Impact on plan:** Required — the plan's stated patch target was technically incorrect for module-top imports. Fix was necessary for the test to pass. No scope creep. Docstring updated to accurately reflect the correction.

## Canonical Precedent Cross-Reference

This is the third application of the defining-module / caller-namespace patch target rule in the v1017→v1018 sweep:

| Plan | File | Import style | Correct patch target |
|------|------|--------------|----------------------|
| 1075-03 | `test_ingest.py` | lazy (function-body) | defining-module (`app.modules.catalog.sources.security.validate_url_for_ssrf`) |
| 1081-02 | `test_reupload_service.py` | lazy (function-body) | defining-module (`app.modules.catalog.sources.security.validate_url_for_ssrf`) |
| 1082-01 | `test_reupload_idor.py` | **module-top** | **caller-namespace** (`app.modules.catalog.datasets.api.router_reupload.run_service_preview`) |

**Strengthened rule (replaces Plan 1081-02's "lazy-import patch target rule"):**
> The correct patch target is always the namespace where the function name is resolved at call time. For lazy/function-body imports, that is the defining module (symbol re-bound per call). For module-top from-imports, that is the caller's module namespace (symbol bound at load time, not updated by patching the defining module).

**Note on plan scope_notes:** The plan's scope_notes stated "the defining-module patch is the canonical target across the v1018 sweep" even for module-top imports. This is incorrect. The canonical rule is "patch where the name is resolved at call time," which produces different targets depending on import style. Future plans should read both the import location (module-top vs. lazy/function-body) and the `tasks_reupload.py` caller before choosing a patch target.

## Known Stubs

None — this is a test-only fix with no UI rendering or data stubs.

## Threat Flags

None — no new production endpoints, auth paths, or schema changes introduced. Test-only change.

## TD-04 Closure Reference

- **Originating discovery:** `.planning/v1017-MILESTONE-AUDIT.md` TD-04 row — "environmental dependency on the `ogrinfo` CLI being on host PATH"
- **Downstream consumer:** Phase 1083 close-gate baseline — `test_owner_gets_non_404_on_service_preview` now counts as PASSING on macOS without environmental dependencies

## Self-Check: PASSED

- `backend/tests/test_reupload_idor.py` modified: FOUND
- Commit `8a1d2777` exists: FOUND (git log HEAD)
- `git diff --stat backend/app/`: 0 lines (no production code)
- `pytest tests/test_reupload_idor.py -x`: 7 passed, exit 0
- `grep -c "TD-04 disposition (mock-out" backend/tests/test_reupload_idor.py`: 1 (docstring)
- `grep -c "pytest.mark.skip"` (non-comment): 0

## Next Phase Readiness

- TD-04 row satisfied; Phase 1083 close-gate can proceed
- The corrected patch target rule (caller-namespace for module-top imports) should be documented in the project's test conventions if a similar case arises in future milestones

---
*Phase: 1082-test-environmental*
*Completed: 2026-05-21*
