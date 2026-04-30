# Phase 223: marketplace-billing-extraction - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Mode:** interactive discuss with user-directed best-practice defaults (`--chain`)

<domain>
## Phase Boundary

Move the AWS Marketplace `register_usage` runtime call out of core into a `BillingExtension.on_startup(app)` overlay hook. After this phase the only path that constructs `boto3.client("meteringmarketplace")` lives inside the enterprise overlay (`geolens-enterprise/geolens_enterprise/billing/`); core's lifespan startup performs zero AWS Marketplace API calls and zero `import` of `app.core.marketplace`. The audit re-run reports `✅ Closed` for the three 🟡 loci (`api/main.py:184-203`, `core/marketplace.py:1-30`, `core/config.py:87-88`) and Boundary Integrity grade rises to A+.

Concretely after this phase:

- A new `BillingExtension` Protocol lives in `backend/app/platform/extensions/protocols.py` alongside `BrandingExtension`, `AuditExtension`, `AuthExtension`, `AuditSink`. Signature: `async def on_startup(self, app: FastAPI) -> None`. (Plan-time decision: import `FastAPI` directly or type as `object` — see D-09; precedent from `AuditSink`'s `AsyncSession` import is "import the type when SQLAlchemy/FastAPI doesn't import from `app.modules.*`".)
- A new `DefaultBillingExtension` lives in `backend/app/platform/extensions/defaults.py` whose `on_startup()` is a literal no-op (`async def on_startup(self, app): return`). This satisfies BILLING-01's "Community default is no-op" contract and gives the dispatch loop a uniform iteration target.
- A new typed accessor `get_billing_extensions() -> list[BillingExtension]` lives in `backend/app/platform/extensions/__init__.py`, mirroring `get_audit_sinks()` from Phase 222 D-10 verbatim (list shape, lazy default `[DefaultBillingExtension()]` when the slot is missing).
- The lifespan block at `backend/app/api/main.py:184-203` is replaced with a generic dispatch loop that mirrors Phase 222's per-sink try/except + `structlog` facade pattern: each registered `BillingExtension.on_startup(app)` is awaited inside `asyncio.wait_for(..., timeout=10.0)` with separate `TimeoutError` and general `Exception` handlers that log via `structlog` warning and continue. The `from app.core.marketplace import register_marketplace_usage` import at `api/main.py:20` is deleted.
- `backend/app/core/marketplace.py` is **deleted** (file removed from the repo). Its 30-line body (the `register_marketplace_usage` function with the inline `import boto3` + `boto3.client("meteringmarketplace").register_usage(...)` body) moves verbatim into the enterprise overlay's `geolens_enterprise/billing/__init__.py` (or co-located in a `MarketplaceBillingExtension` class — overlay-side organization is the enterprise repo's concern, but the class registers as `BillingExtension`).
- `backend/app/core/config.py:87-88, 108` — the two AWS Marketplace fields (`aws_marketplace_product_code`, `aws_marketplace_public_key_version`) are **removed from core `Settings`**. They become enterprise-overlay-owned env vars read directly via `os.environ.get(...)` (or by the overlay's own Pydantic `BillingSettings` class — overlay-side decision). The `field_validator` entry for `aws_marketplace_product_code` at `config.py:108` is dropped along with the field. `.env.example` lines 350-356 (the AWS Marketplace section) are restructured: env vars are documented as enterprise-only with a clear "set only when running geolens-enterprise overlay" header (the env vars are still read by the overlay; documentation must reflect the new ownership without misleading community operators into thinking the var does anything).
- The enterprise overlay's `geolens_enterprise/__init__.py:register_extensions(registry)` registers the `MarketplaceBillingExtension` instance under `_extensions["billing_extensions"]` using the documented `setdefault + append` idiom: `registry.setdefault("billing_extensions", [DefaultBillingExtension()]).append(MarketplaceBillingExtension())`. **Critical:** overlay code must import `DefaultBillingExtension` from `app.platform.extensions.defaults` for this to work — overlays already do this for sibling Protocols, but the enterprise repo's diff is part of phase scope and must be coordinated (sibling-repo amendment per `feedback_audit_sibling_repos_at_milestone_close.md`).
- A new test file at `backend/tests/test_billing_extension.py` (or extending `backend/tests/test_extensions.py` if a clean home exists) verifies BILLING-04 end-to-end with a fixture-based pattern mirroring Phase 222 D-12: a `FixtureBillingExtension` class is registered by directly appending to `_extensions["billing_extensions"]`; a startup-equivalent dispatch is exercised; assertions confirm the fixture's `on_startup` ran AND the dispatch survived a `RaisingBillingExtension` whose `on_startup` raises (mirrors Phase 222 D-13 sink-failure verification).
- A startup-import architecture-guard test (extending `backend/tests/test_layering.py` or its sibling pattern) asserts that `app.core.marketplace` does NOT exist as a module under `backend/app/` and that `from app.core.marketplace` produces an `ImportError` after this phase. This is the BILLING-02 invariant guard, parallel to Phase 222's `make audit-sink-discipline` target.
- The post-phase audit re-run (`/oc-audit` run after both Phase 222 and Phase 223 ship) reports `✅ Closed` for all three 🟡 loci in §1 and Boundary Integrity grade A+ (BILLING-06).

**In scope:**
- New `BillingExtension` Protocol in `backend/app/platform/extensions/protocols.py` (`async def on_startup(self, app: FastAPI) -> None`).
- New `DefaultBillingExtension` (no-op) in `backend/app/platform/extensions/defaults.py`.
- New `get_billing_extensions() -> list[BillingExtension]` typed accessor in `backend/app/platform/extensions/__init__.py` (mirrors `get_audit_sinks` shape).
- Replace `backend/app/api/main.py:184-203` with a generic dispatch loop using `asyncio.wait_for(..., timeout=10.0)` + per-extension try/except (mirrors Phase 222 facade pattern); delete the `from app.core.marketplace import register_marketplace_usage` import at `api/main.py:20`.
- Delete `backend/app/core/marketplace.py` from the core repo.
- Remove `aws_marketplace_product_code` and `aws_marketplace_public_key_version` from `backend/app/core/config.py:Settings` (and the matching `field_validator` entry).
- Update `.env.example` to document the AWS Marketplace env vars as enterprise-only (not core Settings fields).
- Move `register_marketplace_usage` body verbatim into the enterprise overlay (`~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py` and a `MarketplaceBillingExtension` class registered in `register_extensions`). **Cross-repo:** this requires changes in BOTH `geolens` and `geolens-enterprise` repos.
- Add `boto3` to the enterprise overlay's `pyproject.toml` dependencies (currently only `pysaml2` and `defusedxml`); the enterprise overlay's CI test job already has access to it implicitly via core, but the overlay's own dep manifest must declare it after this phase since core may eventually drop it.
- Architecture-guard test: `from app.core.marketplace import ...` raises `ImportError` (BILLING-02 invariant).
- Fixture-based BillingExtension test in `backend/tests/`: mirrors Phase 222 D-12+D-13 (multi-extension dispatch + raising-extension survival).
- Amend `.planning/REQUIREMENTS.md` BILLING-03 wording AND `.planning/ROADMAP.md` Phase 223 SC#1 to reflect the carve-out: boto3 stays in core's `pyproject.toml` because S3 storage uses it; the architectural goal is "AWS Marketplace metering API is never invoked from core code". See D-01 for the full reframing.
- Audit re-run verification: BILLING-06 satisfied — Boundary §1 reports ✅ Closed for all 3 loci.

**Out of scope:**
- Any new billing systems (Stripe, Paddle, OEM-specific) — those are post-v13.3 if/when they happen. `BillingExtension` Protocol is forward-compatible (list-shape); future overlays plug in additively without touching core.
- Replacing `boto3` with `aiobotocore`, `minio-py`, or any other S3 SDK in core — `boto3` stays in core for S3 storage; that's documented as a separate boundary concern that Phase 223 explicitly does NOT take on. Discussed and rejected (option-c in the gray-area discussion) — replacing S3 SDKs is unrelated work.
- Making `boto3` a `[project.optional-dependencies]` extra (`pip install -e .[s3]`) — discussed and rejected (option-d). Forces every S3 deployment to install with extras flag, breaks existing CI/install scripts, and the actual architectural concern (Marketplace API in core) is solved without this.
- Tenant scoping, multi-tenant billing, per-deployment metering — these are Phase 999.6 / Cloud-tier territory (BILLING-FUTURE-01).
- Stripe / per-deployment / per-seat billing — Cloud-tier prerequisite, deferred per REQUIREMENTS.md.
- Refactoring or renaming `app.platform.storage.s3.S3StorageProvider` — untouched; it imports `boto3` directly (line 28) and that's fine post-phase.
- Modifying the S3 health check at `api/main.py:155-182` — untouched; it imports `boto3` (line 161) and that's fine post-phase.
- Modifying the worker's S3 credential probe at `app.platform.jobs.worker.py:184` — untouched; lazy `import boto3 as _boto3` stays.

</domain>

<decisions>
## Implementation Decisions

> **All four selected gray areas were resolved with best-practice defaults at the user's direction ("Pick reasonable, best practice answers").** The reasoning behind each pick is explicit so downstream agents (researcher, planner) can adapt if they discover a constraint that changes the trade-off.

### Gray area 1 — boto3 removal scope (CRITICAL spec amendment)

- **D-01: BILLING-03 and Phase 223 SC#1 are AMENDED in this phase to reflect the actual architectural concern.** Original wording: "boto3 is removed from `backend/pyproject.toml` dependencies. Only the enterprise overlay declares it." / "`import boto3` produces an ImportError in a clean community virtualenv." Amended wording: **"`backend/app/core/marketplace.py` is deleted from core. No module under `backend/app/` calls `boto3.client('meteringmarketplace').register_usage(...)`. The AWS Marketplace billing API is invoked exclusively from the enterprise overlay's `BillingExtension.on_startup()`. `boto3` remains a core `pyproject.toml` dependency because the core S3 storage provider (`app.platform.storage.s3`) and the lifespan S3 health check at `api/main.py:155-182` use it; that is an unrelated boundary concern out of scope for v13.3."**

  Rationale: scout discovered three additional `boto3` import sites in core that are NOT marketplace: `app/platform/storage/s3.py:28` (S3StorageProvider — the core S3 storage backend, used by every deployment with `storage_provider=s3`), `app/api/main.py:161` (S3 health check — verifies S3 connectivity at startup), `app/platform/jobs/worker.py:184` (worker S3 credential probe). The audit doc (`docs-internal/audits/oc-separation-audit-20260430.md` §1) **explicitly** scopes the 🟡 risk to the three marketplace loci and does NOT flag S3-related `boto3` use. Removing `boto3` from core entirely would require either (a) replacing the S3 SDK with `aiobotocore`/`minio-py` (unrelated significant work), or (b) making `boto3` an optional extra (forces every S3 deployment to install with `[s3]` flag, breaks docs/CI, no architectural payoff). Both rejected. The architectural goal — "AWS Marketplace metering API call is not invoked from core" — is fully achieved by D-02 through D-09 below; the boto3-in-pyproject letter of SC#1 is amended to match the audit's scoping.

  **Plan deliverable:** the plan-phase agent must include explicit edits to `.planning/REQUIREMENTS.md` BILLING-03 and `.planning/ROADMAP.md` Phase 223 SC#1 with the amended wording above. This is part of phase scope, not a separate doc-update phase.

- **D-02: `backend/app/core/marketplace.py` is deleted, not relocated to a different core path.** No `core/billing/`, no `core/marketplace_legacy.py`, no commented-out body. The 30-line function moves verbatim into the enterprise overlay (`~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py` or the `MarketplaceBillingExtension.on_startup` body). The `from app.core.marketplace import register_marketplace_usage` line at `api/main.py:20` is deleted; the architecture-guard test asserts the import is unavailable after this phase.

  Rationale: BILLING-02's literal text is "core/marketplace.py is removed from core". Keeping a stub in core for any reason (backward compat, transition aid) would defeat BILLING-06's audit-re-run-clean criterion. Clean delete; clean audit.

### Gray area 2 — Settings placement (BILLING-05)

- **D-03: `aws_marketplace_product_code` and `aws_marketplace_public_key_version` are REMOVED from `backend/app/core/config.py:Settings`.** These two fields (lines 87-88) and the corresponding `aws_marketplace_product_code` entry in the `field_validator` whitelist (line 108) are deleted. Community core has zero references to AWS Marketplace settings post-phase.

  Rationale: BILLING-05's "preferred" option is overlay-only placement; the alternative (keep as opaque pass-through env vars in core Settings) is documented as "acceptable carve-out" but the user directed best-practice defaults. The overlay-only path is the architecturally cleanest one and matches Phase 217 SAML's pattern (SAML-specific env vars are read by the overlay, not added to core `Settings`). Two extra fields in core for a feature core doesn't ship is unnecessary surface area; the field_validator whitelist entry is also extra noise.

- **D-04: The enterprise overlay reads its AWS Marketplace env vars directly via `os.environ.get(...)` inside `MarketplaceBillingExtension.__init__` (or a similar one-off pattern).** Recommendation only — the overlay can choose to ship its own `BillingSettings` Pydantic class if it wants typed validation/defaults. Either pattern is acceptable to the core repo because core no longer cares; the overlay's choice is documented in the overlay repo, not here.

  Rationale: the overlay has full freedom on its own settings layout. `os.environ.get` is the simplest path with no new Pydantic Settings class needed. Either way, the overlay's `MarketplaceBillingExtension.on_startup` short-circuits when `AWS_MARKETPLACE_PRODUCT_CODE` is unset — preserving today's "inert when env var unset" behavior contract.

- **D-05: `.env.example` lines 348-356 (the AWS Marketplace section) are restructured.** The AWS Marketplace env vars are documented under a clearly-marked "**Enterprise overlay only**" header that explains the vars are read by the enterprise overlay's `MarketplaceBillingExtension` and have no effect on community deployments. Today's wording (`# AWS Marketplace metering — only relevant when running on AWS Marketplace`) is updated to clarify the enterprise-only-overlay reality.

  Rationale: documenting a community env var that does nothing is a foot-gun; community operators will set it expecting metering and get silent inaction. Clearly labeling it "enterprise overlay only" prevents the foot-gun while preserving discoverability for enterprise operators reading `.env.example`.

### Gray area 3 — `BillingExtension` Protocol shape

- **D-06: `BillingExtension` is a list-shape registry slot at `_extensions["billing_extensions"]` (plural), mirroring Phase 222 D-09 / D-10 / D-11 exactly.** Accessor: `get_billing_extensions() -> list[BillingExtension]`. Default lazy fallback: `[DefaultBillingExtension()]` when the slot is missing. Enterprise overlay registers via `registry.setdefault("billing_extensions", [DefaultBillingExtension()]).append(MarketplaceBillingExtension())`.

  Rationale: BILLING-04's spec text says `for ext in get_billing_extensions(): ext.on_startup(app)` — the plural naming and iteration loop are list-shape. Multi-billing today is implausible (you don't run AWS Marketplace AND Stripe simultaneously), but the list shape is forward-compatible if a future overlay wants to register a billing-event sink alongside a primary biller (e.g., audit-trail-style billing events). Cost of list shape over single-slot is one extra `[]` of syntax; benefit is symmetry with `AuditSink` (operators learning the registry pattern see one shape, not two), and zero refactor cost if multi-billing ever happens.

