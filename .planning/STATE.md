---
gsd_state_version: 1.0
milestone: v13.4
milestone_name: Boundary Closeout
status: executing
stopped_at: "/oc-audit 2026-05-02 closed end-to-end: 4 Tier-A inline fixes (6db19582, d92ee171, 259ebc72, 9d805949) + 4 new backlog entries (999.21, 999.22 — god-module splits) + 2 backlog → v13.4 promotions (999.20 → 230 CatalogPort, 999.19 → 231 EmbeddingProviderExtension). Coupling target lifted B+ → A−. Phase 228 Wave 2/3 still BLOCKED on @geolens npm org approval; Phase 230 + 231 ready for /gsd-discuss-phase."
last_updated: "2026-05-02T18:30:00.000Z"
last_activity: 2026-05-02
progress:
  total_phases: 13
  completed_phases: 3
  total_plans: 15
  completed_plans: 12
  percent: 80
---

# Project State

## Project Reference

See: .planning/PROJECT.md (refreshed 2026-05-01 after v13.3 close)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 228 — run-cold-publish-workflows

## Current Position

Phase: 228 (run-cold-publish-workflows) — EXECUTING
Plan: 2 of 4
Status: Ready to execute
Last activity: 2026-05-02 - Completed quick task 260502-c19: star-audit command review (correctness + readiness checks)

## Roadmap Snapshot

| Phase | Name | Requirements | Depends on |
|-------|------|--------------|------------|
| 225 | processing-port-protocol-cycle-inversion | PROCESS-01, PROCESS-02, PROCESS-03, PROCESS-04, PROCESS-05 | 224 (✅ shipped) |
| 226 | ai-provider-extension-protocol | AIEXT-01, AIEXT-02, AIEXT-03, AIEXT-04, AIEXT-05 | 225 |
| 227 | saml-test-fixture-tmp-path | TESTFIX-01, TESTFIX-02, TESTFIX-03 | — |
| 228 | run-cold-publish-workflows | PUBLISH-01, PUBLISH-02, PUBLISH-03, PUBLISH-04 | — |
| 230 | catalog-port-protocol-symmetric | CATPORT-01, CATPORT-02, CATPORT-03, CATPORT-04, CATPORT-05 | 225 (sequential — both touch core/Protocol surface) |
| 231 | embedding-provider-extension-protocol | EMBPROV-01, EMBPROV-02, EMBPROV-03, EMBPROV-04, EMBPROV-05 | — (independent, can ship in parallel) |
| 229 | post-impl-audit-v13.4 | PIAUDIT-01, PIAUDIT-02, PIAUDIT-03 | 225, 226, 227, 228, 230, 231 |

Coverage: 30/30 v13.4 requirements mapped (original 20 + 10 added 2026-05-02 with Phase 230/231 promotions).

**Audit-grade targets (verified by Phase 229):** Boundary Integrity ≥ **A+** (hold v13.3 close grade) · Coupling Health **B → A−** (BOTH cycle directions inverted via 225 + 230) · Seam Quality **B+ → A−** (Phase 226 closes AI dispatch 🔴; Phase 231 closes the embeddings 🔴).

## v13.3 Close-Out Summary (shipped 2026-05-01)

- 3 phases shipped: 222 (audit-sink-protocol), 223 (marketplace-billing-extraction), 224 (catalog-god-module-split)
- 18 plans, 15/15 requirements satisfied (AUDIT-01..05, BILLING-01..06, DECOUPLE-01..04)
- 83 commits, 141 files changed (+19,316 / −2,211 LOC) across 2026-04-30 → 2026-05-01
- Audit grade movements vs v13.1 close: Boundary Integrity A → **A+** (zero 🟡 risks); Seam Quality B → **B+**; Coupling Health B− → **B**
- Overall readiness: 3.39 → **3.85 (A)** per `post-impl-20260501-b.md`
- Archive: `.planning/milestones/v13.3-ROADMAP.md` + `.planning/milestones/v13.3-REQUIREMENTS.md`

## Next Action

Three v13.4 phases ready to discuss/plan in parallel — none blocked on the npm org approval that's holding up Phase 228:

1. **Phase 231 (EmbeddingProviderExtension)** — `/gsd-discuss-phase 231 ${GSD_WS}` then `/gsd-plan-phase 231 ${GSD_WS}`. Smallest of the three (2-3d), independent of all other v13.4 phases. Closes the last direct provider-SDK import in `processing/`.
2. **Phase 230 (CatalogPort)** — `/gsd-discuss-phase 230 ${GSD_WS}` then `/gsd-plan-phase 230 ${GSD_WS}`. Larger (~1w), depends on Phase 225 (✅ shipped). Lifts Coupling Health audit-grade target B+ → A−.
3. **Phase 228 Wave 2/3** — Still BLOCKED on external `@geolens` npm org approval. Plan 04 (docs update) is independently executable — `/gsd-execute-phase 228 ${GSD_WS}` if you want to pick that up.

