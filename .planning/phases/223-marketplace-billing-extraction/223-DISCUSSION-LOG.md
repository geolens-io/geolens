# Phase 223: marketplace-billing-extraction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-30
**Phase:** 223-marketplace-billing-extraction
**Areas discussed:** boto3 removal scope (CRITICAL), Settings placement (BILLING-05), BillingExtension Protocol shape, Behavior preservation (timeout/error handling)
**Mode:** interactive selection of areas; user directed "Pick reasonable, best practice answers for all of your questions" → Claude picked the recommended option per area without per-area follow-up question turns.

---

## boto3 removal scope (CRITICAL spec amendment)

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Marketplace-only scope; reword SC#1 | boto3 stays in core for S3 storage; reframe SC#1 as "no AWS billing API call from core". | ✓ |
| (b) Move S3 to overlay too | Expand phase scope to relocate S3 storage from core to enterprise overlay. | |
| (c) Replace S3 boto3 with aiobotocore/minio | Swap the SDK in core S3 storage. | |
| (d) Make boto3 an `[s3]` optional extra | `pip install -e .[s3]` for S3 deployments. | |

**Claude's pick (best-practice default at user's direction):** (a). The audit doc explicitly scopes the 🟡 risk to the three marketplace loci and does NOT flag S3-related boto3 use; SC#1's literal wording is incompatible with current core S3 storage which is a community feature. Options (b)/(c)/(d) are unrelated significant work without architectural payoff for the v13.3 boundary goal. The architectural concern Phase 223 addresses is "AWS Marketplace API not invoked from core" — solved without removing boto3 from pyproject.toml.

**Notes:** This decision required amending the spec wording in REQUIREMENTS.md (BILLING-03) and ROADMAP.md (Phase 223 SC#1) as part of the phase plan. The plan-phase agent must include explicit edits to those two docs. See CONTEXT.md D-01.

---

## Settings placement (BILLING-05)

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Move to enterprise overlay's settings | Remove from core Settings; overlay reads via `os.environ.get` or its own Pydantic class. | ✓ |
| (b) Keep as opaque pass-through env vars in core Settings | Fields stay on core `Settings` but are inert in community. | |

**Claude's pick (best-practice default at user's direction):** (a). BILLING-05 explicitly states (a) is "preferred"; (b) is the "acceptable carve-out". Phase 217 SAML overlay precedent supports (a) — SAML-specific env vars are read by the overlay, not added to core `Settings`. Keeping unused fields in core `Settings` for an enterprise feature is unnecessary surface area and violates the cleanest boundary.

**Notes:** `aws_marketplace_product_code: str | None = None` (line 87), `aws_marketplace_public_key_version: int = 1` (line 88), and the `aws_marketplace_product_code` entry in the `field_validator` whitelist (line 108) are all deleted from `core/config.py`. `.env.example` lines 348-356 are restructured to mark these env vars as enterprise-overlay-only.

---

## BillingExtension Protocol shape

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Single-slot like BrandingExtension | One slot, single accessor `get_billing_extension()`, single default. | |
| (b) List-shape like AuditSink | List slot at `_extensions["billing_extensions"]`, list accessor `get_billing_extensions()`, lazy default `[DefaultBillingExtension()]`. | ✓ |

**Sub-decisions (also picked best-practice):**
- on_startup-only or on_startup + on_shutdown? **on_startup-only.** BILLING-01 says "at least on_startup"; on_shutdown is YAGNI for AWS register_usage which has no shutdown semantics.
- Async or sync? **Async-only.** Lifespan is already async; matches Phase 222 D-03 precedent; future overlays may need non-blocking I/O.
- Hook signature `app: FastAPI` vs `app: object`? **Recommend `app: FastAPI`** with `app: object` fallback if planner discovers an unexpected import cycle (precedent: Phase 222 added `AsyncSession` import to `protocols.py` for the same reason).

**Claude's pick (best-practice default at user's direction):** (b) list-shape. BILLING-04's spec text uses plural naming (`get_billing_extensions()`) and a `for ext in ...:` loop — a list-shape signal. Mirrors Phase 222 D-09/D-10/D-11 verbatim, giving the codebase one consistent "extension dispatch with isolation" idiom rather than two patterns. Multi-billing today is implausible (you don't run AWS Marketplace AND Stripe simultaneously), but list shape is forward-compatible at no real cost.

