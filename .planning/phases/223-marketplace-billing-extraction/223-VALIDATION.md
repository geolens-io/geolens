---
phase: 223
slug: marketplace-billing-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-30
---

# Phase 223 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `223-RESEARCH.md` §"Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-anyio |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && uv run pytest tests/test_billing_extension.py tests/test_layering.py::test_no_core_marketplace_import -v` |
| **Full suite command** | `cd backend && uv run pytest --timeout=60` |
| **Estimated runtime** | ~5s quick / ~120s full |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green AND `make billing-extraction-discipline` exits 0 AND `/oc-audit` re-run reports ✅ Closed for the 3 §1 loci
- **Max feedback latency:** ~5s (quick) / ~120s (full)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 223-01-01 | 01 | 1 | BILLING-01 | — | BillingExtension Protocol contract present | unit | `cd backend && uv run pytest tests/test_billing_extension.py::test_billing_extension_protocol_shape -v` | ❌ W0 | ⬜ pending |
| 223-01-02 | 01 | 1 | BILLING-01 | — | DefaultBillingExtension is no-op | unit | `cd backend && uv run pytest tests/test_billing_extension.py::test_default_billing_extension_is_noop -v` | ❌ W0 | ⬜ pending |
| 223-02-01 | 02 | 2 | BILLING-04 | — | get_billing_extensions() returns [DefaultBillingExtension()] when slot missing | unit | `cd backend && uv run pytest tests/test_billing_extension.py::test_get_billing_extensions_default_fallback -v` | ❌ W0 | ⬜ pending |
| 223-02-02 | 02 | 2 | BILLING-04 | — | Multi-extension dispatch happy path | unit (anyio) | `cd backend && uv run pytest tests/test_billing_extension.py::test_dispatch_runs_all_registered_extensions -v` | ❌ W0 | ⬜ pending |
| 223-02-03 | 02 | 2 | BILLING-04 | T-223-01 | Raising extension does not crash dispatch loop | unit (anyio) | `cd backend && uv run pytest tests/test_billing_extension.py::test_raising_extension_isolated -v` | ❌ W0 | ⬜ pending |
| 223-02-04 | 02 | 2 | BILLING-04 | T-223-01 | Hanging extension is timed out at 10s | unit (anyio) | `cd backend && uv run pytest tests/test_billing_extension.py::test_hanging_extension_timeout -v` | ❌ W0 | ⬜ pending |
| 223-03-01 | 03 | 3 | BILLING-02 | — | `from app.core.marketplace import register_marketplace_usage` raises ImportError | architecture | `cd backend && uv run pytest tests/test_layering.py::test_no_core_marketplace_import -v` | ❌ W0 | ⬜ pending |
| 223-03-02 | 03 | 3 | BILLING-03 (amended) | — | No `register_usage` call in `backend/app/` | architecture (grep) | `cd backend && make billing-extraction-discipline` | ❌ W0 | ⬜ pending |
| 223-03-03 | 03 | 3 | BILLING-05 | — | `aws_marketplace_*` fields removed from Settings | unit | `cd backend && uv run pytest tests/test_billing_extension.py::test_settings_has_no_marketplace_fields -v` | ❌ W0 | ⬜ pending |
| 223-04-01 | 04 | 3 | BILLING-04 | — | Enterprise overlay registers MarketplaceBillingExtension via setdefault+append | integration | `cd backend && uv run pytest tests/test_billing_extension.py::test_enterprise_overlay_register_pattern -v` | ❌ W0 | ⬜ pending |
| 223-05-01 | 05 | 4 | BILLING-06 | — | `/oc-audit` re-run reports ✅ Closed for 3 §1 loci, Boundary Integrity grade A+ | manual | N/A — manual `/oc-audit` run | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are illustrative — final task IDs assigned by gsd-planner. The validation contract by Requirement is what's binding.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_billing_extension.py` — NEW FILE. Test classes: `TestBillingExtensionProtocol`, `TestDispatchLoop`, `TestSettingsRemoval`, `TestEnterpriseOverlayPattern`. Fixtures: `_extensions_billing_slot_save_restore` (yield-finally pattern from `test_audit_sink.py`).
- [ ] `backend/tests/test_layering.py` — EXTEND existing file with `test_no_core_marketplace_import` function (parallel to Phase 222's audit architecture guard).
- [ ] `backend/Makefile` — ADD `billing-extraction-discipline` target. Body: `@! grep -rn "from app.core.marketplace\|import app.core.marketplace" backend/app/ || (echo "BILLING-02 violation: core/marketplace imports detected" && exit 1)`. Update `.PHONY` line to include the new target.
- [ ] `~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py` — NEW FILE in enterprise repo with `MarketplaceBillingExtension` class. Cross-repo task; planner specifies cross-repo coordination order.
- [ ] `~/Code/geolens-enterprise/pyproject.toml` — ADD `boto3>=1.35.0` to dependencies array. Match core's pin (`boto3>=1.35.0` per `backend/pyproject.toml:29`).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Audit re-run grade A+ | BILLING-06 | `/oc-audit` is an interactive audit Skill that produces a dated audit doc; cannot be automated as a unit test | After all plans pass: run `/oc-audit` (or the equivalent in this project's harness). Verify the new audit doc reports ✅ Closed for the three §1 loci (`api/main.py:184-203`, `core/marketplace.py:1-30`, `core/config.py:87-88`) and Boundary Integrity grade A+. Cite the audit doc filename in `/gsd-verify-work` output. |
| Enterprise overlay end-to-end on a real container | SC#3 | Requires the full geolens-enterprise overlay loaded via `uv add --editable /enterprise` in the enterprise container; cannot be reproduced inside community pytest | Spin up the enterprise docker-compose with `GEOLENS_ENTERPRISE_PATH` set, set `AWS_MARKETPLACE_PRODUCT_CODE=test-product`, observe that `MarketplaceBillingExtension.on_startup` log line fires (or that the boto3 stub call would fire — use moto / mock if running outside AWS). Document the manual step in `/gsd-verify-work` output. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test file, test function, Makefile target, overlay file)
- [ ] No watch-mode flags
- [ ] Feedback latency ~5s quick / ~120s full
- [ ] `nyquist_compliant: true` set in frontmatter (after planner finalizes plan structure and verifies all task IDs map)

**Approval:** pending
