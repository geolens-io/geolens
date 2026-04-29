---
gsd_state_version: 1.0
milestone: v13.1
milestone_name: Open-Core Separation P1
status: verifying
stopped_at: Phase 219 context gathered
last_updated: "2026-04-29T22:34:49.058Z"
last_activity: 2026-04-29
progress:
  total_phases: 10
  completed_phases: 8
  total_plans: 30
  completed_plans: 30
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (refreshed 2026-04-26 after cross-repo split)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v13.1 milestone close — Phase 219 verified; ready for `/gsd-complete-milestone`.

## Current Position

Phase: 219 (oc-audit-remediate-idp-mapping) — **COMPLETE**
Plan: 1 of 1 (4 of 4 atomic commits landed: d0e09c17 schema gate, dcbb86af service gate, 1cb06324 tests, 6a79e1e5 doc amendment)
Status: v13.1 milestone close VERIFIED — Boundary Integrity A (≥ A− target) + Seam Quality B (≥ B target) + OSS Surface A− (≥ C target). All three close-gate dimensions met or exceeded.
Last activity: 2026-04-29

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

**Next step:** `/gsd-complete-milestone` to archive v13.1 and roll forward to v13.2.

## Roadmap Snapshot

| Phase | Name | Requirements | Depends on |
|-------|------|--------------|------------|
| 212 | core-settings-decouple | LAYER-01 | — |
| 213 | catalog-authz-relocate | LAYER-02 | — |
| 214 | identity-protocol-extract | IDENT-01, IDENT-02, IDENT-03 | — |
| 215 | sdks-from-openapi | OCSDK-01, OCSDK-02, OCSDK-03, OCSDK-04 | — |
| 216 | geolens-cli-mvp | OCCLI-01..06 | 215 |
| 217 | auth-saml-enterprise | SAML-08..12 | 214 |
| 218 | oc-audit-close-v13.1 | AUDIT-V1 | 212–217 |
| 219 | oc-audit-remediate-idp-mapping | TBD | 218 |

Coverage: 21/21 v13.1 requirements mapped.

## Accumulated Context

### Roadmap Evolution

- Phase 219 added: oc-audit-remediate-idp-mapping (remediate Phase 218 boundary shortfall — OAuth IdP→role mapping in core)

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

Items acknowledged and deferred at v13.1 milestone close on 2026-04-29:

| Category | Count | Disposition |
|----------|-------|-------------|
| quick_tasks | 170 | Cross-cutting backlog dating from 2026-03-16 through 2026-04-26 (v10.x–v13.0 era). Mix of completed-but-untracked, abandoned spikes, and superseded ideas. Run `/gsd-cleanup` to triage before next milestone. |
| uat_gaps | 1 | Phase 216 (216-HUMAN-UAT.md) — 4 open scenarios are documented `human_needed` items: PyPI publish (D-40), OS-native keyring per-platform, interactive Progress UI, refresh-token retry. Not v13.1 close blockers. |
| verification_gaps | 4 | 215, 216 (`human_needed` — deferred user actions per CONTEXT.md); 999.2, 999.4 (P3 backlog phases — not in v13.1 scope). |
| **Total** | **175** | |

These were surfaced by `gsd-sdk query audit-open` at v13.1 close. None are functional defects in v13.1; the 175 reflect cross-milestone hygiene debt (170 quick_tasks) plus the documented `human_needed` deferred user actions that ship alongside v13.1 (PyPI/npm publishes, per-platform keyring testing).

## Session Continuity

Last session: 2026-04-29T18:00:50.491Z
Stopped at: Phase 219 context gathered
Resume file: .planning/phases/219-oc-audit-remediate-idp-mapping/219-CONTEXT.md
