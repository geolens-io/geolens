# Roadmap: GeoLens

## Milestones

- ✅ **v1.0 MVP** — Phases 1-8 (shipped 2026-02-13)
- ✅ **v1.1 Machine Readability** — Phases 9-13 (shipped 2026-02-14)
- ✅ **v1.2 QA & Polish** — Phases 14-16 (shipped 2026-02-14)
- ✅ **v1.3 Admin Control & Data Lifecycle** — Phases 17-21 (shipped 2026-02-15)
- ✅ **v1.4 Production Readiness** — Phases 22-27 (shipped 2026-02-15)
- ✅ **v1.5 Data Organization & Freshness** — Phases 28-31 (shipped 2026-02-15)
- ✅ **v1.6 UI/UX Polish** — Phases 32-35 (shipped 2026-02-15)
- ⏸️ **v1.7 Marketplace & Distribution** — Phases 36-42 (paused at Phase 40)
- ✅ **v1.8 Map Builder Core** — (shipped 2026-02-17)
- ✅ **v1.9 Map Builder AI** — (shipped 2026-02-21)
- ✅ **v2.0 Natural Earth Seed Script** — Phases 53-55 (shipped 2026-02-22)
- ✅ **v2.1 Service URL Importing** — Phases 56-60 (shipped 2026-02-23)
- ✅ **v2.2 Architecture Simplification** — Phases 61-63 (shipped 2026-02-23)
- ✅ **v2.3 Layer Creation & Editing** — Phases 64-67 (shipped 2026-02-24)
- ✅ **v2.4 Visual Identity & Admin Experience** — Phases 68-71 (shipped 2026-02-24)
- ✅ **v2.5 i18n** — (shipped 2026-02-25)
- ✅ **v2.6 Tile Architecture** — (shipped 2026-02-26)
- ✅ **v3.0 Design Overhaul** — (shipped 2026-02-28)
- ✅ **v5.0 Cloud-Ready Architecture** — (shipped 2026-03-02)
- ✅ **v6.0 Hardening & Production Readiness** — Phases 102-110 (shipped 2026-03-03)
- ✅ **v6.1 Dataset Detail UX & Provenance** — Phases 111-115 (shipped 2026-03-06)
- ✅ **v6.2 Enterprise Configuration & OAuth** — Phases 116-120 (shipped 2026-03-07)
- ✅ **v7.0 Stack Consolidation** — Phases 121-132 (shipped 2026-03-08)
- ✅ **v7.2 Semantic Search (pgvector)** — Phases 133-138 (shipped 2026-03-09)
- ✅ **v7.3 Map Page Polish** — Phases 139-143 (shipped 2026-03-09)
- ✅ **v8.0 Spatial Intelligence** — Phases 144-147 (shipped 2026-03-09)
- ✅ **v8.1 Secure Sharing & Embed Tokens** — Phases 148-151 (shipped 2026-03-10)
- ✅ **v8.2 Share Link Settings** — Phases 152-153 (shipped 2026-03-10)
- ✅ **v9.0 Cloud Marketplace Distribution** — Phases 154-160 (shipped 2026-03-11)
- ✅ **v9.1 Map Experience & Discovery** — Phases 161-164 (shipped 2026-03-11)
- ✅ **v10.0 Raster Support** — Phases 165-170 (shipped 2026-03-14)
- ✅ **v10.1 VRT Raster Mosaics** — Phases 171-177 (shipped 2026-03-15)
- ✅ **v11.0 Performance at Scale** — Phases 178-182 (shipped 2026-03-16)
- ✅ **v12.0 Record-First Discovery Architecture** — Phases 183-190 (shipped 2026-03-17)
- ✅ **v12.1 UI/UX Polish** — Phases 191-194 (shipped 2026-03-18)
- ✅ **v12.2 Record Detail Stabilization** — Phases 195-199 (shipped 2026-03-19)
- ✅ **v12.3 Map Builder Excellence** — Phases 200-205 (shipped 2026-03-21)
- ✅ **v13.0 Open-Core Pre-Release** — Phases 206-211 (shipped 2026-03-27)
- 🚀 **1.0.0 Public Release** — Version reset; backend/frontend bumped to 1.0.0 (shipped 2026-04-01)
- ✅ **v13.1 Open-Core Separation P1** — Phases 212-219 (shipped 2026-04-29) — see [archive](milestones/v13.1-ROADMAP.md)
- ✅ **v13.2 Edition Lifecycle Hardening** — Phases 220-221 (shipped 2026-04-30) — see [archive](milestones/v13.2-ROADMAP.md)
- 🔄 **v13.3 Boundary A+ Cleanup** — Phases 222-224 (Phases 222-223 shipped 2026-04-30; Phase 224 queued from `/oc-audit` follow-up)