**Notes:** `DefaultBillingExtension.on_startup(self, app)` body is literally `return` (no-op). The dispatch loop in `api/main.py` uses `for ext in get_billing_extensions(): try: await asyncio.wait_for(ext.on_startup(app), timeout=10.0): except: ...` — see Behavior preservation below for the full pattern.

---

## Behavior preservation (timeout/error handling)

| Option | Description | Selected |
|--------|-------------|----------|
| (a) All in overlay | BillingExtension.on_startup applies its own timeout, swallows its own exceptions; core just `await ext.on_startup(app)`. | |
| (b) Core wraps the dispatch | Core dispatch loop wraps each extension with `asyncio.wait_for(timeout=10.0)` + try/except (TimeoutError + Exception). Overlay's on_startup is naive. | ✓ |
| (c) Hybrid | Core wraps with try/except; timeout is overlay's responsibility. | |

**Claude's pick (best-practice default at user's direction):** (b). Mirrors Phase 222 D-06 facade pattern verbatim — per-sink try/except inside core dispatch. Every overlay automatically gets the safety net (no overlay can crash startup; no overlay can hang it past 10s). Overlays stay simple. Operators learning the registry pattern see one consistent shape (Phase 222 audit_emit + Phase 223 dispatch loop are structurally identical).

**Sub-decisions (also picked best-practice):**
- Configurable timeout? **No, hardcoded 10s.** YAGNI; matches today's value at `api/main.py:191`.
- Conditional gate (`if AWS_MARKETPLACE_PRODUCT_CODE`) location? **Inside the overlay's `on_startup` body.** Core doesn't read or know about the env var; encapsulation belongs with the AWS-specific behavior.
- Circuit-breaking on N failures? **Out of scope.** Same as Phase 222 D-08 — per-emit/per-startup isolation, no quarantine.

**Notes:** Today's `api/main.py:184-203` has three concerns wrapped together (env-var gate, 10s timeout, non-fatal failure). After Phase 223: env-var gate moves to overlay's `on_startup`; 10s timeout and non-fatal failure stay in core's dispatch loop (now generic across all BillingExtensions). The `from app.core.marketplace import register_marketplace_usage` import at `api/main.py:20` is deleted along with the block.

---

## Claude's Discretion

User directed best-practice defaults across all four areas; Claude documented sub-decisions and discretion items inline in CONTEXT.md `<decisions>` and "Claude's Discretion" subsection. Specifically:

- `MarketplaceBillingExtension` internal organization (overlay-side) — single class vs split into helper module + class. Either acceptable; enterprise repo's organization concern.
- Overlay's settings layout — `os.environ.get` (recommended for simplicity) vs Pydantic `BillingSettings` class. Planner discretion.
- Test file location — `backend/tests/test_billing_extension.py` (new file, recommended) vs extending an existing extension-tests file.
- Makefile target name — `make billing-extraction-discipline` vs alternatives. Contract is "static + runtime check that the import path is gone", not the spelling.
- Single PR vs multi-PR partition — recommended 4-5 plans mirroring Phase 222.
- Whether `app: FastAPI` or `app: object` is the right Protocol signature — verify during plan-time research.
- Whether `_init_default_billing()` step is needed — recommend lazy-default in accessor (no init step), matching Phase 222 D-11.
- Dispatch loop's structlog context fields — `extension`, `timeout_seconds`/`error` recommended; planner finalizes.

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section — summarized:

- Replacing boto3 with aiobotocore/minio-py in core S3 storage (out of v13.3 — separate phase if ever needed)
- boto3 as `[project.optional-dependencies]` extra (rejected — option (d) of gray area 1)
- Stripe / per-deployment / per-seat billing (Cloud-tier; BILLING-FUTURE-01)
- Multi-tenant billing isolation (Phase 999.6 territory)
- Configurable `BILLING_STARTUP_TIMEOUT_SECONDS` env var (YAGNI)
- Per-extension timeout overrides (out of scope)
- Circuit-breaking / extension-quarantine on N failures (out of scope)
- `BillingExtension.on_shutdown(app)` hook (YAGNI; no current billing system needs it)
- Audit-export overlay billing events (BILLING-FUTURE territory)
- Renaming `BillingExtension` (locked to spec text)
- Unified registry-shape abstraction (YAGNI; same Phase 222 guidance)
- CHANGELOG entry generation (planner discretion at plan time)