Phase 229 (post-impl audit gate) now depends on Phases 225, 226, 227, 228, 230, 231 — runs last.

## Phase 224 Queue (from /oc-audit follow-ups)

The audit produced 16 findings. Three trivial fixes were applied inline (env-var move from base compose to enterprise overlay, GEOLENS_EDITION explicit set in overlay, GTM doc amendment for Phase 223 completion). The remaining 13 findings split:

- **Phase 224 (P0):** catalog-god-module-split — Split `backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC) into 4 cohesive modules (`service_create.py`, `service_query.py`, `service_lifecycle.py`, `service_grants.py`) behind a thin façade. Largest enterprise-overlay obstacle. ✅ shipped 2026-05-01.
- **v13.4 (active):** Phases 225 (999.7 → 225 ProcessingPort), 226 (999.10 → 226 AIProviderExtension), 227 (999.18 → 227 SAML fixture tmp_path), 228 (999.17 → 228 cold publish), plus inlined architecture guard (former 999.11 → folded into 225) and milestone audit gate (229).
- **Backlog (remaining):** Phase 999.6 (tenant scoping — Cloud prereq), 999.8 (PermissionExtension), 999.9 (WorkflowExtension), 999.12 (geolens.yaml manifest), 999.13 (persistent connector registry), 999.14 (Helm + AMI), 999.15 (SBOM + signed images), 999.16 (geolens-schemas extraction), 999.19 (EmbeddingProviderExtension), 999.20 (CatalogPort), 999.21 (split catalog/maps/service.py), 999.22 (split catalog/search/service.py).

## /oc-audit follow-ups (2026-05-02 audit run)

Audit shipped at `docs-internal/audits/oc-separation-audit-20260502.md`. Overall held at A− (3.50/4.0). Two grade lifts (Seam Quality B+ → A−, Coupling Health B → B+) offset by one ding (Boundary Integrity A+ → A from share/embed token "(enterprise only)" copy lying without enforcement).

Tier A — fixed inline 2026-05-02 (4 atomic commits):
- `6db19582` — strip false "(enterprise only)" copy from share/embed token surfaces (closes the only outstanding 🟡 cluster)
- `d92ee171` — wire AuthExtension.get_auth_methods() into /auth/config/ (Seam #2 🟡 → 🟢)
- `259ebc72` — defer provider-SDK imports out of module scope in `processing/ai/` + add CI guard `test_no_module_level_provider_sdk_imports_in_processing_ai`
- `9d805949` — SPDX headers on 4 hand-written SDK files

Tier B — 4 backlog entries added 2026-05-02; 2 immediately promoted to v13.4 phases the same day:
- 999.20 (CatalogPort) → **Phase 230** (catalog-port-protocol-symmetric) — lifts Coupling target B+ → A−
- 999.19 (EmbeddingProviderExtension) → **Phase 231** (embedding-provider-extension-protocol)
- 999.21 (split catalog/maps/service.py) — stays backlog P2
- 999.22 (split catalog/search/service.py) — stays backlog P2
Existing 999.8/9/12/14/16 cross-referenced to the 2026-05-02 audit (no promotion).

Tier C — external blocker: Phase 228 Wave 2/3 cannot proceed until `@geolens` npm org approval lands.

## Phase 218 / 219 close-gate record

**Pre-219 (BLOCKED):** Phase 218 closing audit graded Boundary Integrity B− vs target A− because of one architectural P0 — OAuth IdP→role mapping (`oauth/{schemas,service,models}.py`) executed unconditionally in community despite `repo-split.md` classing it as Enterprise. Phase 217 documented this gating as out-of-scope; Phase 218 (scoped audit-close only) surfaced it as the v13.1 close blocker.

**Post-219 (VERIFIED):** Phase 219 (`oc-audit-remediate-idp-mapping`) closed the cluster on 2026-04-29 in three code commits + one doc amendment. The 2026-04-29 audit re-run confirmed Boundary Integrity grade A (zero 🔴 violations under the OAuth IdP cluster).

**Final grade results vs v13.1 close targets:**

| Dimension | v13.1 Close (post-219) | Target | Met? |
|-----------|------------------------|--------|------|
| Boundary Integrity | A | A- | ✅ YES (exceeds) |
| Seam Quality | B | B | ✅ YES |
| OSS Surface Readiness | A- | C | ✅ YES (exceeds) |

**v13.1 close artifact:** `docs-internal/audits/oc-separation-audit-v13.1-close.md` — amended in place per Phase 219 D-12. `## ⚠ MILESTONE CLOSE BLOCKED` replaced with `## ✅ MILESTONE CLOSE VERIFIED — Phase 219 closed boundary gap`. Pre-remediation BLOCKED narrative preserved as `### Pre-remediation state (2026-04-29)` subsection for audit-trail traceability.