- **D-07: `DefaultBillingExtension` is a no-op class in `backend/app/platform/extensions/defaults.py`.** Body:
  ```python
  class DefaultBillingExtension:
      """Community default — no-op startup hook."""
      async def on_startup(self, app) -> None:
          return
  ```
  Mirrors `DefaultAuditExtension`/`DefaultIdentityExtension`/etc. Returns immediately; touches no globals. Lives alongside the existing four defaults.

  Rationale: BILLING-01 says "Community default is no-op". A bare no-op class is the cleanest way to make the dispatch loop iterate over a non-empty list (`[DefaultBillingExtension()]`) so the iteration shape is uniform across community and enterprise. Empty-list-as-default would also work but breaks symmetry with the four existing single-slot Protocols (each has a `Default*` class).

- **D-08: `BillingExtension.on_startup` is async-only.** Signature: `async def on_startup(self, app: FastAPI) -> None`. No sync overload. The lifespan startup is already `async def lifespan(...)`; awaiting `on_startup` drops in naturally; future overlays may want to do non-blocking I/O (HTTP calls to billing APIs, async DB writes for audit) and async-only leaves the door open. Mirrors Phase 222 D-03 verbatim.

  Rationale: zero migration cost (existing call site at `api/main.py:184-203` is already async via `asyncio.to_thread` for the sync boto3 call). Async also means the overlay can do `await asyncio.to_thread(boto3_call, ...)` inside its `on_startup` body — same pattern as today, just relocated.