## Phases

<details>
<summary>✅ v13.1 Open-Core Separation P1 (Phases 212-219) — SHIPPED 2026-04-29</summary>

- [x] Phase 212: core-settings-decouple (4/4 plans) — completed 2026-04-27
- [x] Phase 213: catalog-authz-relocate (4/4 plans) — completed 2026-04-27
- [x] Phase 214: identity-protocol-extract (4/4 plans) — completed 2026-04-27
- [x] Phase 215: sdks-from-openapi (5/5 plans) — completed 2026-04-27
- [x] Phase 216: geolens-cli-mvp (6/6 plans) — completed 2026-04-27
- [x] Phase 217: auth-saml-enterprise (5/5 plans) — completed 2026-04-27
- [x] Phase 218: oc-audit-close-v13.1 (1/1 plan) — completed 2026-04-28 (PARTIAL — closed by Phase 219)
- [x] Phase 219: oc-audit-remediate-idp-mapping (1/1 plan) — completed 2026-04-29

Audit grades met: Boundary A (≥A−), Seam Quality B (≥B), OSS Surface A− (≥C). 21/21 v13.1 requirements satisfied.

</details>

<details>
<summary>✅ v13.2 Edition Lifecycle Hardening (Phases 220-221) — SHIPPED 2026-04-30</summary>

- [x] Phase 220: lifecycle-runbooks-and-preservation (6/6 plans) — completed 2026-04-30
- [x] Phase 221: lifecycle-user-continuity-and-verification (3/3 plans) — completed 2026-04-30

7/7 v13.2 requirements satisfied (LIFECYCLE-01..07). Operator runbooks for enterprise↔community lifecycle, admin SAML→local conversion endpoint, and 3 lifecycle tests (deactivate-only, conversion, deactivate→reactivate round-trip symmetry) shipped.

</details>

### v13.3 Boundary A+ Cleanup (Phases 222-224)

