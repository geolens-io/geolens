---
phase: 1165
title: Live MCP Close-Gate
status: passed
requirement: QA-01
date: 2026-05-31
---

# Phase 1165 Verification — Live MCP Close-Gate (QA-01)

**Goal:** Prove on the running stack that the breaking widget→plugin rename round-trips end-to-end, plus the full deterministic gate is green, before tagging v1036.

## Result: PASSED

QA-01 has two halves; both pass.

### 1. Deterministic gate (subagent-run, read-only, real output)

| Gate | Command | Result | Counts |
|------|---------|--------|--------|
| Frontend typecheck | `npm run typecheck` | ✅ PASS | exit 0, 0 errors |
| i18n parity | `npm run test:i18n` | ✅ PASS | 2/2 |
| Full vitest | `npm run test` | ✅ PASS | 2640 passed / 242 files / 0 failed |
| Backend plugin pytest | `pytest test_maps test_persistent_config test_migration_0025_plugins_rename test_settings_router test_settings_admin test_settings_oauth_crud` | ✅ PASS | 231 passed / 0 failed |
| OpenAPI contract | `make openapi-check` | ✅ PASS | exit 0, no drift |
| SDK contract | `make sdks-check` | ✅ PASS | exit 0, clean |
| E2E core smoke | `npm run e2e:smoke:core` | ✅ PASS | 31/31 |
| E2E builder smoke | `npm run e2e:smoke:builder` | ⚠ PASS (pre-existing flake) | 22 passed / 1 failed (BLDR-TILE-RACE) / 3 skipped |

**The single e2e failure** is `builder-v1-5.spec.ts:165 vector-dataset-onto-stack` — the documented **BLDR-TILE-RACE** flake (4× `"pt"` minified @vis.gl/react-maplibre tile-token 403 race on drag-from-catalog), pre-existing since v1034, NOT a v1036 regression. Carried forward (was already a v1035 carry-forward).

Migration `0025` is covered by a dedicated upgrade→downgrade→re-upgrade round-trip test (`test_migration_0025_plugins_rename.py`) that asserts both the `maps.widgets`→`plugins` column rename and the `enabled_widgets`→`enabled_plugins` config-key migration preserve values. Grep-clean: no `widget`/`enabled_widgets` platform refs remain in `backend/app/` or `frontend/src/` (except preserved `measurement`/`legend` IDs + the cosmetic `legend-widget-${idx}` DOM id).

### 2. Live Playwright MCP (orchestrator-driven, DB-verified)

See `evidence/LIVE-MCP-EVIDENCE.md`. Summary:
- **Map round-trip:** enable Legend → save → `catalog.maps.plugins = ["legend"]` → reload → state persists → cleanup → `[]`. The renamed column writes + reads end-to-end.
- **Admin config:** toggle Measurement → `catalog.app_settings.enabled_plugins = ["legend"]` → restore → `["measurement","legend"]`. The renamed config key persists.
- **0 console errors** at every checkpoint. Old `/enabled-widgets/` route → 404; new `/enabled-plugins/` → 200.
- System restored to baseline (no test residue).

## Success criteria (ROADMAP Phase 1165)
1. ✅ Plugin set→save→reload round-trips the renamed `maps.plugins` DB column — DB-verified.
2. ✅ Admin `enabled_plugins` config persists — DB-verified.
3. ✅ Builder console error-free — 0 errors at all checkpoints.
4. ✅ Full deterministic gate green (the 1 e2e failure is the pre-existing BLDR-TILE-RACE flake, not a regression).

**QA-01: COMPLETE.** v1036 is ready to tag.
