---
gsd_state_version: 1.0
milestone: v13.3
milestone_name: Boundary A+ Cleanup
status: executing
stopped_at: Completed 223-02-PLAN.md
last_updated: "2026-05-01T13:08:12.656Z"
last_activity: 2026-05-01
progress:
  total_phases: 15
  completed_phases: 2
  total_plans: 19
  completed_plans: 16
  percent: 84
---

# Project State

## Project Reference

See: .planning/PROJECT.md (refreshed 2026-04-26 after cross-repo split)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 224 — catalog-god-module-split

## Current Position

Phase: 224 (catalog-god-module-split) — EXECUTING
Plan: 4 of 8
Status: Ready to execute
Last activity: 2026-05-01

```
[Phase 222] [Phase 223]
[██████████] [██████████]
  100%        100%          v13.3 phases shipped — BILLING-06 satisfied 2026-04-30
```

## v13.3 Close-Out Status

- Phase 222: COMPLETE (5/5 plans, AUDIT-01..05 satisfied)
- Phase 223: COMPLETE (5/5 plans, BILLING-01..06 satisfied — BILLING-06 close gate `oc-separation-audit-20260430-b.md`)
- Audit grade movements vs v13.1 close: Boundary Integrity A → **A+** (zero 🟡 risks); Seam Quality B → **B+** (AuditSink + BillingExtension promoted to 🟢); Coupling Health B− → **B** (log_action 65→7 chokepoint sites)
- Overall readiness: 3.39 → **3.53** (A−)
- Next milestone close: run `/gsd-complete-milestone v13.3`

## Phase 224 Queue (from /oc-audit follow-ups)

The audit produced 16 findings. Three trivial fixes were applied inline (env-var move from base compose to enterprise overlay, GEOLENS_EDITION explicit set in overlay, GTM doc amendment for Phase 223 completion). The remaining 13 findings split:

- **Phase 224 (P0):** catalog-god-module-split — Split `backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC) into 4 cohesive modules (`service_create.py`, `service_query.py`, `service_lifecycle.py`, `service_grants.py`) behind a thin façade. Largest enterprise-overlay obstacle.
- **Backlog 999.7-999.17:** 11 multi-day / multi-week items (ProcessingPort Protocol, PermissionExtension, WorkflowExtension, AIProviderExtension, geolens.yaml manifest, persistent connector registry, Helm chart, SBOM, geolens-schemas extraction, run cold publish workflows, processing-imports-catalog architecture guard).

## Roadmap Snapshot

| Phase | Name | Requirements | Depends on |
|-------|------|--------------|------------|
| 222 | audit-sink-protocol | AUDIT-01, AUDIT-02, AUDIT-03, AUDIT-04, AUDIT-05 | 221 |
| 223 | marketplace-billing-extraction | BILLING-01, BILLING-02, BILLING-03, BILLING-04, BILLING-05, BILLING-06 | 221 (parallel with 222) |

Coverage: 11/11 v13.3 requirements mapped.

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

### Key Implementation Reference

The v13.1 SAML implementation is ground truth for v13.2:

- `backend/app/modules/auth/saml/` — SAML enterprise overlay registered via `importlib.metadata` entry_points
- `oauth_providers` table — stores `provider_type='saml'` rows
- `User` model `deferred=True` columns (4 SAML columns) — Pitfall 11 mitigation ensuring lossless reactivation by design
- `find_or_create_oauth_user()` — JIT provisioning path that creates User rows for SAML-authenticated users

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

Last session: 2026-05-01T13:08:07.784Z
Stopped at: Completed 223-02-PLAN.md
Resume file: None
