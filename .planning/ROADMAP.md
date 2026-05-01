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
- ✅ **v13.3 Boundary A+ Cleanup** — Phases 222-224 (shipped 2026-05-01) — see [archive](milestones/v13.3-ROADMAP.md)
- 🚧 **v13.4 Boundary Closeout** — Phases 225-229 (in progress)

## Phases

### Active Phases — v13.4 Boundary Closeout

- [ ] **Phase 225: processing-port-protocol-cycle-inversion** — Invert the catalog↔processing cycle behind a `ProcessingPort` Protocol; inline architecture-guard test
- [ ] **Phase 226: ai-provider-extension-protocol** — Replace hardcoded provider dispatch with `AIProviderExtension` extension lookup
- [ ] **Phase 227: saml-test-fixture-tmp-path** — Stop committed SAML fixture mutation; route generator output to pytest `tmp_path`
- [ ] **Phase 228: run-cold-publish-workflows** — Execute publish-sdks / publish-cli workflows end-to-end and validate install on a clean machine
- [ ] **Phase 229: post-impl-audit-v13.4** — Post-implementation audit gate confirming Boundary ≥ A+, Coupling ≥ B+, Seam ≥ A−

#### Phase 225: processing-port-protocol-cycle-inversion

**Goal:** Invert the 19-file two-way coupling between `backend/app/modules/catalog/*` and `backend/app/processing/*` by defining a `ProcessingPort` Protocol in `backend/app/core/` (mirror Phase 214 `IdentityProtocol` pattern). Rewire the 8 `processing/*` → `catalog/*` imports — including the AI features (`processing/ai/chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) — through Protocol-typed boundaries. Ship a default ProcessingPort implementation that preserves all existing behavior with zero functional regressions.

**Source:** `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 (Coupling regression: 16 → 19 files since 2026-04-30 baseline) / §7 P0 (action item #2). Promoted from Phase 999.7 on 2026-05-01.

**Requirements:** PROCESS-01, PROCESS-02, PROCESS-03, PROCESS-04, PROCESS-05

**Depends on:** Phase 224 (catalog god-module split — ✅ shipped 2026-05-01)

**Notes:** This phase **inlines** the architecture-guard test that was originally backlogged as Phase 999.11 (`test_no_processing_imports_catalog`). Adding the guard before the cycle is inverted would fail CI immediately, so the guard ships in the same phase as the inversion. Backlog item 999.11 is therefore retired (see Backlog section). The guard mirrors the AUDIT-02 invariant pattern from Phase 222.

**Success Criteria** (what must be TRUE):
1. `ProcessingPort` Protocol exists in `backend/app/core/` and exposes the catalog accessors needed by `processing/*` (mirrors the `IdentityProtocol` shape from Phase 214).
2. `grep -RE "from backend.app.modules.catalog|from app.modules.catalog" backend/app/processing/` returns zero hits — no direct cross-domain imports remain.
3. `pytest backend/tests/test_layering.py::test_no_processing_imports_catalog` passes, and intentionally adding a forbidden import causes the test to fail in CI.
4. Full backend test suite passes with the default `ProcessingPort` wired in (zero functional regressions vs. the v13.3 baseline of 2036/2036).
5. AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog data exclusively through the Protocol — verifiable by the same grep guard plus a focused unit test that swaps in a fake `ProcessingPort`.

**Plans:**
- ✅ Plan 01: additive-scaffold — ProcessingPort Protocol + DefaultProcessingPort + get_processing_port() (committed 9bb12f66)
- ✅ Plan 02: migrate-top-level-imports — 8 module-level catalog imports migrated to port calls (committed 3285bfa3; 2046/2046 tests green)
- ✅ Plan 03a: migrate-deferred-imports-batch-a — 8 deferred sites in 4 files migrated; Port extended with 3 ORM class helpers (committed 49553678)
- [ ] Plan 03b: migrate-deferred-imports-batch-b
- [ ] Plan 04: architecture-guard-and-seam-test

#### Phase 226: ai-provider-extension-protocol

**Goal:** Close the last 🔴 seam from `oc-separation-audit-20260430-b.md` by extracting AI provider dispatch into an `AIProviderExtension` Protocol on the same accessor pattern as `BillingExtension` (Phase 223) and `AuditSink` (Phase 222). Replace the hardcoded `if/elif provider == "anthropic"/"openai_compatible"` branches at `processing/ai/llm_loop.py:117,132` and `service.py:387-398` with extension lookup. Default registry maps the two community providers; overlays can register Bedrock / Vertex / Azure / vLLM via `importlib.metadata` entry_points. Ships only the seam — new provider implementations land in overlays or follow-up milestones.

**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #7 (🔴) / §7 P1. Promoted from Phase 999.10.

**Requirements:** AIEXT-01, AIEXT-02, AIEXT-03, AIEXT-04, AIEXT-05

**Depends on:** Phase 225 (sequential — both phases touch `processing/ai/`; serializing avoids merge churn and keeps the architecture-guard signal clean while the seam is being cut).

**Success Criteria** (what must be TRUE):
1. `AIProviderExtension` Protocol exists at `backend/app/platform/extensions/protocols.py` with `complete(messages, tools)` and `stream(messages, tools)` methods.
2. `DefaultAIProviderExtension` resolves the two community providers (Anthropic native, OpenAI-compatible) via the same accessor pattern as `get_billing_extension()` / `get_audit_sink()`.
3. `grep -RE "if .*provider *== *['\"](anthropic|openai_compatible)" backend/app/processing/ai/` returns zero hits after the migration; the architecture-guard test enforces this in CI.
4. Existing AI integration tests pass unchanged with the default extension wired in (no behavior delta for community users).
5. A test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file — proving the seam is genuinely extensible.

**Plans:** TBD

#### Phase 227: saml-test-fixture-tmp-path

**Goal:** Stop the committed SAML fixture files from being rewritten on every `pytest` run. Refactor the session-scoped `_regenerate_saml_fixtures` autouse fixture in `backend/tests/test_saml_overlay.py` so the signed XML responses land in a pytest `tmp_path` for the test session instead of mutating `backend/tests/fixtures/saml/idp_response_*.xml.b64`. Rename the committed fixtures to `.xml.b64.template` (immutable templates) or remove them entirely; resolve the docstring's "CI fallback when pysaml2 unavailable" claim by either restoring it for real or deleting the claim.

**Source:** Surfaced during 2026-05-01 v13.3 milestone close — five SAML fixture files were perpetually showing as modified across 9 commits because every pytest invocation rewrote them in place. Promoted from Phase 999.18.

**Requirements:** TESTFIX-01, TESTFIX-02, TESTFIX-03

**Depends on:** None — independent of 225/226 (no shared files).

**Success Criteria** (what must be TRUE):
1. `git status` is clean after a full `pytest backend/tests/test_saml_overlay.py` run (regression: previously always-dirty); a CI step asserts `git diff --quiet backend/tests/fixtures/saml/` post-pytest.
2. `_regenerate_saml_fixtures` writes generated XML responses to a session-scoped `tmp_path` (or session-fixture-managed temp dir); no test path writes into the tracked fixtures directory.
3. The committed `idp_response_*.xml.b64` files are either renamed to `.xml.b64.template` (and the consumers read from the template + emit to `tmp_path`) or removed, matching whichever resolution applies to the docstring's CI-fallback claim.
4. Existing SAML overlay tests (`test_saml_overlay.py`) continue to pass — `pytest backend/tests/test_saml_overlay.py -v` is green.

**Plans:** TBD

#### Phase 228: run-cold-publish-workflows

**Goal:** Convert the wired-but-cold `.github/workflows/publish-{sdks,cli}.yml` workflows from "wired" to "shipped" by executing them at least once end-to-end. Confirm `secrets.PYPI_TOKEN` and `secrets.NPM_TOKEN` exist (or migrate to PyPI Trusted Publishing via `id-token: write`). Validate published artifacts against the README install instructions on a clean machine: `pip install geolens-sdk`, `npm install @geolens/sdk`, `pip install geolens` should each install successfully without local checkout context.

**Source:** `oc-separation-audit-20260430-b.md` §6 (WIRED — never run) / §7 P2. Promoted from Phase 999.17.

**Requirements:** PUBLISH-01, PUBLISH-02, PUBLISH-03, PUBLISH-04

**Depends on:** None — independent of 225/226/227 (publish pipeline lives entirely in `.github/workflows/` + package metadata).

**Success Criteria** (what must be TRUE):
1. `secrets.PYPI_TOKEN` and `secrets.NPM_TOKEN` are confirmed present in repository secrets (or replaced with Trusted Publishing for PyPI), documented in the phase VERIFICATION.md.
2. `publish-sdks.yml` completes a green end-to-end run on `main` or a release tag; `geolens-sdk` is installable from PyPI and `@geolens/sdk` from npm by version.
3. `publish-cli.yml` completes a green end-to-end run; `geolens` CLI is installable from PyPI by version and `geolens --version` returns the published version on a fresh `pip install`.
4. README install instructions are validated against the published artifacts on a machine without the GeoLens checkout — all three install commands (`pip install geolens-sdk`, `npm install @geolens/sdk`, `pip install geolens`) succeed.

**Plans:** TBD

#### Phase 229: post-impl-audit-v13.4

**Goal:** Run the post-implementation audit gate for v13.4 to confirm the milestone's audit-grade targets hold across the new implementation surface (Phases 225–228). Produce a dated `post-impl-2026MMDD-*.md` audit report; triage P1 findings either inline or via tracked deferral; re-run grades to confirm Boundary Integrity ≥ **A+** (held from v13.3), Coupling Health ≥ **B+** (cycle inversion lever from 225), and Seam Quality ≥ **A−** (AIProviderExtension closes the last 🔴 from 226).

**Source:** Mirrors the `/post-impl` close-gate pattern used at v13.2 close (`post-impl-20260430.md`) and v13.3 close (`post-impl-20260501-b.md`).

**Requirements:** PIAUDIT-01, PIAUDIT-02, PIAUDIT-03

**Depends on:** Phases 225, 226, 227, 228 (audits the milestone's full implementation surface).

**Success Criteria** (what must be TRUE):
1. A dated audit report exists at `docs-internal/audits/post-impl-2026MMDD-*.md` covering Phases 225–228 with the standard sections (Boundary, Coupling, Seam, OSS Surface, Findings, Grades).
2. Every P1 finding in the report is either fixed inline (commit referenced in the report) or explicitly deferred with rationale + a tracked backlog phase opened.
3. Post-audit grade re-run records Boundary Integrity ≥ **A+**, Coupling Health ≥ **B+**, Seam Quality ≥ **A−** in the report's grades table.
4. v13.4 milestone is unblocked for close — `/gsd-complete-milestone` runs without surfacing unresolved P1 findings.

**Plans:** TBD

---

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

<details>
<summary>✅ v13.3 Boundary A+ Cleanup (Phases 222-224) — SHIPPED 2026-05-01</summary>

- [x] Phase 222: audit-sink-protocol (5/5 plans) — completed 2026-04-30
- [x] Phase 223: marketplace-billing-extraction (5/5 plans) — completed 2026-04-30
- [x] Phase 224: catalog-god-module-split (8/8 plans) — completed 2026-05-01

15/15 v13.3 requirements satisfied (AUDIT-01..05, BILLING-01..06, DECOUPLE-01..04). Audit grade movements vs v13.1 close: Boundary Integrity A → **A+** (zero 🟡 risks); Seam Quality B → **B+** (AuditSink + BillingExtension promoted to 🟢); Coupling Health B− → **B** (log_action 65→7 chokepoint sites). Overall readiness 3.39 → 3.85 (A) per `post-impl-20260501-b.md`.

</details>

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 6/9 plans executed
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

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

### ~~Phase 999.10: AIProviderExtension Protocol~~ — PROMOTED to Phase 226 (v13.4, 2026-05-01)

Promoted into the v13.4 Boundary Closeout milestone as Phase 226 (`ai-provider-extension-protocol`). See Active Phases above.

---

### ~~Phase 999.11: test_no_processing_imports_catalog architecture guard~~ — INLINED into Phase 225 (v13.4, 2026-05-01)

Inlined into Phase 225 (`processing-port-protocol-cycle-inversion`) because adding the guard before the cycle is inverted would fail CI immediately. The guard ships in the same phase as the cycle inversion. See Active Phases above.

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

### ~~Phase 999.17: Run cold PyPI/npm publish workflows~~ — PROMOTED to Phase 228 (v13.4, 2026-05-01)

Promoted into the v13.4 Boundary Closeout milestone as Phase 228 (`run-cold-publish-workflows`). See Active Phases above.

---

### ~~Phase 999.18: SAML test fixture generator → tmp_path~~ — PROMOTED to Phase 227 (v13.4, 2026-05-01)

Promoted into the v13.4 Boundary Closeout milestone as Phase 227 (`saml-test-fixture-tmp-path`). See Active Phases above.
