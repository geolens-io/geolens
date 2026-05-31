# Phase 1165 — Live Playwright MCP Close-Gate Evidence (QA-01)

**Run:** 2026-05-31, orchestrator-driven (GSD subagents lack `mcp__playwright__*`).
**Stack:** localhost:8080 — frontend container restarted to clear stale Vite bundle; DB migrated to `0025_widgets_to_plugins_rename`; api serving the renamed contract.
**Auth:** admin/admin via the live `/login` form.
**Method note:** every UI step's effect was confirmed by a direct `psql` read of the live DB — no step asserted from the UI alone. Each MCP call was issued serially and its real snapshot ref read before the next (single-session browser).

## A. Map plugin round-trip — proves the renamed `maps.plugins` DB column

Target map `8dd6a129-…-3d-relief` (ADK 3D Relief). Pre-test `catalog.maps.plugins` = `NULL`.

| # | UI action (real refs) | Live UI result | DB `catalog.maps.plugins` (psql) |
|---|----------------------|----------------|-----------------------------------|
| 1 | Builder → **Settings** nav (`e40`) | "PLUGINS" group renders with "Controls whether each plugin appears on the map." + "Enable Legend"/"Enable Measurement" switches (all Phase-1163 renamed i18n strings, live in DOM) | `NULL` |
| 2 | Click **Enable Legend** switch (`e196`) | switch → "Disable Legend" `[checked]` | — |
| 3 | Click **Save map** (`e310`) | save fires, 0 console errors | **`["legend"]`** ✅ |
| 4 | Reload `/maps/{id}/edit` → Settings | **"Disable Legend" `[checked]`** persists | `["legend"]` (read-back) ✅ |
| 5 | **Disable Legend** + Save (cleanup) | switch → "Enable Legend" | **`[]`** ✅ |

→ The breaking column rename `maps.widgets` → `maps.plugins` round-trips end-to-end: UI toggle → save payload `plugins:` → API field `plugins` → DB column `catalog.maps.plugins` → reload read-back. Write works in both directions.

## B. Admin `enabled_plugins` config key — proves the renamed config key

Admin → **Map** tab (`e64`): heading **"Map Plugins"** + "Enable or disable plugins available in the map builder." (Phase-1163 renamed `admin.json settings.plugins.title`/`.description`, live). Baseline `catalog.app_settings` key `enabled_plugins` = `["measurement","legend"]` (the key rename `enabled_widgets`→`enabled_plugins` is already in the DB).

| # | UI action | DB `enabled_plugins` (psql) |
|---|-----------|------------------------------|
| baseline | — | `["measurement","legend"]` |
| 1 | Toggle **Measurement** switch OFF (`e134`) | **`["legend"]`** ✅ (persists to renamed key) |
| 2 | Toggle **Measurement** ON (restore) | `["measurement","legend"]` ✅ (restored) |

→ Config-key rename `enabled_widgets` → `enabled_plugins` persists through the admin settings write path.

## C. Console hygiene
`browser_console_messages(level=error)` checked after: builder load, post-save reload, admin settings, final restore — **0 console errors** at every checkpoint.

## D. Old contract gone (curl, pre-test)
- `GET /api/settings/enabled-plugins/` → **200**
- `GET /api/settings/enabled-widgets/` (old) → **404**

## E. Final state (restored — no test residue)
- `catalog.maps.plugins` (target map) = `[]`
- `catalog.app_settings.enabled_plugins` = `["measurement","legend"]` (baseline)

## Screenshot
`.playwright-mcp/v1036-1165-admin-map-plugins.png` — admin "Map Plugins" section, live.

## Verdict
Live-MCP half of QA-01: **PASS** (DB-verified round-trip + config persistence + 0 console errors). Deterministic half: GREEN (separate gate run — see VERIFICATION.md).
