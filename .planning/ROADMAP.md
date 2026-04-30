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
- 🔄 **v13.3 Boundary A+ Cleanup** — Phases 222-223 (in progress)

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

### v13.3 Boundary A+ Cleanup (Phases 222-223)

- [ ] **Phase 222: audit-sink-protocol** — Extract AuditSink Protocol; route all 65 log_action() emit sites through get_audit_sink().emit() with safe failure semantics and a fixture-based extension test
- [ ] **Phase 223: marketplace-billing-extraction** — Remove boto3 from core; relocate AWS Marketplace logic to enterprise overlay behind BillingExtension.on_startup() hook

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
  - [ ] 222-05-PLAN.md — Architecture guard (AUDIT-02 invariant) + Makefile target + AUDIT-05 close gate

---

### Phase 223: marketplace-billing-extraction
**Goal**: boto3 is absent from the community package; AWS Marketplace registration runs only in the enterprise overlay via a BillingExtension hook; the post-phase audit re-run shows zero 🟡 boundary risks
**Depends on**: Phase 221 (can run in parallel with Phase 222)
**Requirements**: BILLING-01, BILLING-02, BILLING-03, BILLING-04, BILLING-05, BILLING-06
**Source spec**: `docs-internal/audits/oc-separation-audit-20260430.md` §1 (Feature Boundary Leakage — 3 🟡 loci: `api/main.py:184-203`, `core/marketplace.py:1-30`, `core/config.py:87-88`)
**Note**: The aws_marketplace_product_code / aws_marketplace_public_key_version settings placement (core Settings pass-through vs enterprise-only) is an acceptable-carve-out decision; resolve during phase planning if not via /gsd-discuss-phase.
**Success Criteria** (what must be TRUE):
  1. `import boto3` produces an ImportError in a clean community virtualenv (boto3 not in backend/pyproject.toml)
  2. A community deployment with AWS_MARKETPLACE_PRODUCT_CODE unset (the default) performs zero AWS API calls and imports zero boto3 symbols at startup
  3. The enterprise overlay's BillingExtension.on_startup() fires and registers marketplace usage when the overlay is installed and the env var is set — behavior is unchanged for enterprise deployments
  4. An audit re-run against the post-phase codebase reports zero 🟡 risks in §1 (Feature Boundary Leakage) and the AWS Marketplace cluster reads "✅ Closed"
**Plans**: TBD

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 222. audit-sink-protocol | 4/5 | In Progress|  |
| 223. marketplace-billing-extraction | 0/TBD | Not started | - |

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 4/5 plans executed
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)
