---
status: tech_debt
milestone: v1035
audited: 2026-05-30
verdict: CLEAR-TO-TAG
requirements: 12/12
---

# v1035 Builder, Maps & Export Bug Sweep — Milestone Audit

**Verdict: CLEAR-TO-TAG** (`tech_debt`). 12/12 requirements satisfied; SEC-01 + EXP-01 live-verified on the running stack; full standard gate green.

## Requirement coverage (12/12)
| Req | Phase | Status |
|-----|-------|--------|
| SEC-01 | 1156 | ✅ leak closed across 5 entry points; live-verified (anon 404 for public+internal) |
| EXP-01 | 1157 | ✅ anon export of public+published (live: 200, 4MB) |
| EXP-02 | 1157 | ✅ allow/deny regression matrix (`test_export_access.py`) |
| API-01 | 1157 | ✅ trailing-slash dual-shape alias |
| BLDR-01 | 1158 | ✅ raster basemap stays below data (vitest + e2e) |
| BLDR-02 | 1158 | ✅ terrain eye toggles 3D (vitest getTerrain null/set) |
| BLDR-03 | 1158 | ✅ terrain row suppressed (live: clean 7-row stack). "Copy N of M" badge deferred (net-new UI) |
| BLDR-04 | 1158 | ✅ hypso-tint hides with parent (vitest) |
| MAPS-01 | 1159 | ✅ createRoot warning fixed (dev-HMR cached-root guard); console-hygiene e2e |
| MAPS-02 | 1159 | ✅ blob-url-cache eviction→revoke vitest |
| HYG-01 | 1159 | ✅ registerBlobUrlRevocation moved to useEffect |
| QA-01 | 1160 | ✅ live close-gate (all 6 items) |

## Integration: CLEAN
All gates green (typecheck 0 · vitest 2640 · e2e:smoke:core 31 · e2e:smoke:builder 26 · backend tiles+export 127 · i18n 2 · openapi-check no-drift). SEC-01 + EXP-01 round-tripped live (flip-to-internal → 404 → revert → 200). No new deps/migrations.

## Inline fixes found during the milestone (not regressions — caught + fixed)
- **1156 BLOCKER (Wave-2 test):** `port.check_dataset_access_or_anonymous` didn't exist on the port → the SEC-01 fix was non-functional at runtime. Fixed (direct import) + follow-up preserved the 401-for-private contract.
- **1158 BLOCKER (code review CR-01):** shift-click range bulk-delete could silently delete the hidden terrain layer record. Fixed (`selectableRowIds` filter).
- 1156/1157/1158/1159 code reviews otherwise clean; INFO/WARNING findings fixed inline or already-covered.

## Carry-forward (tech_debt)
- **BLDR-TILE-RACE:** ~20% transient tile-token 403 in `builder-v1-5` drag-from-catalog (vector `.pbf` fetched before its HMAC sig via `transformRequest`). **Pre-existing** (v1034 shipped with the same console-error, 22/1 — confirmed via the v1034 MILESTONES record), NOT a v1035 regression. Non-functional (tiles recover). Mitigated `retries: 2`; proper fix at the token/transformRequest ordering layer.
- **CI-01-v1030:** GH Actions billing prerequisite (standing ops blocker, unchanged).
- BLDR-03 "Copy N of M" duplicate badge (deferred — net-new UI vs the milestone's no-new-features constraint).

## Method
Orchestrator-driven live MCP/curl for all close-gate verification (executor subagents lack `mcp__playwright__*`). Backend api + frontend restarted before the gate (fresh bundles — avoided the stale-bundle hazard).
