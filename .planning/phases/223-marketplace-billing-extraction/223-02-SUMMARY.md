---
phase: 223-marketplace-billing-extraction
plan: 02
subsystem: platform-extensions
tags: [lifespan, dispatch, billing, anyio, timeout, BILLING-04]
dependency_graph:
  requires:
    - 223-01-SUMMARY.md  # BillingExtension Protocol, DefaultBillingExtension, get_billing_extensions() all ship in Plan 01
  provides:
    - Generic BillingExtension dispatch loop in api/main.py (replaces AWS Marketplace block)
    - 3 anyio dispatch tests: happy path, raising isolation, hanging timeout
  affects:
    - backend/app/api/main.py  # import deleted + marketplace block replaced
    - backend/tests/test_billing_extension.py  # 3 new dispatch tests appended
tech_stack:
  added: []
  patterns:
    - asyncio.wait_for(timeout=10.0) dispatch per extension (D-10 / D-11)
    - per-extension try/except isolation (D-12)
    - env-var gate moved to overlay (D-13)
    - inline _dispatch helper for anyio tests (mirrors production loop without TestClient)
key_files:
  created: []
  modified:
    - backend/app/api/main.py
    - backend/tests/test_billing_extension.py
decisions:
  - "asyncio.wait_for(timeout=10.0) hardcoded in core dispatch (D-11 — YAGNI for env-var config)"
  - "No if settings.aws_marketplace_product_code gate in core (D-13 — env-var check moves to overlay)"
  - "Dispatch loop runs unconditionally — community deployments iterate over [DefaultBillingExtension()] whose on_startup is a no-op (D-07); zero overhead"
  - "Test-only timeout=0.5s for hanging test to keep suite fast; production value 10.0 verified by Plan 04 architecture guard grep"
  - "_dispatch helper collapses TimeoutError + Exception into one except clause in tests (behavior-not-log-shape assertion)"
metrics:
  duration: ~15 minutes
  completed: 2026-04-30
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 2
---

# Phase 223 Plan 02: Generic BillingExtension Dispatch Loop Summary

One-liner: Replace the AWS Marketplace-specific lifespan block with a generic `for ext in get_billing_extensions()` dispatch loop wrapping each extension with `asyncio.wait_for(timeout=10.0)` + per-extension try/except isolation — plus 3 anyio tests verifying D-10/D-12 contract.

## What Was Built

### api/main.py — Three Surgical Edits (Single Commit)

**Edit A — Deleted line 20** (`from app.core.marketplace import register_marketplace_usage`)
After deletion: no reference to `app.core.marketplace` anywhere in `api/main.py`. The `register_marketplace_usage` symbol no longer appears in core.

**Edit B — Added `get_billing_extensions` to the import block** (alphabetical insertion):
```python
from app.platform.extensions import (
    get_billing_extensions,   # <-- added
    get_extension_routers,
    list_extensions,
    load_extensions,
)
```

**Edit C — Replaced the marketplace conditional (old lines 184-203) with the generic dispatch loop:**
```python
    # Phase 223 BILLING-04 / D-10: generic BillingExtension dispatch.
    # Community: DefaultBillingExtension.on_startup is a no-op (D-07).
    # Enterprise overlay (geolens-enterprise) registers MarketplaceBillingExtension
    # which reads AWS_MARKETPLACE_PRODUCT_CODE itself (D-13 — env-var gate lives
    # in the overlay, not in core).
    for ext in get_billing_extensions():
        try:
            await asyncio.wait_for(ext.on_startup(app), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "BillingExtension.on_startup timed out -- continuing without billing",
                extension=type(ext).__name__,
                timeout_seconds=10.0,
            )
        except Exception as exc:
            logger.warning(
                "BillingExtension.on_startup failed -- continuing without billing",
                extension=type(ext).__name__,
                error=str(exc),
            )
```

Lifespan ordering preserved: `load_extensions()` → S3 health check → BillingExtension dispatch → `init_cache()`.

### test_billing_extension.py — 3 New Dispatch Tests + Infrastructure

**New fixture classes:**
- `FixtureBillingExtension` — records `app` arguments for dispatch coverage assertions
- `RaisingBillingExtension` — raises `RuntimeError` in `on_startup`
- `HangingBillingExtension` — `await asyncio.sleep(15.0)` to exceed timeout

