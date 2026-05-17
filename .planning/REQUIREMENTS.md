# Milestone v1010.2 Requirements — Builder Smoke Carryover

**Milestone version:** v1010.2
**Milestone name:** Builder Smoke Carryover
**Goal:** Close the 5 carried-forward items from v1010.1's 2026-05-17 Playwright MCP smoke (1 P1 + 4 P2) so the Map Builder ships clean of all open smoke findings.

**Shape:** Hygiene close — single phase (1050), sequential plans per SF item, single CTRL-01 smoke gate. No new features, no research, no AI integration, no UI design contracts. Each requirement maps 1:1 to a v1010.1 smoke finding with root cause + recommended fix already documented in `.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md`.

**Source of scope:** v1010.1 SMOKE-FINDINGS.md, sections SF-04 through SF-08. Findings dispositioned `deferred-with-rationale` (SF-04) or `deferred-with-rationale — P2 tech-debt` (SF-05..08) at v1010.1 close.

---

## v1010.2 Requirements

### Smoke Carryover (5 reqs)

- [ ] **SMOKE-08**: Map Builder deduplicates MapLibre vector tile sources across layers that share the same `dataset_table_name` — opening a saved map with N layers backed by M unique datasets (M < N) fires roughly N→M unique tile URLs on initial load, not N copies of the same URL. Closes SF-04 / `BUILDER-PERF-DEDUPE-SOURCES`. Touches: `frontend/src/components/builder/hooks/use-builder-layers.ts` source registration, `swapLayerOnMap`, per-layer `removeSource` path, cluster-source override (`cluster-source.ts`), dataset/tile-token signing. Migration: coordinated update to saved-map layer rows if source-id keying contract changes.

- [x] **SMOKE-09**: Post-login redirect to `/` produces zero `net::ERR_FILE_NOT_FOUND` console errors for `blob:` thumbnail URLs. Closes SF-05. Fix path: defer `URL.revokeObjectURL(blob)` until the `<img>` finishes loading OR move revoke to component unmount cleanup. Locate via `git grep "revokeObjectURL" frontend/src`.

- [ ] **SMOKE-10**: Visiting `/login` unauthenticated does NOT fire console-error 401 noise for `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/search/saved/`, `/api/auth/refresh/`. Closes SF-06. Fix path: gate authed-endpoint fetches behind `auth.isAuthenticated` in their React Query hooks, OR suppress error-level logging on these specific 401s in the React Query global error handler. The `/api/admin/ai-status/` probe from a public/anonymous page is the most egregious.

- [ ] **SMOKE-11**: Initial map mount fires exactly ONE `PUT /api/maps/{id}/thumbnail/` request, not two. Closes SF-07. Audit the 500ms debounce in `use-builder-save.ts` (added in v1009.1 SP-16): confirm the debounce wraps the effect-triggered side effect, not just the click-handler path; initial-mount paint events may currently bypass the debounce window.

- [ ] **SMOKE-12**: Saving a map whose basemap loaded successfully on mount does NOT surface a "Basemap connection issue" toast. Closes SF-08. Fix path: re-evaluate basemap-connection check on save so it does NOT fire when the basemap was previously confirmed loaded; likely in `frontend/src/components/builder/hooks/use-builder-save.ts` or `BuilderMap.tsx` error handler. Transient style-fetch errors during save should not surface as user-visible basemap outages.

---

## Future Requirements (deferred — NOT v1010.2)

- **SP-03 / M-02** — fresh-add MapLibre sync race (the `syncInputs` memo closure on `structuralKey`-only key OR `mapReady` timing). Escalated from v1009.1. Workaround: refresh after add. Belongs in a separate builder reliability quick-task or its own milestone — out of scope for v1010.2 because it predates v1010.1.

- **SP-07** — backend `has_quicklook` predicate. Escalated from v1009.1. Frontend `quicklook-cache.ts` already prevents repeats; the honest fix is a backend predicate so the first request per session doesn't 404. Out of scope for v1010.2 because it predates v1010.1 and requires a backend API change.

- **SP-12** — representative-fraction "1:N" pane in `MapCoordReadout`. New feature, not a bug. Out of scope.

## Out of Scope (explicit exclusions)

- **Any new feature work** — v1010.2 is strictly hygiene close. Adding features here would dilute the milestone's reason for existing (close the last 5 v1010.1 smoke findings cleanly so v1010-line builder polish is done).

- **999.x parked phases** (tenant scoping, helm chart, SBOM, connector registry, schemas package) — these are parked-future work tracked outside numbered milestone flow.

- **SP-03 / SP-07 / SP-12** — v1009.1 escalations + the feature ticket; see Future Requirements above.

---

## Traceability

| REQ-ID | Phase | Plan(s) | Status |
|--------|-------|---------|--------|
| SMOKE-08 | 1050 | 01 | Open |
| SMOKE-09 | 1050 | 02 | Open |
| SMOKE-10 | 1050 | 03 | Open |
| SMOKE-11 | 1050 | 04 | Open |
| SMOKE-12 | 1050 | 05 | Open |

*(Plan 06 — CTRL-01 — is the close gate; verifies SMOKE-08..12 collectively, no direct REQ mapping.)*
