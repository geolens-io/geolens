# Next-Milestone Draft — Map Builder Marketing-Ready

**Source:** 6 dogfooding findings + aux items from quick task `260524-o57-adk-high-peaks-data/260524-o57-API-ISSUES.md`
**Drafted:** 2026-05-24
**Status:** DRAFT — ready to feed into `/gsd-new-milestone` when you decide to start

---

## Suggested Framing

**Working name:** `v1024 Map Builder Marketing-Ready` (or `v1024 Composition Quality`)
**Public tag target:** `v1.5.9` (SemVer patch — UI/rendering bug fixes, no API/schema/migration changes)

**Why this is a real milestone, not a bug sweep:**
- Each of the 6 findings is independently reproducible from a single user session — these aren't theoretical issues
- 2 of them (CRITICAL builder-reorder + HIGH DEM-maxzoom) affect every user who tries to compose a map with vectors-over-raster + terrain — i.e. the canonical map builder use case
- The dogfooding evidence is verbatim browser-console output + verified file:line root causes; no investigation phase needed
- Marketing materials (screenshots, embeds, demo videos) are blocked on these — fixing them unlocks a category of GeoLens collateral that the team has been wanting

**HARD INVARIANT for this milestone:**
> A freshly-composed map at `localhost:8080/maps/{new_id}` opens in the builder with **zero console errors/warnings** and the user-set layer order (vectors above rasters) is preserved across reload. Verified via live Playwright MCP, not just unit tests.

---

## Phase Breakdown

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1101 Builder Reorder Fix | Builder UI drag-reorder of vectors above rasters renders correctly without page reload | BUILDER-01, BUILDER-02 | — |
| 1102 DEM Terrain Maxzoom | Replace hardcoded `maxzoom=18` in raster tile token with per-dataset overview metadata | TERRAIN-01, TERRAIN-02 | — |
| 1103 Basemap Toast Triage | Disambiguate genuine basemap connection errors from MapLibre internal errors; reposition the toast | TOAST-01, TOAST-02, BASEMAP-01 | Phase 1102 (terrain errors are the toast's main false-positive trigger) |
| 1104 terrain_config Persistence | `terrain_config={enabled:false}` in `POST /api/maps/` survives the first frontend open | TERRAIN-03 | — |
| 1105 Sprite Refs Cleanup | Resolve `road_` / `us-state_` openfreemap Positron sprite warnings | SPRITE-01 | — |

**Total:** 5 phases (could collapse 1104 + 1105 into Phase 1103 if scope is too thin)

---

## Requirements

| ID | Severity | Source finding | Acceptance |
|----|----------|----------------|------------|
| BUILDER-01 | CRITICAL | API-ISSUES Issue 6 | Drag vector above raster in builder → vector renders on top immediately, no reload required |
| BUILDER-02 | CRITICAL | API-ISSUES Issue 6 follow-up | New regression test: e2e:smoke:builder asserts vector-above-raster ordering survives PATCH `/api/maps/{id}/layers` + reload |
| TERRAIN-01 | HIGH | API-ISSUES Issue 3, root cause `backend/app/processing/tiles/router.py:464-472` | Replace hardcoded `maxzoom=18` with per-dataset overview pyramid lookup (DEM-specific) |
| TERRAIN-02 | HIGH | API-ISSUES Issue 3 follow-up | New raster integration test: terrain-enabled saved map opens without `dem dimension mismatch` console error |
| TOAST-01 | HIGH | API-ISSUES Issue 5, root cause `BuilderMap.tsx:408-437` | Stop routing MapLibre internal errors (no HTTP status) into the 5xx basemap-error bucket |
| TOAST-02 | MEDIUM | API-ISSUES Issue 4 | Reposition basemap-error toast from `top-3 left-3` to a non-colliding position (top-right, or anchor to a corner with collision avoidance vs. NavigationControl) |
| BASEMAP-01 | HIGH | API-ISSUES Issue 5 corollary | Confirm Positron basemap loads cleanly when no terrain layer is present; if it doesn't, fix the actual basemap fetch path |
| TERRAIN-03 | MEDIUM | API-ISSUES Issue 2 | `POST /api/maps/` with `terrain_config={enabled:false}` is preserved on first frontend open — no auto-enable behavior |
| SPRITE-01 | LOW | API-ISSUES Issue 1 | Filter or resolve `road_` / `us-state_` sprite-missing warnings from openfreemap Positron upstream |

**Coverage:** 9 requirements mapped across 5 phases, 0 orphans.

---

## Aux Findings Already Tracked (defer or absorb)

| Item | Disposition |
|------|-------------|
| Form-encoded login docstring gap | Doc fix only — could ride on Phase 1101 |
| `DELETE /api/auth/api-keys/{id}` self-deletion blocked | Defer to a future auth-ergonomics milestone |
| `POST /api/auth/login` 429 missing `Retry-After` header | Defer or absorb into Phase 1103 if cheap |
| Upload status code inconsistency | Investigate as part of TERRAIN-02 raster-ingest tests |
| Vite proxy large-body drop (>500MB) | Operator workaround documented in compose script README; defer |
| `docker compose up -d --build` vs. `restart` interaction | Documentation gap, no fix needed |

---

## Estimated Scope

- **Code surface:** ~5-8 files per phase, mostly frontend (`frontend/src/components/builder/`, `BuilderMap.tsx`) + 1-2 backend (`backend/app/processing/tiles/router.py`)
- **Risk:** LOW — these are bug fixes, not architectural changes. Each phase has a verifiable browser-console outcome.
- **Total elapsed:** 1-3 days assuming the executor uses live MCP verify per phase (no flaky e2e roundtrips)

---

## Success Criteria

1. The marketing map at `c39be324-6815-40e5-8143-00a2723827b2` opens with **zero browser console errors/warnings** after the milestone ships
2. Re-running `scripts/marketing-data/adk-high-peaks/compose_marketing_maps.py` end-to-end produces a working map with no manual `PUT /api/maps/{id}` post-fix needed
3. `e2e:smoke:builder` extended with at least 1 vector-above-raster reorder regression test
4. Marketing team can produce a screenshot at z14–z16 with crisp aerial + visible terrain hillshade + visible vector overlays in one frame
5. The aerial-quality limitation (3.5 MB ArcGIS REST exportImage) is OUT OF SCOPE for this milestone — capture as a follow-up; this milestone is about the rendering pipeline, not the data source

---

## How to Promote

When ready, run:
```
/gsd:new-milestone
```

Then paste this draft into the conversation OR reference this file path:
`.planning/quick/260524-o57-adk-high-peaks-data/NEXT-MILESTONE-DRAFT.md`

The `gsd-roadmapper` should pick up the phase breakdown and requirement mapping directly. Tighten the phase names, push back on requirement ordering if needed, and let the roadmapper do its standard goal-backward coverage analysis.

---

## Cross-Reference

- **Source dogfooding report:** [260524-o57-API-ISSUES.md](260524-o57-API-ISSUES.md) — 344 lines, full repro + file:line root causes
- **Source quick task:** [260524-o57-SUMMARY.md](260524-o57-SUMMARY.md) — context for why these findings emerged
- **Marketing map (test target for the milestone):** `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2`
- **Reproduction scripts:** `scripts/marketing-data/adk-high-peaks/` — end-to-end rerun for live testing during the milestone