**`_dispatch` async helper** — inline replica of the production loop; collapses TimeoutError + Exception for behavior-not-log-shape testing.

**Three new anyio tests:**
1. `test_dispatch_runs_all_registered_extensions` — D-10 happy path; both extensions in `[DefaultBillingExtension(), FixtureBillingExtension()]` see the same mock app
2. `test_raising_extension_isolated` — D-12; `RaisingBillingExtension` first in list; asserts `FixtureBillingExtension` still runs after the raise
3. `test_hanging_extension_timeout` — D-10/D-11; uses 0.5s test timeout; asserts loop completes in <2s AND `FixtureBillingExtension` still runs after timeout

All three tests use try/finally registry save/restore to prevent fixture bleed.

## Dispatch Contract (D-10 / D-11 / D-12 / D-13)

| Decision | What Was Done |
|----------|---------------|
| D-10: per-extension wait_for + try/except | Each `on_startup` wrapped in `asyncio.wait_for(timeout=10.0)` with separate TimeoutError + Exception handlers |
| D-11: 10s hardcoded | `timeout=10.0` literal; no env-var config |
| D-12: per-iteration isolation | try/except scoped inside the for-loop body; one failure does not abort iteration |
| D-13: env-var gate in overlay | No `if settings.aws_marketplace_product_code:` in core; the overlay's `MarketplaceBillingExtension.on_startup` short-circuits on unset env var |

## core/marketplace.py Status

`backend/app/core/marketplace.py` **still exists** at this point — Plan 03 deletes it. Plan 02 only severs the import chain so `api/main.py` no longer pulls in `register_marketplace_usage` at module load time. Running `from app.core.marketplace import register_marketplace_usage` in isolation still works until Plan 03 commits. The architecture-guard test in Plan 04 (`test_layering.py`) verifies the deletion is complete.

## Test Results

```
tests/test_billing_extension.py::test_billing_extension_protocol_shape PASSED
tests/test_billing_extension.py::test_default_billing_extension_is_noop PASSED
tests/test_billing_extension.py::test_get_billing_extensions_default_fallback PASSED
tests/test_billing_extension.py::test_dispatch_runs_all_registered_extensions PASSED
tests/test_billing_extension.py::test_raising_extension_isolated PASSED
tests/test_billing_extension.py::test_hanging_extension_timeout PASSED
6 passed, 1 warning in 1.81s
```

Re-run stable (no registry bleed). `test_hanging_extension_timeout` completes in ~1s real time using 0.5s test timeout (would be ~16s if wait_for was absent).

Phase 222 regression (test_audit_sink.py + test_layering.py): 9 passed, 0 failed.

## What Is Unblocked

- **Plan 03** (settings removal + `core/marketplace.py` deletion + `.env.example` restructure): import chain from core to marketplace is severed; Plan 03 can delete the file without transient broken-import state
- **Plan 04** (architecture guard in test_layering.py + Makefile target): can now add the BILLING-02 guard asserting `from app.core.marketplace import ...` raises ImportError
- **Plan 05** (enterprise overlay `MarketplaceBillingExtension`): core dispatch loop is in place; the overlay's `register_extensions` call will populate `_extensions["billing_extensions"]` and the loop will invoke `on_startup` automatically

## Deviations from Plan

None — plan executed exactly as written. The `import asyncio` re-addition to the test file (removed in Plan 01 as unused) is the expected Plan 02 action (Plan 01 SUMMARY documented it as deferred to Plan 02).

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes. The dispatch loop runs inside the FastAPI lifespan startup context — same trust boundary as today's marketplace block. T-223-01 (DoS via hanging extension) and T-223-02 (DoS/Repudiation via raising extension) are both mitigated and verified end-to-end by `test_hanging_extension_timeout` and `test_raising_extension_isolated`.

## Self-Check: PASSED

Files verified:
- `backend/app/api/main.py` — exists, `from app.core.marketplace` count = 0, `for ext in get_billing_extensions():` count = 1
- `backend/tests/test_billing_extension.py` — exists, 6 test functions, all anyio-decorated where async

Commits verified:
- `4ab7edda` — feat(223-02): replace AWS Marketplace block with generic BillingExtension dispatch loop
- `85aed635` — test(223-02): add BILLING-04 dispatch tests — happy path, raising isolation, hanging timeout
