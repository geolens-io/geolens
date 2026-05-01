---
phase: 223-marketplace-billing-extraction
plan: "03"
subsystem: backend-core
tags: [delete, settings, env-example, billing, cleanup, BILLING-02, BILLING-05]
dependency_graph:
  requires:
    - 223-01 (BillingExtension Protocol + DefaultBillingExtension + get_billing_extensions)
    - 223-02 (lifespan dispatch loop replacing the marketplace block; import deleted from api/main.py)
  provides:
    - core/marketplace.py ABSENT from filesystem (D-02)
    - Settings class with zero aws_marketplace_* fields (D-03 / BILLING-05)
    - .env.example AWS Marketplace section under "Enterprise overlay only" header (D-05)
    - test_settings_has_no_marketplace_fields regression guard (BILLING-05)
  affects:
    - 223-04 (architecture-guard test can now assert ImportError on app.core.marketplace)
    - 223-05 (enterprise overlay adds MarketplaceBillingExtension containing the body deleted here)
tech_stack:
  added: []
  patterns:
    - Clean delete (not relocation) — D-02 contract honored
    - Pydantic v2 model_fields schema-level assertion in tests
key_files:
  created: []
  modified:
    - backend/app/core/config.py
    - .env.example
    - backend/tests/test_billing_extension.py
  deleted:
    - backend/app/core/marketplace.py
decisions:
  - "D-02: marketplace.py deleted entirely (clean delete), body moves to enterprise overlay Plan 05"
  - "D-03: aws_marketplace_* fields removed from core Settings; overlay reads via os.environ.get"
  - "D-05: .env.example restructured with Enterprise overlay only header + NO EFFECT warning"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-30"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 223 Plan 03: Core Cleanup — Delete marketplace.py + Remove Settings Fields

**One-liner:** Deleted `core/marketplace.py` entirely, stripped both `aws_marketplace_*` fields and the matching `field_validator` entry from core `Settings`, restructured `.env.example` under an explicit "Enterprise overlay only" header, and locked BILLING-05 with a schema-level regression-guard test.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Delete marketplace.py + remove aws_marketplace_* from config.py | e71a4e0b | `backend/app/core/marketplace.py` (deleted), `backend/app/core/config.py` |
| 2 | Restructure .env.example AWS Marketplace section per D-05 | 64ade0bb | `.env.example` |
| 3 | Append test_settings_has_no_marketplace_fields (BILLING-05) | d8746f1d | `backend/tests/test_billing_extension.py` |

## What Was Done

### Task 1: Delete core/marketplace.py + Strip aws_marketplace_* from Settings

**Pre-flight:** Confirmed zero remaining `from app.core.marketplace` imports in `backend/app/` before deletion — Plan 02 severed the import chain at `api/main.py:20` as required by D-14's cross-repo ordering.

**Deleted** `backend/app/core/marketplace.py` (30 lines: `register_marketplace_usage` function with inline `import boto3` and `boto3.client("meteringmarketplace").register_usage(...)` body). This is a clean delete per D-02 — the body moves verbatim into the enterprise overlay's `MarketplaceBillingExtension.on_startup` in Plan 05.

**Edited** `backend/app/core/config.py`:
- Removed `aws_marketplace_product_code: str | None = None` (was line 87)
- Removed `aws_marketplace_public_key_version: int = 1` (was line 88)
- Removed `"aws_marketplace_product_code"` from the `@field_validator(...)` whitelist (was line 108)

After edits: `grep -c 'aws_marketplace'` in config.py returns 0. `tile_signing_secret` and all 17 other validator entries preserved.

**Verified:**
- `from app.core.config import settings; assert not hasattr(settings, 'aws_marketplace_product_code')` — passes
- `from app.api.main import app` — boots cleanly, no ImportError, no Pydantic validation error
- `grep -rn 'app.core.marketplace' backend/app/` — zero matches

### Task 2: Restructure .env.example per D-05

Replaced the 10-line AWS Marketplace section (under `# --- AWS Marketplace (BYOL/AMI billing) ---`) with a 14-line section under `# --- AWS Marketplace (Enterprise overlay only) ---`.

The new section adds:
- An explicit `WARNING` paragraph naming `MarketplaceBillingExtension` as the consumer
- "They have NO EFFECT on community (open-core) deployments" — prevents operators from setting the var expecting metering and getting silent inaction
- "enables hourly metering via overlay" qualifier in the product code comment

