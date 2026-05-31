# Phase 1165 — Live Close-Gate Evidence (QA-01)

**Run:** 2026-05-31, orchestrator-driven. Stack: localhost:8080 (frontend restarted to clear stale Vite bundle; DB migrated to `0025`; admin/admin).

> **Honesty note on method.** The plan called for proving the round-trip by clicking the builder Settings→PLUGINS toggle via Playwright MCP. In practice the MCP browser's click-locator translation repeatedly resolved to the wrong elements (it opened the Hiking-trails *layer editor* instead of the Settings→PLUGINS panel), and the tool-output channel was intermittently stalling. Rather than fabricate a UI-click result, I proved the **same backend write path** the builder Save uses — `PUT /api/maps/{id}` with `plugins:` in the body (`frontend/src/components/builder/hooks/use-builder-save.ts:494`) — directly via authenticated curl, and confirmed every effect against the live DB. The live builder UI *was* observed (MCP snapshots) rendering the renamed plugin vocabulary. This is the authoritative proof for the breaking DB/API column rename; it is not a UI-driven result and is not described as one.

## A. Renamed API contract (live GET)
`GET /api/maps/8dd6a129-…` (admin JWT) →
- response **has `plugins` key**, **no `widgets` key** ✅
- `GET /api/settings/enabled-plugins/` → **200** `{"enabled_plugins":["measurement","legend"]}` ✅
- `GET /api/settings/enabled-widgets/` (old) → **404** ✅

## B. Map plugin round-trip — proves the renamed `maps.plugins` column
Target map `8dd6a129-…` (ADK 3D Relief). Pre-test `catalog.maps.plugins` = `NULL`.

| # | Action (authenticated API = same path as builder Save) | HTTP | DB `catalog.maps.plugins` (psql) |
|---|--------------------------------------------------------|------|-----------------------------------|
| 1 | `GET /api/maps/{id}` | 200 | `NULL` (response `plugins: null`) |
| 2 | `PUT /api/maps/{id}` body `plugins:["legend"]` | **200** (returned `plugins:["legend"]`) | **`["legend"]`** ✅ |
| 3 | reload `GET /api/maps/{id}` | 200 | response `plugins:["legend"]` (persisted read-back) ✅ |
| 4 | `PUT` `plugins:[]` then DB restore to `NULL` (cleanup) | 200 | `NULL` (pre-test state restored) ✅ |

→ The breaking column rename `maps.widgets` → `maps.plugins` round-trips end-to-end through the live API: write → DB column → read-back. (The builder Save button issues exactly this PUT with the `plugins:` body key.)

## C. Admin `enabled_plugins` config key (renamed config key)
Baseline `catalog.app_settings.enabled_plugins` = `["measurement","legend"]`.

| # | Action | HTTP | DB `app_settings.enabled_plugins` |
|---|--------|------|------------------------------------|
| 1 | `PUT /api/settings/enabled-plugins/` `["legend"]` | **200** | **`["legend"]`** ✅ |
| 2 | `PUT` restore `["measurement","legend"]` | 200 | `["measurement","legend"]` (restored) ✅ |

→ Config-key rename `enabled_widgets` → `enabled_plugins` persists through the settings write path. Old `enabled_widgets` key = **0 rows** in DB.

## D. Live builder UI renders renamed plugin vocabulary (MCP snapshots)
On `/maps/8dd6a129-…` the builder DOM (captured via MCP `browser_snapshot`) shows the Phase-1162/1163 renames live:
- Legend plugin panel with **"Close plugin"** button (`aria-label` = `plugins.closePlugin` i18n key) — ref `e316` in snapshot.
- Builder tool rail: Pan / Measure / **Legend** / Style JSON.
- `browser_console_messages(level=error)` on the builder page → **0 errors**.

## E. Final state (restored — no residue)
- `catalog.maps.plugins` (target map) = `NULL` (pre-test value)
- `catalog.app_settings.enabled_plugins` = `["measurement","legend"]` (default)
- `enabled_widgets` key = 0 rows; `/settings/enabled-widgets/` → 404

## Verdict
QA-01 live half: **PASS** — renamed `maps.plugins` column + `enabled_plugins` config key both round-trip on the running stack (DB-verified), live builder renders renamed plugin vocabulary, 0 console errors. Method was API-level (curl on the builder's own PUT path) + UI observation, not UI-click-driven — stated plainly above.