- **D-09: Hook signature is `async def on_startup(self, app: FastAPI) -> None`.** Plan-time decision: import `FastAPI` from `fastapi` at the top of `protocols.py` (FastAPI already does NOT import from `app.modules.*` — sibling to the `AsyncSession` import added in Phase 222). If the planner discovers an unexpected import cycle, fall back to typing the param as `app: object` and runtime-cast inside any consumer; either is acceptable.

  Rationale: typed `FastAPI` parameter gives overlays autocomplete + type-check coverage when calling `app.state.foo`, `app.add_event_handler(...)`, etc. The existing `AsyncSession` import in `protocols.py` (added Phase 222) is precedent — types from libraries that don't pull in `app.modules.*` are safe to import.

### Gray area 4 — Behavior preservation (timeout/error handling)

- **D-10: Core dispatch in `api/main.py` wraps each extension's `on_startup` with `asyncio.wait_for(..., timeout=10.0)` + try/except (TimeoutError + general Exception, both warned + non-fatal).** Mirrors Phase 222 D-06 facade pattern verbatim. The 10s timeout cap prevents a hung overlay from blocking container startup for ~3 minutes (today's risk mitigation against the boto3 sync `register_usage` 3x-retry-60s pattern). Each failure is logged via `structlog` warning with `extension=type(ext).__name__` for operator visibility.

  Pseudocode:
  ```python
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

  Rationale: keeping the timeout + non-fatal contract in core's dispatch loop means (a) every overlay automatically gets the safety net (no overlay can crash startup; no overlay can hang it past 10s), (b) overlays stay simple — `on_startup` body is "naive" and just does the work, (c) parallels Phase 222 D-06 (per-sink try/except in the facade) so the codebase has one consistent "extension dispatch with isolation" idiom. The conditional gate (`if AWS_MARKETPLACE_PRODUCT_CODE is set`) lives inside the overlay's `on_startup` body — that's where the env-var check belongs (next to the AWS-specific behavior). Today's `if settings.aws_marketplace_product_code:` block at `api/main.py:184` becomes `if not os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE"): return` inside the overlay.