The env var NAMES and commented-out VALUES (`AWS_MARKETPLACE_PRODUCT_CODE=`, `AWS_MARKETPLACE_PUBLIC_KEY_VERSION=1`) are unchanged — existing `.env` files from before v13.3 continue to work without modification.

### Task 3: Append test_settings_has_no_marketplace_fields (BILLING-05)

Appended the regression-guard test to `backend/tests/test_billing_extension.py`. The test asserts absence at three levels:
- `(a)` `hasattr(settings, 'aws_marketplace_product_code')` is False
- `(b)` `hasattr(settings, 'aws_marketplace_public_key_version')` is False
- `(c)` Neither field name is in `Settings.model_fields` (Pydantic v2 schema registry — catches `extra='allow'` bypass attempts)

Full test file now has **7 tests, all GREEN** (3 Wave-0 from Plan 01 + 3 dispatch from Plan 02 + 1 settings-removal from this plan).

## Verification Results

```
tests/test_billing_extension.py::test_billing_extension_protocol_shape PASSED
tests/test_billing_extension.py::test_default_billing_extension_is_noop PASSED
tests/test_billing_extension.py::test_get_billing_extensions_default_fallback PASSED
tests/test_billing_extension.py::test_dispatch_runs_all_registered_extensions PASSED
tests/test_billing_extension.py::test_raising_extension_isolated PASSED
tests/test_billing_extension.py::test_hanging_extension_timeout PASSED
tests/test_billing_extension.py::test_settings_has_no_marketplace_fields PASSED
16 passed, 16 warnings (test_billing_extension + test_audit_sink + test_layering combined)
```

Community-deployment smoke test passed: `get_billing_extensions()` returns `[DefaultBillingExtension()]` with `AWS_MARKETPLACE_PRODUCT_CODE` unset — zero AWS API calls, zero boto3 Marketplace imports.

## Deviations from Plan

None — plan executed exactly as written.

## Success Criteria Verified

- [x] `backend/app/core/marketplace.py` deleted from the filesystem
- [x] `backend/app/core/config.py:Settings.aws_marketplace_product_code` field removed
- [x] `backend/app/core/config.py:Settings.aws_marketplace_public_key_version` field removed
- [x] `backend/app/core/config.py` field_validator does not contain `aws_marketplace_product_code`
- [x] `.env.example` AWS Marketplace section restructured per D-05 (`Enterprise overlay only` header + WARNING)
- [x] `test_settings_has_no_marketplace_fields` appended to test_billing_extension.py and passes GREEN
- [x] All 7 tests in test_billing_extension.py pass GREEN
- [x] `from app.api.main import app` succeeds (no ImportError, no Pydantic error)
- [x] No surviving references to `app.core.marketplace` in `backend/app/`
- [x] Phase 222 tests still pass (no regression) — 16 passed total across three test files
- [x] Ruff clean for all touched files

## What Is Unblocked

- **Plan 04 (architecture guard + Makefile):** Can now assert that `from app.core.marketplace import register_marketplace_usage` raises `ImportError`, since the file is deleted. The `make billing-extraction-discipline` Makefile target can wrap this + a grep confirming zero `app.core.marketplace` references in `backend/app/`.
- **Plan 05 (enterprise overlay):** The `MarketplaceBillingExtension` class in `geolens-enterprise` will contain the verbatim 30-line body that was in `core/marketplace.py`. The overlay reads `AWS_MARKETPLACE_PRODUCT_CODE` and `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` directly via `os.environ.get` (D-04/D-13) — no core Settings dependency needed.

## Cross-Repo Note

The 30-line body of `register_marketplace_usage` that was deleted from `core/marketplace.py` must move verbatim into `MarketplaceBillingExtension.on_startup` in the enterprise overlay (`~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py`). Plan 05 handles this. The core side of the boundary is clean as of this plan.

## Self-Check: PASSED

Files verified present/absent:
- `backend/app/core/marketplace.py`: ABSENT (confirmed `test -f` returns 1)
- `backend/app/core/config.py`: FOUND with 0 marketplace references
- `.env.example`: FOUND with new header confirmed by grep
- `backend/tests/test_billing_extension.py`: FOUND with 7 tests

Commits verified:
- e71a4e0b: FOUND in git log
- 64ade0bb: FOUND in git log
- d8746f1d: FOUND in git log
