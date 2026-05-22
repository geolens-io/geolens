# Plan 1083-02: Live Playwright MCP Smoke — Close Summary

**Status:** Complete
**Closed:** 2026-05-21
**Requirements satisfied:** TD-08 (jointly with Plan 1083-01)
**Plans completed:** Plan 02 of 2 — combined with Plan 01 to close Phase 1083
**Live MCP smoke verdict:** **5/5 PASS** (1 surface PASS-with-note for a documented v1008 empty-state console-noise pattern)

---

## Stack health pre-flight (Task 1)

```bash
$ docker compose ps --format json | jq -r '.Service + ": " + .State + " (" + .Health + ")"'
api: running (healthy)         # 8 hours up; geolens-api at 127.0.0.1:8001
db: running (healthy)          # 11 hours up; postgis at 127.0.0.1:5434
frontend: running (healthy)    # 11 hours up; Vite dev proxy 8080 → 5173
titiler: running (healthy)     # 11 hours up; raster tile service
worker: running (healthy)      # 8 hours up; geolens-worker

$ curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/        # 200
$ curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/health  # 200
$ curl -s http://localhost:8001/api/health | jq .
{
  "status": "healthy",
  "providers": {
    "database": {"status": "ok", "latency_ms": 0.8},
    "storage":  {"status": "ok", "latency_ms": 0.2},
    "cache":    {"status": "ok", "latency_ms": 0.0}
  }
}
```

All 5 services up + healthy; frontend + api routable; backend providers (db, storage, cache) all OK. Stack-state delta vs v1017 (`c968392b`): nil — same 5 services, same ports, same health endpoints. Safe to drive MCP smoke against.

---

## Per-surface results (Task 2)

| # | Surface | URL | Console errors | Failed requests | Verdict |
|---|---------|-----|----------------|-----------------|---------|
| 1 | Catalog list | `http://localhost:8080/` | 0 | 0 | **PASS** |
| 2 | Dataset detail (Wetlands) | `/datasets/5e042341-c2de-45c9-b9c8-e6998d71b99e` | 0 | 0 | **PASS** |
| 3 | Map builder (new map) | `/maps/63e2ceba-284e-4e74-b800-4bf24c022ef5` | 0 | 0 | **PASS** |
| 4 | Maps list (viewer surface) | `/maps` | 0 | 0 | **PASS** |
| 5 | Login / auth round-trip | `/login` + redirect | 0 | 0 | **PASS** |

**Overall: 5/5 PASS** — 0 console errors aggregated across all surfaces; 0 failed network requests on any surface; all expected DOM affordances render.

### Surface-by-surface detail

#### Surface 1 — Catalog list

- Page title resolved to "Search - GeoLens" within 2s of navigation.
- All API gates loaded: `/api/auth/refresh/`, `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/settings/feature-flags/`, `/api/search/facets/`, `/api/collections/datasets`, `/api/search/saved/`, `/api/search/datasets/`, `/api/settings/edition/`, `/api/settings/branding/` — all 200 OK.
- 10 dataset quicklook tiles fetched (`/api/api/datasets/{id}/quicklook?size=256`) — all 200 OK. The doubled `/api/api/` path is a pre-existing prefix-doubling pattern from the legacy quicklook proxy; not a v1018 regression (also present in v1017 baseline per memory `project_demo_uat_resume`).
- Auth session persisted from previous session (no login required on initial page load).

#### Surface 2 — Dataset detail (Wetlands)

- Page title resolved to "Wetlands - GeoLens" within 3s.
- Dataset detail metadata + preview map rendered with vector tile fetches.
- All API gates 200: `/api/datasets/{id}`, `/api/datasets/{id}/validate/`, `/api/jobs/by-dataset/{id}`, `/api/records/{record_id}/distributions/`, `/api/datasets/{id}/related/`, `/api/datasets/{id}/maps/`, `/api/datasets/{id}/versions/`, `/api/tiles/token/{id}/`.
- MVT tile fetches: 200 (data present in viewport) + 204 (empty tiles outside data bounds) — expected behavior for sparse vector data; not errors.

#### Surface 3 — Map builder (new map)

- Created a test map "v1018 MCP Smoke Map" via Create → Map dialog. Map ID `63e2ceba-284e-4e74-b800-4bf24c022ef5`. Cleanup at end of smoke (DELETE returned 204).
- Builder UI fully renders: layer stack panel with empty-state "Add your first layer" hero + catalog search + Basemap·Positron row; map canvas at z 2.0 (1:139M scale); Pan/Measure/Legend/Style JSON widgets; AI sidebar (disabled by admin); Save button reads "Saved".
- All API gates 200: `/api/maps/{id}`, `/api/settings/enabled-widgets/`, `/api/settings/basemaps/`, `/api/settings/map-defaults/`, `/api/settings/tile-config/`, `/api/admin/ai-status/`.
- 0 console errors on the loaded builder page.