## Accumulated Context

### Roadmap Evolution

- Phase 219 added: oc-audit-remediate-idp-mapping (remediate Phase 218 boundary shortfall — OAuth IdP→role mapping in core)
- v13.2 phases 220-221 defined: promotes backlog phase 999.7 (edition lifecycle runbooks + data preservation + user continuity + CI verification)
- v13.3 phases 222-223 defined: closes two P1 audit items from oc-separation-audit-20260430.md — AuditSink Protocol (65 log_action() sites → extensible sink) and AWS Marketplace extraction (boto3 out of core)
- v13.4 phases 225-229 defined (2026-05-01): closes the last 🔴 seams from `oc-separation-audit-20260430-b.md` — invert catalog↔processing cycle (225 promoted from 999.7, with 999.11 architecture guard inlined), AIProviderExtension seam (226 promoted from 999.10), SAML fixture tmp_path (227 promoted from 999.18), cold publish workflows (228 promoted from 999.17), post-impl audit gate (229).

### Key Implementation Reference

The v13.1 SAML implementation is ground truth for v13.2:

- `backend/app/modules/auth/saml/` — SAML enterprise overlay registered via `importlib.metadata` entry_points
- `oauth_providers` table — stores `provider_type='saml'` rows
- `User` model `deferred=True` columns (4 SAML columns) — Pitfall 11 mitigation ensuring lossless reactivation by design
- `find_or_create_oauth_user()` — JIT provisioning path that creates User rows for SAML-authenticated users

### v13.4 Design Decisions Pending

- **Phase 225**: ProcessingPort surface area — does the Protocol expose a small set of high-level catalog accessors (e.g., `get_dataset_for_processing(id)`) or a finer-grained set per-call site? Resolve via `/gsd-discuss-phase 225`. Also: where the default implementation lives (likely `backend/app/core/processing_port.py`).
- **Phase 226**: whether `AIProviderExtension` exposes `complete` + `stream` as separate methods (mirrors current call sites) or unifies on a single async-iterator method; whether tool/function-call schema is part of the Protocol or passed opaquely. Resolve via `/gsd-discuss-phase 226`.
- **Phase 227**: whether to keep committed `.xml.b64.template` files (with regen-from-template at session start) or remove the CI-fallback claim and ship session-only generation. Resolve via `/gsd-discuss-phase 227`.
- **Phase 228**: whether to migrate to PyPI Trusted Publishing (`id-token: write` already reserved in workflow) or keep `secrets.PYPI_TOKEN`. npm has no equivalent — keeps `secrets.NPM_TOKEN`.

### v13.3 Design Decisions Pending

- **Phase 222**: sync vs async emit for AuditSink; whether log_action() becomes the default sink body or is removed entirely; sink-failure semantics implementation approach. Resolve via `/gsd-discuss-phase 222`.
- **Phase 223**: whether `aws_marketplace_product_code` / `aws_marketplace_public_key_version` move to the enterprise overlay's settings or remain as opaque pass-through env vars in core Settings. Either is acceptable per BILLING-05.

## Cross-Repo Note (2026-04-26)

The following planning artifacts were relocated from this repo to the `getgeolens.com` repo on 2026-04-26 because they describe work executed in that repo:

- v14.0 Marketing Site (shipped 2026-04-13) — milestones/v14.0-*, research/v14.0-archive/
- v15.0 Documentation Site (in progress) — phases 223–226, ROADMAP.md, REQUIREMENTS.md, MILESTONES.md, research/{ARCHITECTURE,FEATURES,PITFALLS,STACK,SUMMARY}.md
- 999.5 Style System Alignment (shipped 2026-04-26) — phases/999.5-*

The following stay in this repo because they describe work executed in this repo:

