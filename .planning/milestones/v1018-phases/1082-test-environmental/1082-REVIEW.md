---
phase: 1082
depth: quick
status: clean
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
generated: 2026-05-21
files_reviewed:
  - backend/tests/test_reupload_idor.py
---

# Phase 1082: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** quick
**Files Reviewed:** 1
**Status:** clean

## Summary

Single test file edit. The plan specified patching the defining-module path (`app.modules.catalog.sources.preview.run_service_preview`); the executor correctly auto-corrected to the caller-namespace path (`app.modules.catalog.datasets.api.router_reupload.run_service_preview`) because `router_reupload.py:44` uses a module-top from-import that binds the symbol at load time. The caller-namespace target is the technically correct choice and the correction is faithfully documented in the summary, docstring, and inline comment.

## Checks

**1. Patch target correctness.** `router_reupload.py:44` confirms `from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview` — a module-top binding. The patch at `test_reupload_idor.py:452` correctly targets `app.modules.catalog.datasets.api.router_reupload.run_service_preview`. The plan's stated defining-module target (`app.modules.catalog.sources.preview.run_service_preview`) is absent from the file (grep returns 0 hits for that string as executable code). Correct.

**2. AsyncMock correctness.** `preview.py:49` confirms `async def run_service_preview(...)`. `AsyncMock` is the right mock type. The `side_effect=IngestionError(...)` at line 453 has no `return_value` (which would incorrectly bypass the except block). Correct.

**3. IngestionError branch wiring.** `router_reupload.py:268-272` has `except IngestionError: raise HTTPException(status_code=502)`. The test imports `IngestionError` directly from `app.processing.ingest.ogr` (line 24), the same underlying class the router binds at line 54 via `_catalog_port.ingestion_error_class()`. The `isinstance` check fires deterministically. Test assertions `status_code != 404` and `status_code in (400, 502)` are unchanged. Correct.

**4. Docstring extension.** `"TD-04 disposition (mock-out"` confirmed at line 408 per grep. Docstring accurately documents the caller-namespace target and the three grounds for rejecting skip-with-rationale. Correct.

**5. No collateral damage.** `git diff HEAD~1..HEAD -- backend/app/` is empty (0 lines). Only `backend/tests/test_reupload_idor.py` modified in commit `8a1d2777`. Correct.

**6. No skip marks.** `pytest.mark.skip`, `shutil.which`, `pytest.importorskip` are absent from executable code. The one `shutil.which` hit at line 429 is inside the docstring referencing the rejected shape (a). Zero skip decorators. Correct.

**7. Cross-phase invariants.** `tasks_common.py` has 8 `# broad:` comments (includes lines 232, 238, 1030 from Phase 1080-01 plus 5 others — all intact). `config.py:309` has `connect_args["ssl"] = False` (Phase 1080-02 intact). No regression.

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
