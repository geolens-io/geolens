---
phase: 223-marketplace-billing-extraction
plan: "05"
subsystem: billing-extension-overlay
tags: [cross-repo, enterprise-overlay, billing, audit-close-gate, requirements-amendment]
dependency_graph:
  requires:
    - "223-01: BillingExtension Protocol scaffolding (app.platform.extensions.protocols + defaults + accessor)"
    - "223-02: Lifespan dispatch loop (api/main.py:184-203 replaced)"
    - "223-03: core/marketplace.py deleted + Settings fields removed"
    - "223-04: Architecture guards (test_layering.py + make billing-extraction-discipline)"
  provides:
    - "geolens-enterprise/geolens_enterprise/billing/__init__.py with MarketplaceBillingExtension"
    - "geolens-enterprise/geolens_enterprise/__init__.py amended with billing_extensions setdefault+append"
    - "geolens-enterprise/pyproject.toml with boto3>=1.35.0"
    - ".planning/REQUIREMENTS.md BILLING-03 amended per D-01"
    - ".planning/ROADMAP.md Phase 223 SC#1 amended per D-01"
    - "backend/tests/test_billing_extension.py 8th test (test_enterprise_overlay_register_pattern)"
  affects:
    - "Phase 223 BILLING-06 close gate (pending /oc-audit re-run)"
    - "v13.3 milestone close audit doc"
tech_stack:
  added:
    - "geolens_enterprise.billing.MarketplaceBillingExtension (enterprise overlay class)"
    - "boto3>=1.35.0 in geolens-enterprise/pyproject.toml"
  patterns:
    - "setdefault+append list-shape slot registration (D-06) — mirrors Phase 222 AuditSink"
    - "lazy-import helper _get_billing_extension() — mirrors _get_saml/_get_audit/_get_branding"
    - "inline boto3 import inside _register_usage — deferred until env var set"
key_files:
  created:
    - "~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py"
  modified:
    - "~/Code/geolens-enterprise/geolens_enterprise/__init__.py"
    - "~/Code/geolens-enterprise/pyproject.toml"
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"
    - "backend/tests/test_billing_extension.py"
decisions:
  - "D-01: BILLING-03 wording amended — boto3 stays in core for S3 storage; architectural goal reframed to 'no meteringmarketplace call in backend/app/'"
  - "D-06: billing_extensions is list-shape slot using setdefault+append; DefaultBillingExtension preserved in iteration"
  - "D-13: conditional gate (if not product_code: return) lives in overlay on_startup, not in core dispatch"
  - "D-14: cross-repo task ordering respected — core Plans 01-04 shipped before this overlay Plan 05"
metrics:
  completed: "2026-04-30"
---

# Phase 223 Plan 05: Enterprise Overlay + Requirements Amendments Summary

**One-liner:** Cross-repo MarketplaceBillingExtension overlay class registered via setdefault+append; BILLING-03/SC#1 reframed per D-01; 8/8 billing tests GREEN; BILLING-06 pending /oc-audit re-run.

## What Was Built

### Task 1: MarketplaceBillingExtension overlay class (geolens-enterprise repo)

New file `~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py` containing `MarketplaceBillingExtension` — the relocated body of the pre-Phase-223 `register_marketplace_usage` function (deleted from `backend/app/core/marketplace.py` in Plan 03).

Key contracts preserved verbatim from pre-Phase-223 core code:
- `on_startup` reads `AWS_MARKETPLACE_PRODUCT_CODE` via `os.environ.get`; returns immediately if unset (D-13 community no-op gate)
- `asyncio.to_thread(self._register_usage, ...)` bridges the sync boto3 call to the async lifespan
- `boto3` and `structlog` imports are **inline** inside `_register_usage` (not module-top) — community deployments without the env var never trigger the import
- `Nonce=str(uuid.uuid4())` idempotency token preserved verbatim
- `signature=resp.get("Signature", "")[:32] + "..."` log redaction preserved verbatim

Commit: `b8c8bce` (geolens-enterprise repo)

### Task 2: register_extensions amendment + pyproject.toml (geolens-enterprise repo)

`geolens_enterprise/__init__.py:register_extensions` amended with:
- Phase 223 D-06 docstring note
- Local import of `DefaultBillingExtension` from `app.platform.extensions.defaults`
- `billing_extensions = registry.setdefault("billing_extensions", [DefaultBillingExtension()])` followed by `billing_extensions.append(_get_billing_extension())`
- New `_get_billing_extension()` lazy-import helper mirroring the existing `_get_saml_extension` / `_get_audit_extension` / `_get_branding_extension` pattern

`pyproject.toml` dependencies amended (alphabetical insertion):
```toml
dependencies = [
    "boto3>=1.35.0",
    "defusedxml>=0.7.1",
    "pysaml2>=7.5.4",
]
```

End-to-end registration verified: `registry["billing_extensions"]` = `[DefaultBillingExtension(), MarketplaceBillingExtension()]` (length 2, correct types, correct order).

Commit: `e5622e9` (geolens-enterprise repo)

### Task 3: test_enterprise_overlay_register_pattern (core repo)

8th test appended to `backend/tests/test_billing_extension.py`. Simulates `geolens_enterprise.register_extensions` setdefault+append idiom inline using `EnterpriseShapeBillingExtension` fixture class — no geolens-enterprise installation required. Asserts:
- (a) `_extensions["billing_extensions"]` is a 2-element list `[Default, Enterprise]` after simulated registration
- (b) `get_billing_extensions()` returns a defensive copy (not the slot itself)
- (c) Dispatch loop awakens both extensions (Default no-op + fixture appends app arg)
- Pitfall C guard: overwrite idiom `registry["billing_extensions"] = [...]` would leave `len=1` and fail this assertion