- [x] **Phase 222: audit-sink-protocol** — Extract AuditSink Protocol; route all 65 log_action() emit sites through get_audit_sink().emit() with safe failure semantics and a fixture-based extension test (completed 2026-04-30)
- [x] **Phase 223: marketplace-billing-extraction** — Remove boto3 marketplace surface from core; relocate AWS Marketplace logic to enterprise overlay behind BillingExtension.on_startup() hook (completed 2026-04-30; BILLING-06 close gate satisfied by `oc-separation-audit-20260430-b.md`, Boundary Integrity A+)
- [ ] **Phase 224: catalog-god-module-split** — Split `backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC) into 4 cohesive modules behind a thin re-export façade. Largest remaining enterprise-overlay obstacle per `oc-separation-audit-20260430-b.md` §5 / §7 P0.

## Phase Details

### Phase 222: audit-sink-protocol
**Goal**: Every audit event routes through a single extensible sink Protocol; community behavior is identical to today; an enterprise overlay can subscribe additional sinks without modifying core code
**Depends on**: Phase 221
**Requirements**: AUDIT-01, AUDIT-02, AUDIT-03, AUDIT-04, AUDIT-05
**Source spec**: `docs-internal/audits/oc-separation-audit-20260430.md` §2 (Seam #3) and §5 (Coupling Health, log_action regression)
**Note**: Design decisions — sync vs async emit, sink-failure semantics, whether log_action() becomes the default sink body or is removed — should be resolved via `/gsd-discuss-phase` before planning.
**Success Criteria** (what must be TRUE):
  1. A community deployment with zero overlays records exactly the same audit_logs rows after the refactor as before — no row-count or row-content drift on a deterministic test workload
  2. A failed business operation (e.g., dataset publish error) is not rolled back or suppressed because an audit sink raised an exception — sink failures are swallowed and logged via structlog.exception()
  3. An enterprise overlay can register a second AuditSink implementation via the existing extension entry-point group and receive every audit event without any core code change
  4. No call site in backend/app/ calls log_action() directly — all 65 sites route through get_audit_sink().emit()
  5. Existing audit-related tests pass without modification
**Plans**: 5 plans
  - [x] 222-01-PLAN.md — AuditSink Protocol scaffolding (Protocol + AuditEvent dataclass + DefaultAuditSink + get_audit_sinks accessor + AUDIT-01 unit smoke test)
  - [x] 222-02-PLAN.md — audit_emit() facade + AUDIT-03 raising-sink test (per-sink try/except + structlog.exception)
  - [x] 222-03-PLAN.md — Mechanical 65-site rewrite across 18 files (preserves 5 lazy-import sites)
  - [x] 222-04-PLAN.md — AUDIT-04 multi-sink integration test (FixtureSink + DefaultAuditSink coexistence via HTTP endpoint)
  - [x] 222-05-PLAN.md — Architecture guard (AUDIT-02 invariant) + Makefile target + AUDIT-05 close gate

---

### Phase 223: marketplace-billing-extraction
**Goal**: boto3 is absent from the community package; AWS Marketplace registration runs only in the enterprise overlay via a BillingExtension hook; the post-phase audit re-run shows zero 🟡 boundary risks
**Depends on**: Phase 221 (can run in parallel with Phase 222)
**Requirements**: BILLING-01, BILLING-02, BILLING-03, BILLING-04, BILLING-05, BILLING-06
**Source spec**: `docs-internal/audits/oc-separation-audit-20260430.md` §1 (Feature Boundary Leakage — 3 🟡 loci: `api/main.py:184-203`, `core/marketplace.py:1-30`, `core/config.py:87-88`)
**Note**: The aws_marketplace_product_code / aws_marketplace_public_key_version settings placement (core Settings pass-through vs enterprise-only) is an acceptable-carve-out decision; resolve during phase planning if not via /gsd-discuss-phase.
**Success Criteria** (what must be TRUE):
  1. `backend/app/core/marketplace.py` is deleted from core; no module under `backend/app/` calls `boto3.client("meteringmarketplace").register_usage(...)`. `boto3` remains a core dependency because the core S3 storage provider and S3 health check use it — that is an unrelated boundary concern. The AWS Marketplace billing API is invoked exclusively from the enterprise overlay.
  2. A community deployment with AWS_MARKETPLACE_PRODUCT_CODE unset (the default) performs zero AWS API calls and imports zero boto3 symbols at startup
  3. The enterprise overlay's BillingExtension.on_startup() fires and registers marketplace usage when the overlay is installed and the env var is set — behavior is unchanged for enterprise deployments
  4. An audit re-run against the post-phase codebase reports zero 🟡 risks in §1 (Feature Boundary Leakage) and the AWS Marketplace cluster reads "✅ Closed"
**Plans**: 5 plans
  - [x] 223-01-PLAN.md — BillingExtension Protocol scaffolding (Protocol + DefaultBillingExtension + get_billing_extensions accessor + Wave-0 BILLING-01 tests)
  - [x] 223-02-PLAN.md — Lifespan dispatch loop replaces api/main.py:184-203 + drop core.marketplace import + 3 anyio dispatch tests (BILLING-04 / D-10/D-11/D-12)
  - [x] 223-03-PLAN.md — Delete core/marketplace.py + remove aws_marketplace_* from Settings + .env.example restructure (BILLING-02, BILLING-05)
  - [x] 223-04-PLAN.md — Architecture guard tests + billing-extraction-discipline Makefile target (BILLING-02 + BILLING-04 / D-11)
  - [x] 223-05-PLAN.md — Cross-repo enterprise overlay (MarketplaceBillingExtension) + REQUIREMENTS/ROADMAP amendments (D-01) + /oc-audit re-run close gate (BILLING-06) — completed 2026-04-30

---

### Phase 224: catalog-god-module-split
**Goal**: `backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC orchestration god-module) is split into 4 cohesive sub-modules (`service_create.py`, `service_query.py`, `service_lifecycle.py`, `service_grants.py`) behind a thin re-export façade so future enterprise overlays (quotas, tier-gated dataset behavior, multi-tenant scoping) can target focused modules instead of monkey-patching a 1.4kLOC orchestrator.
**Depends on**: Phase 223
**Requirements**: TBD via `/gsd-discuss-phase 224` and `/gsd-plan-phase 224` (likely DECOUPLE-01 …DECOUPLE-04)
**Source spec**: `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 (Coupling Health regression) and §7 P0 (action item #1)
**Note**: Pure refactor — zero behavior change. Public import surface (`from app.modules.catalog.datasets.domain.service import ...`) must be preserved via the façade. Architecture-guard test pattern from Phase 222 (`test_layering.py::test_no_log_action_calls_outside_audit_service`) is the template — add a guard ensuring no external module bypasses the façade.
**Estimated effort**: 1 day (1 phase, 4-5 plans)
**Success Criteria** (draft — refine in `/gsd-discuss-phase 224`):
  1. `backend/app/modules/catalog/datasets/domain/service.py` is <250 LOC (just re-exports + docstrings)
  2. Each of the 4 new modules is <500 LOC and has a single cohesive responsibility (creation / queries / lifecycle / grants)
  3. All public symbols previously importable from `service.py` remain importable from the same path (zero call-site churn outside this module)
  4. Existing catalog tests pass without modification
  5. New architecture guard prevents external imports of the 4 sub-modules (must go through the façade)
**Plans**: TBD (run `/gsd-plan-phase 224`)

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 222. audit-sink-protocol | 6/5 | Complete    | 2026-04-30 |
| 223. marketplace-billing-extraction | 4/5 | In Progress|  |

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 2/9 plans executed
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.7: ProcessingPort Protocol — break catalog ↔ processing cycle (BACKLOG — P0)

**Goal:** Invert the 19-file two-way coupling between `backend/app/modules/catalog/*` and `backend/app/processing/*` by defining a `ProcessingPort` Protocol in `backend/app/core/` (mirror Phase 214 `IdentityProtocol` pattern). The 8 `processing/*` → `catalog/*` imports become Protocol-typed; an architecture-guard test prevents the cycle from regrowing.
**Source:** `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 (Coupling regression: 16 → 19 files since 2026-04-30 baseline) / §7 P0 (action item #2)
**Estimated effort:** 3–5 days
**Why:** Two-way coupling makes processing un-overlayable for enterprise (async ingest pipelines, AI gateway swap, persistent connectors). AI features are *deepening* the cycle, not breaking it — `processing/ai/chat_service.py`, `metadata_service.py`, `embeddings/backfill.py` are the new violators. Phase 224 (catalog god-module split) is a prerequisite — easier to invert imports against a focused module surface than against a 1407-LOC orchestrator.
**Depends on:** Phase 224 (catalog god-module split) recommended first

Plans:
- [ ] TBD

---

### Phase 999.8: PermissionExtension Protocol (BACKLOG — P1)

**Goal:** Add `PermissionExtension` Protocol at `backend/app/platform/extensions/protocols.py` with `check_permission(user, action, resource)` + `filter_visible(user, query)` hooks. Convert the hardcoded `DEFAULT_ROLE_PERMISSIONS` matrix at `backend/app/modules/auth/permissions.py:43-74` to `DefaultPermissionExtension`. Move the visibility chokepoint at `backend/app/modules/catalog/authorization.py:34` to consult the extension.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #5 (🔴) / §7 P1
**Estimated effort:** 3–5 days
**Unblocks:** Field-level RBAC, attribute-based access control (ABAC), row-level filters by user attribute — all unreachable today since the matrix is fixed-list.

Plans:
- [ ] TBD

---

### Phase 999.9: WorkflowExtension Protocol (BACKLOG — P1)

**Goal:** Add `WorkflowExtension` Protocol with `allowed_transitions()` + `on_transition(from, to, user)` hooks. Convert the hardcoded `ALLOWED_TRANSITIONS` dict at `backend/app/modules/catalog/datasets/api/router_data.py:210-215` and `_STATUS_ORDER` at `:260` to `DefaultWorkflowExtension`. No registry, no events, no approver concept exist today.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #6 (🔴) / §7 P1
**Estimated effort:** 3–5 days
**Unblocks:** Multi-step approvals (draft → review → publish), reviewer assignment, custom states. Required for Enterprise §3 (Governance & Workflow — "BIG MONEY AREA" per GTM doc).

Plans:
- [ ] TBD

---

### Phase 999.10: AIProviderExtension Protocol (BACKLOG — P1)

**Goal:** Replace hardcoded `if/elif provider == "anthropic" / "openai_compatible"` dispatch (currently at `backend/app/processing/ai/llm_loop.py:117,132` and `service.py:387-398`) with `AIProviderExtension` Protocol exposing `complete(messages, tools)` and `stream(...)` methods. Default registry maps the two community providers; overlays register Bedrock / Vertex / Azure / vLLM via the same accessor pattern as `BillingExtension` and `AuditSink`.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #7 (🔴) / §7 P1
**Estimated effort:** 5–8 days
**Unblocks:** AI policy/governance, BYO-key, batch AI, model routing. Adding a new provider today touches 5+ files.

Plans:
- [ ] TBD

---

### Phase 999.11: test_no_processing_imports_catalog architecture guard (BACKLOG — P1)

**Goal:** Add `test_layering.py::test_no_processing_imports_catalog` architecture guard that fails CI if any module under `backend/app/processing/` imports from `backend/app/modules/catalog/`. Mirrors the AUDIT-02 invariant guard pattern from Phase 222.
**Source:** `oc-separation-audit-20260430-b.md` §7 P1 (action item #5)
**Estimated effort:** 1 hour
**Depends on:** Phase 999.7 (ProcessingPort Protocol) — blocked until the cycle is inverted, otherwise this guard fails immediately.

Plans:
- [ ] TBD

---

### Phase 999.12: geolens.yaml catalog manifest spec (BACKLOG — P1)

**Goal:** Define and ship the `geolens.yaml` catalog manifest format (Apache-2.0) — declarative descriptor for datasets, sources, and publishing rules. Implement `geolens init` / `geolens apply` / `geolens validate` CLI commands; backend ingest path consumes the manifest. The largest unshipped open-core enabler per the strategic guidance.
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — zero source-tree hits) / §7 P1 (action item #9). v13.1 close audit and v13.2 audit both flagged this as biggest unshipped OC adoption wedge.
**Estimated effort:** 2 weeks
**Why this matters:** "A new user should be able to publish a working geospatial catalog in 10 minutes — from `docker compose up` to a browsable, shareable catalog of their own data" is the GTM falsifiable adoption target. Without a declarative manifest + `apply` workflow, that target is hand-wavy.

Plans:
- [ ] TBD

---

### Phase 999.13: Persistent connector registry (BACKLOG — P2)

**Goal:** Greenfield Enterprise-tier feature — `Connector` ORM (id, type, config_jsonb, schedule, last_sync_at, owner_id) + `ConnectorAdapter` Protocol + Celery beat scheduler integration + encrypted credential vault. Distinct from current stateless probes at `backend/app/modules/catalog/sources/adapters/{wfs,arcgis,stac,ogcapi}.py`.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #8 (🔴) / §7 P2
**Estimated effort:** 2–3 weeks
**Tier:** Enterprise — stored credentials + scheduled mirroring is an explicit Enterprise paywall per `docs-internal/GTM/free-vs-enterprise.md` §6.

Plans:
- [ ] TBD

---

### Phase 999.14: Helm chart + AMI Packer pipeline (BACKLOG — P2)

**Goal:** Build a `deployment/` directory with Helm chart for K8s deployments + Packer template for AWS Marketplace AMI distribution. Phase 223 wired the `BillingExtension` for AMI metering, but there's currently no path to actually ship the AMI image to AWS Marketplace.
**Source:** `oc-separation-audit-20260430-b.md` §4 (HIGH severity — no `deployment/`, no Helm, no AMI pipeline) / §7 P2
**Estimated effort:** 2 weeks

Plans:
- [ ] TBD

---

### Phase 999.15: SBOM + signed image distribution (BACKLOG — P2)

**Goal:** Add SBOM generation (CycloneDX or SPDX) + Cosign-signed images to the deployment pipeline. Typical enterprise procurement gate.
**Source:** `oc-separation-audit-20260430-b.md` §4 finding #4 / §7 P2
**Estimated effort:** 1 week

Plans:
- [ ] TBD

---

### Phase 999.16: Extract geolens-schemas package (BACKLOG — P2)

**Goal:** Extract `backend/app/standards/{stac,ogc,dcat}/` schemas + validators into a standalone `geolens-schemas` PyPI package (Apache-2.0). Embedded today; persistent OSS-surface gap per audits since v13.1 close.
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — schema/validator package not extractable) / §7 P2
**Estimated effort:** 1 week
**Unblocks:** Schema-validator OSS adoption beyond GeoLens consumers; reusable wedge for FAIR-aligned tooling.

Plans:
- [ ] TBD

---

### Phase 999.17: Run cold PyPI/npm publish workflows (BACKLOG — P2)

**Goal:** Execute the wired-but-cold `.github/workflows/publish-{sdks,cli}.yml` workflows once to convert "wired" → "shipped". Verify `secrets.PYPI_TOKEN` and `secrets.NPM_TOKEN` are set; consider migrating to PyPI Trusted Publishing (`id-token: write` permission already reserved).
**Source:** `oc-separation-audit-20260430-b.md` §6 (WIRED — never run) / §7 P2
**Estimated effort:** 1 hour (after token verification)

Plans:
- [ ] TBD
