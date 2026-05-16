# Phase 1049 Resume Note

**Last session paused:** 2026-05-16 — after Task 2 (seed) complete, before Task 3 (MCP login + builder open).

## Where we are in PLAN.md

- [x] Task 1 — Rebuild Docker stack fresh (`docker compose down -v && up -d --build`); all 5 services healthy.
- [x] Task 2 — Seed test map + 8 layers. Login flow works (form-encoded POST `/auth/login`, no trailing slash). Datasets seeded from `~/.geolens/cache/`.
- [ ] **Task 3 — MCP Smoke Pass A: Auth + Map open** ← RESUME HERE.
- [ ] Task 4 — Pass B Lazy-load
- [ ] Task 5 — Pass C Debounce + rAF
- [ ] Task 6 — Pass D Bulk-delete
- [ ] Task 7 — Pass E LayerStyleEditor split + popup_config
- [ ] Task 8 — Write SMOKE-FINDINGS.md
- [ ] Task 9 — Fix P0/P1 inline
- [ ] Task 10 — Post-fix re-smoke
- [ ] Task 11 — Checkpoint:human-verify

## On-disk state for resume

- `.planning/phases/1049-mcp-smoke-verification/.test-jwt` — admin JWT (form-encoded login; expires ~1hr — re-login if needed)
- `.planning/phases/1049-mcp-smoke-verification/.api-key` — API key (`6EoRuUDJgnfCAFjWVYgQYugUzunbyq5RzMEv2sadJBY`, scopes default)
- `.planning/phases/1049-mcp-smoke-verification/.test-map-id` — `c868cc3a-a3a0-4714-b559-67b3f2b478e2`
- Map URL: `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2`
- Map has **8 layers** alternating between `ne_10m_reefs` (DS1=`13100933-...`) and `ne_10m_admin_0_countries` (DS2=`c50289...`)

## API gotchas (from this session)

- Backend login: `POST http://localhost:8001/auth/login` (no `/api` prefix, no trailing slash) with **`Content-Type: application/x-www-form-urlencoded`** and body `username=admin&password=admin`. Returns `{access_token, refresh_token, ...}`.
- Most other backend endpoints: `http://localhost:8001/<path>/` with trailing slash, JSON body, `Authorization: Bearer $JWT`. **No `/api` prefix on the backend host directly.** Frontend nginx proxies `/api/*` → `http://api:8000/*`.
- Frontend reachable at `http://localhost:8080`. Admin/admin from `.env` defaults.
- Docker stack: 5 services (db, api, worker, titiler, frontend) — all healthy.

## Resume command (start fresh session)

```
/loop  ↑ already-pasted plan path
```

Or directly:

```
/gsd-execute-phase 1049
```

The execute-phase orchestrator will pick up at Task 3 since Task 1–2 acceptance criteria are already met (`.test-jwt`, `.test-map-id`, healthy stack). Or call the gsd-executor agent directly with the plan path:

```
Read .planning/phases/1049-mcp-smoke-verification/1049-01-mcp-smoke-and-fixes-PLAN.md and resume at Task 3.
JWT and map id are at .test-jwt / .test-map-id.
Stack already rebuilt fresh + healthy.
```

## v1010 surfaces to exercise (recap from PLAN.md)

1. **Lazy-load (PERF-05):** click ⚙ Settings rail → confirm SceneSpinnerFallback briefly + chunk fetch in network. Open layer with raster source → check basemap-group / DEM scene.
2. **Debounce + rAF (PERF-04):** drag opacity slider on Layer 1 → no save fired during drag. Drag color picker on DataDrivenStyleEditor. Type in filter editor.
3. **Bulk-delete (PERF-03):** shift-click 3 layers → BulkActionBar appears (overflow popover for delete per v1009.1 SP-01) → confirm exactly **1** `POST */layers/bulk-delete` in network.
4. **LayerStyleEditor split (CODE-02/CB-07):** toggle render mode on a fill layer → per-mode child editor swaps without flicker.
5. **popup_config error (FOLLOWUP-01):** open Popup tab on a layer, enter `{{NONEXISTENT_COLUMN}}` template, save → named error toast appears. Clear + save → success toast.

## Screenshots

Save to `.planning/phases/1049-mcp-smoke-verification/screenshots/01-{pass}-{NN}.png`. Directory is gitignored (whole `.planning/` is). Reference filenames in `1049-SMOKE-FINDINGS.md`.

## Final close steps after Task 11 approved

1. Write Phase 1049 SUMMARY.md
2. Write Phase 1049 VERIFICATION.md (status: passed | gaps_found)
3. `gsd-audit-milestone` → produces `.planning/v1010.1-MILESTONE-AUDIT.md`
4. `gsd-complete-milestone v1010.1` → archives ROADMAP/REQUIREMENTS/AUDIT to `.planning/milestones/v1010.1-*.md` + tags `v1010.1`
5. `gsd-cleanup` → moves `.planning/phases/1049-*/` → `.planning/milestones/v1010.1-phases/`