All 8 tests pass GREEN. Ruff clean.

Commit: `b36040df` (core repo)

### Task 4: REQUIREMENTS.md BILLING-03 + ROADMAP.md SC#1 amendments (core repo)

**REQUIREMENTS.md BILLING-03** (was `[x]`, now `[ ]` — checkbox restored to unchecked pending BILLING-06 audit verification):

OLD: `` `boto3` is removed from `backend/pyproject.toml` dependencies. Only the enterprise overlay declares it. ``

NEW (D-01): ``No module under `backend/app/` calls `boto3.client("meteringmarketplace").register_usage(...)`. The AWS Marketplace billing API is invoked exclusively from the enterprise overlay's `BillingExtension.on_startup()`. `boto3` remains in `backend/pyproject.toml` because the core S3 storage provider (`app.platform.storage.s3`) and the lifespan S3 health check use it — that is an unrelated boundary concern out of scope for v13.3.``

**ROADMAP.md Phase 223 SC#1** amended in parallel. Surrounding SCs 2-4 and BILLING-02/04/BILLING-05 requirements preserved.

Commit: `2cb48992` (core repo)

## Cross-Repo Commit Summary

| Repo | Commit | Description |
|------|--------|-------------|
| geolens-enterprise | b8c8bce | feat(223-05): add MarketplaceBillingExtension overlay class |
| geolens-enterprise | e5622e9 | feat(223-05): register billing_extensions via setdefault+append + boto3 dep |
| geolens (core) | b36040df | test(223-05): add test_enterprise_overlay_register_pattern (8th test) |
| geolens (core) | 2cb48992 | docs(223-05): amend BILLING-03 + ROADMAP SC#1 per D-01 |

## Phase 223 Cumulative BILLING Requirements Status

| Req | Plan | Status | Verification |
|-----|------|--------|--------------|
| BILLING-01 | 223-01 | SATISFIED | Protocol shape + no-op default + accessor lazy fallback (3 tests) |
| BILLING-02 | 223-03 + 223-04 | SATISFIED | core/marketplace.py deleted; architecture guard in test_layering.py + make billing-extraction-discipline |
| BILLING-03 (amended) | 223-05 | SATISFIED | No meteringmarketplace call in backend/app/ — verified by Plan 04 grep guard + Plan 03 file deletion |
| BILLING-04 | 223-02 | SATISFIED | Lifespan dispatch loop with asyncio.wait_for(timeout=10.0) per extension; 3 dispatch tests + architecture guard |
| BILLING-05 | 223-03 | SATISFIED | aws_marketplace_* fields removed from Settings; test_settings_has_no_marketplace_fields |
| BILLING-06 | 223-05 Task 5 | **PENDING /oc-audit re-run** | Human gate — awaiting /oc-audit |

## BILLING-06 Close Gate Status

**PENDING.** Task 5 (`checkpoint:human-action`) gates BILLING-06 on an `/oc-audit` re-run that must report:
- Boundary Integrity grade: **A+** (currently A; Phase 222 + Phase 223 combined target)
- §1 loci `api/main.py:184-203`, `core/marketplace.py:1-30`, `core/config.py:87-88`: all **✅ Closed**
- No new 🔴 / 🟠 / 🟡 violations introduced by Phase 223

Pre-flight checks (a)-(h) defined in Task 5 `how-to-verify` section must all pass before running `/oc-audit`.

When the audit grade is confirmed, BILLING-06 is satisfied and Phase 223 is COMPLETE.

## Deviations from Plan

None — plan executed exactly as written. The cross-repo task ordering (Plans 01-04 first, overlay Plan 05 last) was respected per D-14.

## Known Stubs

None. The `MarketplaceBillingExtension` class is fully implemented with the relocated 30-line body from the pre-Phase-223 `register_marketplace_usage` function. The conditional gate (`if not product_code: return`) preserves the community no-op behavior exactly.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced. The `AWS_MARKETPLACE_PRODUCT_CODE` env var ownership moved from core Settings to the overlay's `os.environ.get` — env var name unchanged, only the consumer changed.

## Handoff Note

The `BillingExtension` Protocol seam delivered across Phase 223 Plans 01-05 is the foundation for BILLING-FUTURE-01 (Stripe / per-deployment metering, Cloud-tier prerequisite). Future billing overlays plug into the same `_extensions["billing_extensions"]` list slot via `setdefault + append` without any core changes. The dispatch loop in `api/main.py` handles timeout isolation for all registered extensions uniformly.

After BILLING-06 is verified by the `/oc-audit` re-run, the v13.3 milestone close action is:
1. Cite the new dated audit doc filename + grade in STATE.md
2. Create/update the milestone close artifact under `docs-internal/audits/` (gitignored)
3. Tag v13.3 in both repos

## Self-Check

- [x] `~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py` exists with `MarketplaceBillingExtension`
- [x] `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` contains `billing_extensions` setdefault+append
- [x] `~/Code/geolens-enterprise/pyproject.toml` contains `boto3>=1.35.0`
- [x] `.planning/REQUIREMENTS.md` BILLING-03 amended per D-01 (unchecked pending audit)
- [x] `.planning/ROADMAP.md` Phase 223 SC#1 amended per D-01
- [x] `backend/tests/test_billing_extension.py` has 8 tests, all GREEN
- [ ] BILLING-06: pending `/oc-audit` re-run (Task 5 checkpoint)