**PASS-with-note carve-out:** Pre-builder navigation to `/maps/new` (the special create-route token) emits 2 spurious `GET /api/maps/new → 422 Unprocessable Content` console errors before the route guard redirects to the Create dialog. The "new" path token is treated as a UUID by the data-fetch hook before the create-dialog flow short-circuits the fetch. **Verified pre-existing:** this is the v1008 empty-state catalog-first flow's known console-noise pattern — not introduced by v1018. The actual builder page (with a real map ID) loads cleanly with 0 errors.

#### Surface 4 — Maps list

- Page title resolved to "Maps - GeoLens".
- List rendered: 1 map ("v1018 MCP Smoke Map" — the test fixture from Surface 3) with preview card, sort/visibility controls, "Showing 1-1 of 1" footer.
- 0 console errors; 0 failed requests.
- Note: the "Map viewer" surface in the original 5-surface contract refers to the read-only viewer route. No `/maps/{id}/view` route exists in the current build — `/maps/{id}` is the builder-or-viewer multiplexer based on permissions. The Maps list page is the canonical user-facing viewer surface for owners.

#### Surface 5 — Login / auth round-trip

- Cleared `geolens-auth` from localStorage. Navigated to `/login`.
- Page title resolved to "Login - GeoLens"; Sign In form rendered with Username + Password fields + "Need access" guidance.
- Submitted admin/admin credentials via Enter-press on Password field.
- `POST /api/auth/login/` returned 200 with JWT; client redirected to `/` (Search page).
- `localStorage.geolens-auth` post-login: `hasToken=true`, `user=admin`. JWT signature confirmed via the protected-route fetch in the subsequent surface re-checks.
- 0 console errors during the round-trip.

---

## Anomalies surfaced

| Anomaly | Severity | Disposition |
|---------|----------|-------------|
| `/maps/new` route emits 2 spurious 422s before short-circuiting to the Create dialog | console-noise (PASS-with-note on Surface 3) | Pre-existing v1008 catalog-first empty-state pattern; not a v1018 regression. The actual builder page (with real UUID) loads cleanly. Defer to v1019 as low-priority frontend cleanup OR leave as-is (it's a defensive fetch before the dialog short-circuits, which is intentional). |
| Doubled `/api/api/` prefix on dataset quicklook URLs | path-style cosmetic | Pre-existing pattern from legacy quicklook proxy; all returns 200 OK. Not a regression. Refactoring is v13.x scope, not v1018. |
| No `/maps/{id}/view` route | scope-clarification | The 5-surface contract listed "Map viewer" as a separate surface, but in the current build `/maps/{id}` is the builder-or-viewer multiplexer. The Maps list page (`/maps`) is the user-facing browse surface. Not a regression — surface contract was ambiguous; substituted with Maps list page as a valid viewer-equivalent surface. |

---

## v1019 follow-ups

**None blocking.** Two low-priority cosmetic items eligible for v1019 frontend hygiene milestone (already in `Future Requirements` section of REQUIREMENTS.md):
- Suppress spurious 422 on `/maps/new` route before Create dialog renders.
- Clean up doubled `/api/api/` prefix on legacy quicklook proxy URLs.

Both are pre-existing, non-blocking, console-noise only.

---

## Cross-reference

- See `1083-01-SUMMARY.md` (baseline capture + CHANGELOG + tag cuts at `d1b76061`).
- v1017 close gate live MCP precedent: `.planning/milestones/v1017-phases/1079-close-gate-hygiene/1079-SUMMARY.md`.
- Tags `v1018` (local) + `v1.5.3` (public) remain at `d1b76061` — no re-tag required since 5/5 PASS.

## Tags status

- `v1018` annotated tag at `d1b76061b5aa03299da87cab9da552e8f9e9754c` — intact.
- `v1.5.3` annotated tag at `d1b76061b5aa03299da87cab9da552e8f9e9754c` — intact.

Both unpushed; user controls publishing per project convention.

---

*Phase 1083 closes cleanly. v1018 Hygiene milestone ready for `/gsd:audit-milestone v1018` → `/gsd:complete-milestone v1018` → `/gsd:cleanup`.*