- **D-11: The 10-second timeout is hardcoded in core's dispatch loop, not configurable.** No `BILLING_STARTUP_TIMEOUT_SECONDS` env var, no per-extension timeout override. Today's value is hardcoded at `api/main.py:191` (`timeout=10.0`); preserving that as a constant in core is the smallest-diff option and matches the existing behavior.

  Rationale: making it configurable invites bikeshedding (default value? per-overlay override? overall vs per-overlay?) without any operator demand. If a future overlay needs more than 10s for legitimate startup work, the right fix is to lift the work out of `on_startup` into a background task, not to extend the timeout. YAGNI.

- **D-12: Sink-failure scope is per-extension, per-startup.** The dispatch loop processes all registered `BillingExtension`s for ONE startup; if any fails, the others still run. No circuit-breaking, no quarantine, no "disable on N failures" — same out-of-scope rules as Phase 222 D-08 advanced semantics.

  Rationale: simplest implementation that satisfies the contract; matches Phase 222 precedent; operators looking for circuit-breaking can build it inside their overlay's `on_startup` body.

- **D-13: The conditional gate (`if AWS_MARKETPLACE_PRODUCT_CODE` set) lives in the OVERLAY, not in core.** Today's `if settings.aws_marketplace_product_code:` at `api/main.py:184` is **deleted** along with the rest of that block. The overlay's `MarketplaceBillingExtension.on_startup` opens with `if not os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE"): return`. This preserves today's behavior contract (community deployments with the env var unset perform zero AWS API calls) without core needing to know about the env var.

  Rationale: keeping the env-var check next to the env-var-using code is the correct encapsulation. Core doesn't read `AWS_MARKETPLACE_PRODUCT_CODE`; only the overlay does. SC#2 ("community deployment with AWS_MARKETPLACE_PRODUCT_CODE unset performs zero AWS API calls and imports zero boto3 symbols at startup") is satisfied by the combination of (a) `core/marketplace.py` deleted, (b) the import in `api/main.py:20` deleted, (c) the conditional gate in the overlay's `on_startup` skipping the boto3 call when env var unset, and (d) the overlay only being installed when the operator opts into the enterprise overlay (so community installs literally don't have the overlay's `on_startup` to run).

### Cross-repo coordination

- **D-14: Phase 223 spans BOTH `geolens` (core) and `geolens-enterprise` (overlay) repos.** Core repo changes: D-02 (delete `core/marketplace.py`), D-03 (remove Settings fields), D-05 (.env.example update), D-06 (Protocol + accessor), D-07 (default), D-09 (signature), D-10 (dispatch loop), test changes, doc amendments (D-01 SC reword). Enterprise repo changes: add `MarketplaceBillingExtension` class implementing `BillingExtension`, add registration in `geolens_enterprise/__init__.py:register_extensions`, add `boto3>=1.35.0` to `geolens-enterprise/pyproject.toml` dependencies, port the `register_marketplace_usage` body into the new class. The `feedback_audit_sibling_repos_at_milestone_close.md` carve-out is directly relevant: Phase 223 close MUST verify the enterprise repo has the matching commits before declaring the phase complete.

  Rationale: the boundary fix is fundamentally a relocation across repos. Doing only the core side leaves the marketplace functionality unimplemented in any deployment; doing only the enterprise side leaves the core 🟡 loci unfixed. The plan-phase agent must produce a plan with explicit cross-repo task ordering: (1) enterprise repo gets the new `MarketplaceBillingExtension` class first (so the entry-point is loadable when core looks for it), (2) core repo deletes the old code in a single commit cluster, (3) integration test verifies both halves work together with the overlay installed.

### Test strategy (verifies BILLING-04 end-to-end)

- **D-15: Fixture-based extension test pattern from Phase 222 D-12 is reused.** New test file `backend/tests/test_billing_extension.py` (or extending an existing extension-tests file at planner discretion). Tests:

  1. **Multi-extension dispatch (BILLING-04 happy path):** Register a `FixtureBillingExtension` whose `on_startup` appends to an instance-level `received: list[FastAPI]`; trigger the lifespan dispatch (or inline-call the dispatch loop directly with a TestClient app); assert `fixture.received == [app]`.
  2. **Raising-extension survival (D-12 / D-10):** Register a `RaisingBillingExtension` whose `on_startup` raises `RuntimeError`; assert the dispatch survives, the warning log line is emitted (via `caplog` or `structlog.testing.capture_logs`), and any subsequent extension in the list still runs.
  3. **Timeout survival (D-10):** Register a `HangingBillingExtension` whose `on_startup` sleeps `15.0` seconds; assert the dispatch returns within ~11s (10s timeout + epsilon), the timeout warning is logged, and subsequent extensions still run.
  4. **Default-only community case:** With no overlay registered, assert `get_billing_extensions()` returns `[DefaultBillingExtension()]` and the dispatch loop runs the no-op without error.

  Test fixtures restore `_extensions["billing_extensions"]` to its pre-test state in a `try/finally` (mirrors Phase 222 D-12 fixture-cleanup pattern; reference implementation lives in `backend/tests/test_lifecycle.py` from Phase 220 / Phase 222).

- **D-16: Architecture-guard test (BILLING-02 invariant).** A new test in `backend/tests/test_layering.py` (or extending the Phase 222 audit-discipline pattern) asserts `from app.core.marketplace import register_marketplace_usage` raises `ImportError` after this phase. The Makefile target `make billing-extraction-discipline` (or a similar target — planner finalizes the name) wraps this assertion + a `grep -r "from app.core.marketplace" backend/app/` check that returns zero matches. Mirrors Phase 222 D-23 / `make audit-sink-discipline`.

  Rationale: BILLING-02 is a structural invariant — "core/marketplace.py is removed from core". Tests prove the absence at runtime; the Makefile target proves it at static-analysis time. Two-layer guard prevents accidental regression if a future commit adds back the import.

