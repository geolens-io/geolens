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
- 🔄 **v13.2 Edition Lifecycle Hardening** — Phases 220-221 (in progress)

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

### v13.2 Edition Lifecycle Hardening (Phases 220-221)

- [ ] **Phase 220: lifecycle-runbooks-and-preservation** - Operator runbooks (deactivate + reactivate) land in `docs/`, `docs/saml.md` cross-links, and data-preservation guarantee is verified by integration test
- [ ] **Phase 221: lifecycle-user-continuity-and-verification** - SAML users have a documented and tested re-onboarding path; CI round-trip symmetry test confirms deactivate → reactivate is lossless

## Phase Details

### Phase 220: lifecycle-runbooks-and-preservation
**Goal**: Operators have authoritative documentation for the enterprise→community downgrade and re-upgrade lifecycle, and data-preservation behavior is verified by an automated test
**Depends on**: Phase 219 (v13.1 SAML implementation — `backend/app/modules/auth/saml/`, `oauth_providers` table, `User` deferred=True columns)
**Requirements**: LIFECYCLE-01, LIFECYCLE-02, LIFECYCLE-03, LIFECYCLE-04, LIFECYCLE-05
**Success Criteria** (what must be TRUE):
  1. Operator can read `docs/edition-deactivation.md` that covers the full enterprise→community downgrade sequence: pre-flight checks, `GEOLENS_EDITION=community` switch, SAML user inventory, and data-fate matrix (what survives vs. what requires export before `alembic downgrade`)
  2. Operator can read `docs/edition-reactivation.md` that confirms `deferred=True` SAML columns and `oauth_providers` rows survive a deactivation period and are usable immediately on re-upgrade
  3. `docs/saml.md` no longer presents `alembic downgrade -1` as the primary deactivation path — it links to `edition-deactivation.md` and labels the alembic path as destructive/opt-in with a mandatory data-export prerequisite
  4. An integration test runs in CI (`pytest -m lifecycle`) that exercises the deactivate path and asserts `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` User columns are intact after edition flag is toggled off
  5. Either a non-destructive alembic downgrade path exists that preserves SAML data, OR `edition-deactivation.md` documents the destructive path with an explicit mandatory-export step
**Plans**: 6 plans
- [x] 220-01-deactivation-runbook-PLAN.md — Author docs/edition-deactivation.md (LIFECYCLE-01, LIFECYCLE-05)
- [x] 220-02-reactivation-runbook-PLAN.md — Author docs/edition-reactivation.md (LIFECYCLE-02)
- [x] 220-03-saml-doc-edit-PLAN.md — Targeted edit to docs/saml.md Installation section (LIFECYCLE-03)
- [x] 220-04-lifecycle-test-PLAN.md — Register lifecycle marker + author backend/tests/test_lifecycle.py (LIFECYCLE-04)
- [ ] 220-05-requirements-precision-fix-PLAN.md — Fix LIFECYCLE-04 wording in REQUIREMENTS.md and ROADMAP.md (LIFECYCLE-04 text-precision)
- [ ] 220-06-ci-overlay-install-PLAN.md — Amend .github/workflows/ci.yml to install geolens-enterprise overlay before backend test job (LIFECYCLE-04 CI side)

### Phase 221: lifecycle-user-continuity-and-verification
**Goal**: Existing SAML-authenticated users have a safe, documented re-onboarding path when their edition is deactivated, and a CI test confirms the full deactivate→reactivate round-trip is lossless
**Depends on**: Phase 220
**Requirements**: LIFECYCLE-06, LIFECYCLE-07
**Success Criteria** (what must be TRUE):
  1. An admin can convert a SAML-authenticated user's account to local-password or OIDC via a documented procedure (runbook or CLI command) without losing audit history, group memberships, or dataset ownership
  2. `docs/edition-deactivation.md` includes a "Handling existing SAML users" section describing the re-onboarding procedure and linking to any supporting admin tooling
  3. A CI test (`pytest -m lifecycle`) exercises the deactivate → reactivate round-trip and asserts that User identities, `oauth_providers` rows, and audit trail entries are all intact after the cycle completes
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 220. lifecycle-runbooks-and-preservation | 4/6 | In Progress|  |
| 221. lifecycle-user-continuity-and-verification | 0/TBD | Not started | - |

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 4/6 plans executed
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the Enterprise tier's "multi-org / tenant isolation" feature can ship. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)
