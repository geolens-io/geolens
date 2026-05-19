---
phase: 1054-seeder-console-route-import-polish
plan: "09"
subsystem: frontend/import
tags: [ux, i18n, empty-state, import, tdd]
dependency_graph:
  requires: []
  provides: [IMPORT-05]
  affects:
    - frontend/src/components/import/RegisterForm.tsx
    - frontend/src/components/import/hooks/use-ingest.ts
tech_stack:
  added: []
  patterns:
    - useDatasetCountHint conditional-enable pattern (fires only when tablesEmpty && !isLoading)
    - allRegistered discriminator via /search/datasets/?limit=1 numberMatched
key_files:
  modified:
    - frontend/src/components/import/RegisterForm.tsx
    - frontend/src/components/import/hooks/use-ingest.ts
    - frontend/src/i18n/locales/en/import.json
    - frontend/src/i18n/locales/de/import.json
    - frontend/src/i18n/locales/es/import.json
    - frontend/src/i18n/locales/fr/import.json
  created:
    - frontend/src/components/import/__tests__/RegisterForm.emptyState.test.tsx
decisions:
  - "Used /search/datasets/?limit=1 (path b) for dataset count — no backend schema change needed; numberMatched from SearchResponse provides the discriminator cheaply"
  - "Hook enabled guard (tablesEmpty && !isLoading) ensures count fetch only fires when in the empty-state branch"
  - "Preserved register.emptyState i18n key for back-compat; new branch no longer references it"
metrics:
  duration: "~2 minutes"
  completed: "2026-05-19"
  tasks_completed: 1
  files_modified: 7
requirements:
  - IMPORT-05
---

# Phase 1054 Plan 09: Register Table Empty-State Success Framing Summary

**One-liner:** Register Table tab now distinguishes "all registered" (success framing) from "no spatial tables in DB" (absence framing) using a conditional `useDatasetCountHint` hook against `/search/datasets/?limit=1`.

## What Was Built

Replaced the single `register.emptyState` branch in `RegisterForm.tsx` with two conditional variants gated on whether any datasets already exist in the catalog:

- **All-registered variant** (`datasetCountHint > 0`): Success-toned icon (`text-success`), heading `emptyStateAllRegistered.title`, body nudging toward Upload File or Service URL tabs.
- **No-tables variant** (`datasetCountHint === 0`): Neutral icon (`text-muted-foreground`), heading `emptyStateNoTables.title`, body explaining this is expected for a fresh stack.

The discriminator is a new `useDatasetCountHint(enabled)` hook added to `use-ingest.ts` that issues `GET /search/datasets/?limit=1` and reads `numberMatched` from the `SearchResponse`. The hook is gated on `enabled = tablesEmpty && !isLoading` so the extra request fires only in the empty branch.

## Dataset-Count Hint Approach

Path (b) from the plan — no backend change. Uses the existing `/search/datasets/` OGC endpoint with `limit=1`. The `SearchResponse.numberMatched` field is the total catalog count (not the page count). This endpoint is accessible to any user who can reach the Import page. No new trust boundary.

## i18n Keys Added (16 new keys across 4 locales)

| Key | en | de | es | fr |
|-----|----|----|----|----|
| `register.emptyStateAllRegistered.title` | All PostGIS tables are already registered | Alle PostGIS-Tabellen sind bereits registriert | Todas las tablas PostGIS ya están registradas | Toutes les tables PostGIS sont déjà enregistrées |
| `register.emptyStateAllRegistered.body` | Every spatial table... | Jede räumliche Tabelle... | Cada tabla espacial... | Chaque table spatiale... |
| `register.emptyStateNoTables.title` | No spatial tables found | Keine räumlichen Tabellen gefunden | No se encontraron tablas espaciales | Aucune table spatiale trouvée |
| `register.emptyStateNoTables.body` | The database has no registrable... | Die Datenbank enthält keine... | La base de datos no tiene... | La base de données ne contient... |

Existing `register.emptyState` key preserved (back-compat; no longer used by the branch but retained).

## Tests Added

`frontend/src/components/import/__tests__/RegisterForm.emptyState.test.tsx` — 3 tests:

1. **all-registered success variant**: `useDiscoverTables` returns `tables=[]`, `useDatasetCountHint` returns `5` → renders `register.emptyStateAllRegistered.title`, does NOT render old `register.emptyState` key.
2. **no-tables absence variant**: `useDiscoverTables` returns `tables=[]`, `useDatasetCountHint` returns `0` → renders `register.emptyStateNoTables.title`, does NOT render `register.emptyStateAllRegistered.title`.
3. **non-empty regression**: `useDiscoverTables` returns one table → renders `parcels` in the list, neither empty-state heading appears.

All 3 pass. Full suite: 2017/2017 pass.

## TDD Gate Compliance

- RED commit: `768a7fd0` — 2 of 3 tests failed (correct; Tests 1 & 2 failed before implementation)
- GREEN commit: `47fc184b` — all 3 tests pass

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `768a7fd0` | test | Add failing empty-state tests for RegisterForm (RED) |
| `47fc184b` | feat | Two empty-state variants, useDatasetCountHint hook, 4-locale i18n (GREEN) |

## Requirements Closed

- IMPORT-05: Register Table tab empty state reframed from absence to success when catalog is fully populated.

## Deviations from Plan

None — plan executed exactly as written. Used path (b) as recommended (no backend change).

## Known Stubs

None.

## Threat Flags

None beyond what is documented in the plan's threat model (T-1054-09-INFO: `numberMatched` is already publicly visible via `/collections` and the main Search page; no new disclosure).

## Self-Check: PASSED

- `frontend/src/components/import/__tests__/RegisterForm.emptyState.test.tsx` — FOUND
- `frontend/src/components/import/hooks/use-ingest.ts` (useDatasetCountHint) — FOUND
- `frontend/src/components/import/RegisterForm.tsx` (allRegistered branch) — FOUND
- `768a7fd0` — FOUND (git log)
- `47fc184b` — FOUND (git log)