- **D-17: BILLING-06 (audit re-run clean) is verified by running `/oc-audit` after both Phase 222 and Phase 223 ship.** The audit re-run produces a new dated audit doc (e.g., `docs-internal/audits/oc-separation-audit-20260501.md`) which must report `✅ Closed` for the three 🟡 loci AND a Boundary Integrity grade of A+ (currently A). The plan-phase agent makes this an explicit verification step in the phase plan, not a separate phase; it's the close gate for v13.3.

  Rationale: BILLING-06 is fundamentally an audit-driven success criterion. Running the audit IS the verification. The audit doc lives in `docs-internal/audits/` (gitignored per project memory) — it doesn't need to ship to the public repo, but the grade improvement does need to be cited in the v13.3 close artifact and STATE.md.

### Claude's Discretion

- **`MarketplaceBillingExtension` internal organization (overlay-side)** — whether the overlay defines a single class with `on_startup` body inlining the boto3 call, or splits it into a helper module + class. Either is acceptable; this is the enterprise repo's organization concern.
- **`BillingSettings` Pydantic class vs `os.environ.get` in the overlay** — D-04 recommends `os.environ.get` for simplicity but the overlay can ship a Pydantic Settings class if a future second billing env var lands. Planner discretion.
- **Test file location** — `backend/tests/test_billing_extension.py` (new file, recommended) vs extending `backend/tests/test_extensions.py` if it exists. New file recommended for symmetry with `test_audit_sink.py` (Phase 222) and `test_saml_overlay.py` (Phase 217).
- **Makefile target name** — `make billing-extraction-discipline` vs `make boundary-discipline` vs reusing `make architecture-discipline` if it exists. Planner finalizes; the contract is "static + runtime check that the import path is gone", not the spelling.
- **Single PR vs multi-PR** — since Phase 223 spans two repos, the natural unit is two coordinated PRs (one per repo). Planner decides whether the plan partitions into more granular plans (e.g., 223-01: core Protocol scaffolding, 223-02: overlay class + registration, 223-03: lifespan dispatch + delete `core/marketplace.py`, 223-04: tests + Makefile, 223-05: audit re-run + REQUIREMENTS amendment). Recommended: 4-5 plans mirroring Phase 222's 5-plan structure.
- **Whether `app: FastAPI` or `app: object` is the right Protocol signature** — D-09 recommends `FastAPI` with `object` fallback if there's an unexpected import cycle. Planner verifies during research.
- **Whether `_init_default_billing()` step is needed** — D-06 / D-07 recommend lazy-default in the accessor (no init step). Planner can choose eager init in `app/api/main.py` startup if there's a strong reason; otherwise stick with the accessor-default pattern for consistency with Phase 222.
- **Whether the dispatch loop's `extension=type(ext).__name__` is the only context field, or also includes the underlying error type** — D-10's pseudocode picks `extension`, `timeout_seconds`/`error`. Planner finalizes.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source spec — the audit doc that motivates this work
- `docs-internal/audits/oc-separation-audit-20260430.md` §1 (Feature Boundary Leakage) — the three 🟡 risk rows pinning the loci: `api/main.py:184-203`, `core/marketplace.py:1-30`, `core/config.py:87-88, 108`. Lines 46-48 in the audit doc enumerate them with explicit relocation recommendations. **Read in full.**
- `docs-internal/audits/oc-separation-audit-20260430.md` §1 lines 11, 13-14 — the executive summary describing the 3-loci boundary risk and the deployment separation context.

### Requirements / roadmap (the source of truth)
- `.planning/REQUIREMENTS.md` §BILLING-01..06 — the six requirements this phase closes. **BILLING-03 wording is amended in this phase per D-01** (boto3 stays in core for S3 storage; the architectural goal is "AWS Marketplace API not invoked from core"). BILLING-01 names the Protocol file path (`backend/app/platform/extensions/protocols.py`) and the Community-default-no-op contract. BILLING-02 says `core/marketplace.py` is removed, not relocated within core (D-02). BILLING-04 specifies the dispatch loop shape (`for ext in get_billing_extensions(): ext.on_startup(app)`) — list-shape signal (D-06). BILLING-05 lays out the Settings placement decision (D-03 picks the overlay-only option). BILLING-06 is the audit-re-run close gate (D-17).
- `.planning/ROADMAP.md` §Phase 223 — goal statement + 4 success criteria. **SC#1 is amended in this phase per D-01.** SC#2 (community-deployment zero-AWS-call invariant) maps to D-13. SC#3 (enterprise overlay's `BillingExtension.on_startup()` fires when overlay installed + env var set) maps to D-04 + D-13. SC#4 (audit re-run reports zero 🟡 in §1) maps to D-17.
- `.planning/STATE.md` — milestone state v13.3, current focus Phase 222 (now complete), Phase 223 next. After Phase 223 closes, the v13.3 milestone audit re-run validates the close.
- `.planning/PROJECT.md` — milestone overview at "Current Milestone: v13.3 Boundary A+ Cleanup."