- 999.1 3D Viewer (toggle terrain extrusions) — geolens frontend
- 999.2 PostGIS 3D Detection metadata — geolens backend
- 999.3 GeoJSON-Z Delivery endpoint — geolens backend
- 999.4 Shared Vector Staging Pipeline — geolens backend
- All quick/* tasks — geolens app work
- ui-reviews/ — geolens UI audits
- All milestones/v[1-13].* archives — geolens app history

## Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260425-h8k | Review map builder labeling with Playwright | 2026-04-25 | pending | Verified | [260425-h8k-review-map-builder-labeling-with-playwri](./quick/260425-h8k-review-map-builder-labeling-with-playwri/) |
| 260425-lbc | Fix map overlay positioning conflicts (filter chips vs measure widget, bottom-left stacking) | 2026-04-25 | cd2e5a3f | Needs Review | [260425-lbc-in-the-map-builder-review-the-map-overla](./quick/260425-lbc-in-the-map-builder-review-the-map-overla/) |
| 260425-oxh | Layer popup config: enable/disable + custom expression with validation | 2026-04-25 | 8ca90a9f | Verified | [260425-oxh-layer-popup-config-enable-disable-custom](./quick/260425-oxh-layer-popup-config-enable-disable-custom/) |
| 260425-sl1 | Address backend test debt (15 failures from audit 2026-04-25) — restored green-baseline (1965/1965) | 2026-04-26 | d6c5a4c8 | Verified | [260425-sl1-address-the-debt-in-docs-internal-audits](./quick/260425-sl1-address-the-debt-in-docs-internal-audits/) |
| 260426-ihc | PR1 of post-impl-20260426-HANDOFF: search hot-path caching (PERF-2 + PERF-7) — 30s anon-only response cache on /search/datasets and /search/facets | 2026-04-26 | 7aebc4d8 | Verified | [260426-ihc-pr1-search-hot-path-caching-perf-2-perf-](./quick/260426-ihc-pr1-search-hot-path-caching-perf-2-perf-/) |
| 260426-m5d | PR2 of post-impl-20260426-HANDOFF: search/maps function decomposition (KISS-1 + KISS-2 + PERF-6) — split search_datasets, extract _bulk_fetch_dataset_metadata, eliminate post-save get_map_with_layers re-fetch | 2026-04-26 | 550179c4 | Verified | [260426-m5d-pr2-search-maps-function-decomposition-k](./quick/260426-m5d-pr2-search-maps-function-decomposition-k/) |
| 260502-c19 | Review `.claude/commands/star-audit.md` — correctness fixes + add Subagent F (release readiness) + Phase 2.5 gate + F.10 visitor-facing OC check (defers engineering-level OC to /oc-audit) | 2026-05-02 | 325cede3 | Verified | [260502-c19-review-the-claude-command-claude-command](./quick/260502-c19-review-the-claude-command-claude-command/) |

## Deferred Items

### v13.2 milestone close (2026-04-30)

| Category | Count | Disposition |
|----------|-------|-------------|
| quick_tasks | 170 | Same cross-milestone backlog carried over from v13.1 close. Run `/gsd-cleanup` to triage. |
| uat_gaps | 1 | Phase 220 (220-HUMAN-UAT.md) — UAT-2 lifecycle CI confirmation. Local equivalent passed (3 lifecycle tests + lifecycle marker INCLUDED locally with overlay installed); CI literal log line confirmation blocked on Actions free-tier billing exhaustion through 2026-04-30. Reset 2026-05-01. Functional behavior already verified. |
| verification_gaps | 1 | Phase 220 (220-VERIFICATION.md) — `human_needed` for the same UAT-2 item. |
| **Total** | **172** | |

Surfaced by `gsd-sdk query audit-open` at v13.2 close. None are functional defects in v13.2; full backend suite (2036/2036 passed, 62.29% coverage) and local CI-equivalent gates (ruff + format + openapi + sdks + bandit + frontend lint/tsc/vitest) all green at close.

### v13.1 milestone close (2026-04-29)

| Category | Count | Disposition |
|----------|-------|-------------|
| quick_tasks | 170 | Cross-cutting backlog dating from 2026-03-16 through 2026-04-26 (v10.x–v13.0 era). Mix of completed-but-untracked, abandoned spikes, and superseded ideas. Run `/gsd-cleanup` to triage before next milestone. |
| uat_gaps | 1 | Phase 216 (216-HUMAN-UAT.md) — 4 open scenarios are documented `human_needed` items: PyPI publish (D-40), OS-native keyring per-platform, interactive Progress UI, refresh-token retry. Not v13.1 close blockers. |
| verification_gaps | 4 | 215, 216 (`human_needed` — deferred user actions per CONTEXT.md); 999.2, 999.4 (P3 backlog phases — not in v13.1 scope). |
| **Total** | **175** | |

These were surfaced by `gsd-sdk query audit-open` at v13.1 close. None are functional defects in v13.1; the 175 reflect cross-milestone hygiene debt (170 quick_tasks) plus the documented `human_needed` deferred user actions that ship alongside v13.1 (PyPI/npm publishes, per-platform keyring testing).

## Session Continuity

Last session: 2026-05-02T12:07:16.740Z
Stopped at: Phase 228 Wave 1 ✓; Wave 2 partial: NPM_TOKEN set + npm org claim PENDING approval; PyPI Trusted Publishing setup blocked until org approves
Resume file: .planning/phases/228-run-cold-publish-workflows/228-02-PLAN.md