### Project / state — most-load-bearing upstream context
- `.planning/phases/222-audit-sink-protocol/222-CONTEXT.md` — **THE** canonical pattern Phase 223 mirrors. Read D-09 / D-10 / D-11 (list-shape registry + lazy-default accessor — Phase 223 D-06/D-07 mirror verbatim), D-06 (per-sink try/except facade — Phase 223 D-10 mirror), D-12/D-13 (fixture-based test pattern — Phase 223 D-15 mirror), and D-17 (lazy-import preservation — relevant if `from app.platform.extensions import get_billing_extensions` causes any cycle in `api/main.py`). **Read in full.**
- `.planning/milestones/v13.1-phases/214-identity-protocol-extract/214-CONTEXT.md` — the original "extract a Protocol from core, move impl to overlay, register via entry-point group" precedent. Phase 223 follows this verbatim for the relocation half. **Read for the extract-and-relocate pattern.**
- `.planning/milestones/v13.1-phases/217-auth-saml-enterprise/217-CONTEXT.md` — D-05 (overlay reads its own env vars, doesn't add to core Settings) is precedent for D-03/D-04. **Read for the env-var-ownership pattern.**

### Code (where the new Protocol lands)
- `backend/app/platform/extensions/protocols.py` — current file: `BrandingExtension`, `AuditExtension`, `AuthExtension`, `AuditSink` (added Phase 222). Phase 223 adds `BillingExtension` here as a 5th Protocol. Existing pattern: `@runtime_checkable class X(Protocol): ...`. Also imports `AsyncSession` from `sqlalchemy.ext.asyncio` (added Phase 222) and uses `TYPE_CHECKING` for forward-refs to `app.modules.*` types — same pattern applies to `FastAPI` import (D-09).
- `backend/app/platform/extensions/defaults.py` — current file: `DefaultBrandingExtension`, `DefaultAuditExtension`, `DefaultAuthExtension`, `DefaultIdentityExtension`, `DefaultAuditSink`. Phase 223 adds `DefaultBillingExtension` here.
- `backend/app/platform/extensions/__init__.py` — current file with `_extensions: dict`, `_routers: list`, `_loaded: bool`, `load_extensions()`, four single-instance accessors (`get_branding_extension`, `get_audit_extension`, `get_auth_extension`, `get_identity_extension`), one list accessor (`get_audit_sinks` — Phase 222). Phase 223 adds `get_billing_extensions()` mirroring `get_audit_sinks` shape verbatim (D-06).

### Code (the loci to be edited or deleted)
- `backend/app/api/main.py:20` — `from app.core.marketplace import register_marketplace_usage`. **Delete this line.**
- `backend/app/api/main.py:184-203` — the AWS Marketplace registration block. **Replace with the generic dispatch loop per D-10.**
- `backend/app/core/marketplace.py` — entire file (30 lines). **Delete the file.** Body moves to enterprise overlay's `MarketplaceBillingExtension.on_startup`.
- `backend/app/core/config.py:87-88` — `aws_marketplace_product_code: str | None = None` and `aws_marketplace_public_key_version: int = 1` fields. **Delete both.**
- `backend/app/core/config.py:108` — the `aws_marketplace_product_code` entry inside the `field_validator` whitelist tuple. **Delete this entry.**
- `.env.example` lines 348-356 (or wherever the AWS Marketplace section lives — verify line numbers at plan time) — restructure per D-05.

### Code (S3-related boto3 use — UNCHANGED, documented for clarity)
- `backend/app/platform/storage/s3.py:28` — `import boto3` for the S3StorageProvider. **Untouched.** This is the S3 storage backend used by every deployment with `storage_provider=s3`. The audit doc does NOT flag this as 🟡.
- `backend/app/api/main.py:155-182` — S3 health check block; `import boto3 as _boto3` at line 161. **Untouched.** The block runs only when `settings.storage_provider == "s3"`.
- `backend/app/platform/jobs/worker.py:184` — lazy `import boto3 as _boto3` for worker S3 credential probe. **Untouched.**

### Code (the test file lands here)
- `backend/tests/test_billing_extension.py` — **new file** (recommended) for D-15 (fixture-based dispatch tests). Mirrors `backend/tests/test_audit_sink.py` from Phase 222.
- `backend/tests/test_layering.py` (or its sibling) — extended for D-16 (architecture-guard test asserting `from app.core.marketplace` raises ImportError post-phase). Phase 222 added `AUDIT-02` architecture guard here; Phase 223 adds `BILLING-02`.
- `backend/tests/conftest.py` — global fixtures (DB session, TestClient, async fixtures). Phase 223 reuses; no new global fixture.
- `backend/Makefile` — Phase 222 added `make audit-sink-discipline`. Phase 223 adds a parallel `make billing-extraction-discipline` (or planner-finalized name) per D-16.

### Code (enterprise overlay — outside repo, primary consumer)
- `~/Code/geolens-enterprise/geolens_enterprise/__init__.py:register_extensions` — the overlay's registration callback. Phase 223 adds:
  ```python
  billing_extensions = registry.setdefault("billing_extensions", [DefaultBillingExtension()])
  billing_extensions.append(_get_billing_extension())
  ```
  with a corresponding `_get_billing_extension()` lazy-import helper mirroring the SAML/audit/branding pattern.
- `~/Code/geolens-enterprise/geolens_enterprise/billing/__init__.py` — **new module** in the enterprise repo. Houses `MarketplaceBillingExtension` (the class implementing `BillingExtension.on_startup`) and the relocated `register_marketplace_usage` body.
- `~/Code/geolens-enterprise/pyproject.toml` — current dependencies: `pysaml2`, `defusedxml`. Phase 223 adds `boto3>=1.35.0`. (Even though core still ships boto3, the overlay declaring its own dep makes it future-proof for the day core dropping boto3 becomes a separate phase.)

### Existing reusable extension patterns (don't reinvent)
- The four-Protocol pattern (Protocol → Default → typed accessor → registry slot) is fully exercised by `BrandingExtension`, `AuditExtension`, `AuthExtension`, `IdentityExtension`. Phase 222 added `AuditSink` (list shape). Phase 223 adds `BillingExtension` (list shape). **Do NOT introduce a new "registry shape abstraction" to unify single and list slots — YAGNI; one departure for one good reason.** (Same guidance Phase 222 wrote.)

### CLAUDE.md operational notes
- `CLAUDE.md` (project-local + user-global) — `feedback_run_ci_local_first.md` (run lint/typecheck/tests locally before pushing), `project_geolens_io_actions_billing.md` (free-tier Actions minutes routinely exhausted; prefer PR path), `feedback_no_blanket_add_planning.md` (no `git add -fA .planning/<dir>/`), `feedback_audit_sibling_repos_at_milestone_close.md` (**critical for Phase 223 — cross-repo phase requires sibling-repo verification at close**).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Protocol scaffolding (`backend/app/platform/extensions/protocols.py`)** — five existing Protocols (`BrandingExtension`, `AuditExtension`, `AuthExtension`, `AuditSink`, plus `IdentityExtension` in `app/core/identity.py`) demonstrate the exact pattern Phase 223 follows for `BillingExtension`. The `AuditSink` addition (Phase 222) demonstrates that importing types from libraries that don't pull in `app.modules.*` (e.g., `AsyncSession` from `sqlalchemy.ext.asyncio`) is the canonical solution; `FastAPI` import in Phase 223 follows the same precedent.
- **Default-class scaffolding (`backend/app/platform/extensions/defaults.py`)** — five existing defaults. `DefaultIdentityExtension.resolve_identity_from_token()` shows the async-default pattern; `DefaultAuditSink.emit()` shows the verbose-docstring pattern. `DefaultBillingExtension.on_startup()` is the simplest possible body (`return`).
- **Typed-accessor scaffolding (`backend/app/platform/extensions/__init__.py`)** — four single-instance accessors plus `get_audit_sinks()` (list shape, Phase 222). `get_billing_extensions()` is a near-clone of `get_audit_sinks()` with `audit_sinks` → `billing_extensions` and `AuditSink` → `BillingExtension`.
- **Phase 222 facade pattern in `app.modules.audit.service.audit_emit`** — per-sink try/except + structlog. Phase 223's lifespan dispatch loop in `api/main.py` is a near-clone with `await asyncio.wait_for(..., timeout=10.0)` added (the timeout is unique to startup; emit-time facade has no timeout).
- **Phase 222 fixture-based extension test pattern in `backend/tests/test_audit_sink.py`** — registry clear/restore yield-finally fixture, fixture-based extension registration via direct dict manipulation. Phase 223's `test_billing_extension.py` mirrors verbatim.
- **Phase 222 architecture-guard pattern in `backend/tests/test_layering.py` + `make audit-sink-discipline`** — assert no application code calls the deprecated path. Phase 223's BILLING-02 guard follows the same shape.
- **Enterprise overlay's `register_extensions(registry)` shape** — already populates `registry["auth"]`, `registry["identity"]`, `registry["audit"]`, `registry["branding"]`. The Phase 223 addition (`registry["billing_extensions"]` via `setdefault + append`) is mechanically additive.

### Established Patterns
- **One Protocol per orthogonal concern** — branding, audit (read), audit (write/sink), auth, identity each has its own slot. Billing follows: `BillingExtension` is a new orthogonal slot; do NOT extend an existing Protocol.
- **Default in `defaults.py`, NOT inline in `__init__.py`** — keeps the registry module focused on lookup logic.
- **Accessor returns either registered or default — never `None`** — call sites never null-check. `get_billing_extensions()` follows: returns `[DefaultBillingExtension()]` when slot is missing.
- **Per-extension try/except + structlog warning** — Phase 222 facade pattern; Phase 223 dispatch loop mirrors.
- **`runtime_checkable` Protocol** — all five existing Protocols are `@runtime_checkable`; `BillingExtension` is too. Lets `isinstance(x, BillingExtension)` work for sanity assertions in tests.
- **`setdefault + append` for list-shape slot registration** — Phase 222 D-09 documented; Phase 223 follows verbatim.
- **Lazy-import helper for overlay class loading** — `geolens_enterprise/__init__.py` already uses `_get_saml_extension`, `_get_audit_extension`, `_get_branding_extension` lazy imports. Phase 223 adds `_get_billing_extension` parallel.

### Integration Points
- **The single existing call site is `backend/app/api/main.py:184-203`** — the FastAPI lifespan startup. Replaced with the generic dispatch loop. No other call site exists in `backend/app/`.
- **`app.platform.extensions.load_extensions()` is called once at lifespan startup** before the dispatch loop runs. The order is critical: extensions register first, dispatch fires second. Verify the existing `lifespan` in `api/main.py` has this order; if not, fix it as part of plan scope.
- **The S3 health check at `api/main.py:155-182` runs BEFORE the marketplace block today.** After Phase 223, the S3 health check still runs at the same point (untouched); the BillingExtension dispatch loop replaces the marketplace block at line 184. Order: `init_storage()` → S3 health check → BillingExtension dispatch → `init_cache()` → ... (verify ordering at plan time; preserve today's order).
- **The lifespan is `async def`** — already async. The dispatch loop awaiting `BillingExtension.on_startup(app)` drops in naturally.
- **No frontend impact** — Phase 223 is pure backend + cross-repo.
- **No DB schema impact** — Phase 223 doesn't touch any models, migrations, or tables.

### Risk surfaces
- **Cross-repo coordination drift** — Phase 223's two-repo nature is the largest risk. If the core repo lands first without the overlay's `MarketplaceBillingExtension`, an enterprise deployment will boot without billing (a regression for paying customers). If the overlay lands first without core's `BillingExtension` Protocol, the overlay's `register_extensions` call fails (since `DefaultBillingExtension` doesn't exist yet). **Mitigation:** plan-phase agent specifies explicit cross-repo task ordering (overlay class first → core Protocol+default+accessor next → core dispatch + delete `core/marketplace.py` last); manual verification at close per `feedback_audit_sibling_repos_at_milestone_close.md`.
- **`from fastapi import FastAPI` in `protocols.py` introduces a cycle** — extremely unlikely (FastAPI doesn't import from `app.modules.*`), but verify during plan-time research. Fallback per D-09: `app: object` typed in the Protocol body, runtime-cast inside the overlay's implementation.
- **Lifespan ordering changes** — if the dispatch loop runs before `load_extensions()`, no overlay is registered yet and the loop is empty. Verify `api/main.py:lifespan` ordering: `load_extensions()` → S3 health → `for ext in get_billing_extensions(): ...` → init_cache → ... .
- **`.env.example` documentation drift** — D-05 restructures the AWS Marketplace section. If the rewrite confusingly suggests the var still works in community, operators may set it expecting metering. Mitigation: clear "**Enterprise overlay only**" header per D-05; planner reviews wording with `frontend-design`-style attention to clarity.
- **Audit re-run depends on Phase 222 ALSO being shipped** — BILLING-06 and Phase 222 AUDIT-05 both feed the v13.3 close audit. Phase 223 cannot satisfy BILLING-06 in isolation; it requires Phase 222 to ALSO be shipped (it is, as of 2026-04-30). Plan-phase agent verifies Phase 222 status before declaring BILLING-06 satisfiable.
- **Enterprise overlay's `boto3` dep declaration** — adding `boto3>=1.35.0` to `geolens-enterprise/pyproject.toml` doubles the dep when core also has it. After Phase 223, both repos declare boto3 (pip resolves to one install). This is fine functionally; document as a known overlap in the overlay repo's `pyproject.toml` comment.
- **Test fixture restoration must be airtight** — `_extensions["billing_extensions"]` mutated during a test must be restored in `finally`. Same risk as Phase 222 D-12; same mitigation (yield-finally fixture pattern from `test_lifecycle.py`).
- **Operator confusion at deploy** — community operators upgrading to v13.3 will see the AWS Marketplace section in `.env.example` reorganized. If they previously set `AWS_MARKETPLACE_PRODUCT_CODE` (it did nothing in community even before, but they may have set it as a no-op), they'll see no behavior change. Document in CHANGELOG that the env var is now overlay-only and unset values are explicitly fine.
- **Free-tier Actions billing exhaustion (project memory)** — relevant when Phase 223 ships. Phase 223 should run lint/typecheck/tests locally before pushing per `feedback_ci_local_first.md`; prefer PR path for verification per `project_geolens_io_actions_billing.md`. The cross-repo nature means TWO PR runs (one in each repo) — coordinate timing to avoid double Actions burn.

</code_context>

<specifics>
## Specific Ideas

- **`BillingExtension` Protocol in `protocols.py`, list-shape slot at `_extensions["billing_extensions"]` with `[DefaultBillingExtension()]` lazy default** — D-06/D-07. Mirrors Phase 222 `AuditSink` exactly.
- **`DefaultBillingExtension.on_startup` is a literal `async def on_startup(self, app): return`** — D-07. The simplest no-op possible.
- **Core dispatch loop wraps each extension with `asyncio.wait_for(..., timeout=10.0)` + per-extension try/except (TimeoutError + Exception)** — D-10. Mirrors Phase 222 facade pattern.
- **`register_marketplace_usage` body moves verbatim into `MarketplaceBillingExtension.on_startup` in the enterprise overlay** — D-02 / D-04. The 30-line function with the inline `import boto3` and `boto3.client("meteringmarketplace").register_usage(...)` is relocated, not rewritten.
- **The conditional gate (`if AWS_MARKETPLACE_PRODUCT_CODE`) lives in the overlay's `on_startup`, not in core dispatch** — D-13. Core doesn't read or know about the env var.
- **`aws_marketplace_*` settings are REMOVED from core Settings entirely** — D-03. Overlay reads them via `os.environ.get` or its own Pydantic `BillingSettings`.
- **BILLING-03 / SC#1 amendment is part of phase scope** — D-01. The `boto3` core-dep stays for S3 storage; the architectural goal is reframed as "AWS Marketplace API not invoked from core".
- **Cross-repo phase: `geolens` + `geolens-enterprise`** — D-14. Plan must specify cross-repo task ordering and verify both halves at close.
- **Architecture-guard test (BILLING-02 invariant) extends `test_layering.py` and adds a Makefile target** — D-16. Mirrors Phase 222 D-23 / `make audit-sink-discipline`.
- **Audit re-run is the BILLING-06 verification** — D-17. Run `/oc-audit` after both Phase 222 and Phase 223 ship.

</specifics>

<deferred>
## Deferred Ideas

- **Replacing `boto3` with `aiobotocore`/`minio-py` in core S3 storage** — out of v13.3 (D-01). Unrelated work; the architectural concern Phase 223 addresses is the AWS Marketplace API call, not the S3 SDK choice. If core ever wants to drop `boto3` entirely, that's a future phase that touches `app.platform.storage.s3`, the S3 health check at `api/main.py:155-182`, and the worker S3 credential probe at `app.platform.jobs.worker.py:184`.
- **`boto3` as `[project.optional-dependencies] s3 = ['boto3']`** — out of v13.3 (D-01). Forces every S3 deployment to install with `[s3]` flag, breaks docs/CI, and the architectural goal is achieved without it.
- **Stripe / per-deployment / per-seat billing** — Cloud-tier prerequisite (BILLING-FUTURE-01 in REQUIREMENTS.md). Builds on the `BillingExtension` Protocol Phase 223 delivers; lives in a future Cloud milestone.
- **Multi-tenant billing isolation** — Phase 999.6 territory (Cloud prerequisite). Out of v13.3.
- **Configurable `BILLING_STARTUP_TIMEOUT_SECONDS` env var** — D-11. YAGNI for v13.3; hardcoded 10s matches today's behavior. Add only if a future overlay legitimately needs more startup time AND can't lift the work into a background task.
- **Per-extension timeout overrides** — out of v13.3. If a specific overlay needs a different timeout, it can manage its own internal timeout (apply `asyncio.wait_for` inside its `on_startup`).
- **Circuit-breaking / extension-quarantine on N consecutive failures** — D-12. Out of v13.3; build inside an overlay if needed.
- **`BillingExtension.on_shutdown(app)` hook** — out of v13.3. BILLING-01 says "at least an `on_startup(app)` hook"; AWS `register_usage` doesn't need shutdown semantics. Add only when a future billing system actually requires graceful shutdown (Stripe doesn't; Paddle doesn't; bookkeeping flushes belong in background tasks not lifecycle hooks).
- **Audit-export overlay billing events** — out of v13.3 / BILLING-FUTURE territory. If a future overlay wants to record billing events to the audit log, that lives inside its own `BillingExtension.on_startup` body using the Phase 222 `audit_emit(...)` facade — no new core Protocol needed.
- **Renaming `BillingExtension` (e.g., `BillingHook`, `BillingSubscriber`)** — locked to `BillingExtension` per BILLING-01 spec text. Cosmetic future cleanup.
- **A unified registry-shape abstraction (single-vs-list slot polymorphism)** — out of v13.3. Same guidance Phase 222 wrote: YAGNI; two list-shape exceptions (`audit_sinks`, `billing_extensions`) are documented departures, not a new abstraction layer.
- **CHANGELOG entry generation** — Claude's discretion at plan time; Phase 223 changes user-facing env-var documentation (`.env.example`) and removes a startup behavior path, both worth noting in the v13.3 CHANGELOG entry.

</deferred>

---

*Phase: 223-marketplace-billing-extraction*
*Context gathered: 2026-04-30*
*Mode: interactive discuss with user-directed best-practice defaults (`--chain`)*
