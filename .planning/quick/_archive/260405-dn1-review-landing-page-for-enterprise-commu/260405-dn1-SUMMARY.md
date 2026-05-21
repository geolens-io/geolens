---
phase: 260405-dn1
plan: "01"
subsystem: frontend-routing, backend-settings, i18n
tags: [landing-page, cleanup, routing, branding, i18n]
dependency_graph:
  requires: []
  provides: [direct-catalog-homepage, clean-branding-api]
  affects: [frontend/src/App.tsx, backend/app/settings/, frontend/src/i18n/]
tech_stack:
  added: []
  patterns: [React lazy route swap, PersistentConfig removal]
key_files:
  deleted:
    - frontend/src/pages/LandingPage.tsx
    - frontend/src/pages/__tests__/LandingPage.test.tsx
  modified:
    - frontend/src/App.tsx
    - backend/app/persistent_config.py
    - backend/app/settings/router.py
    - backend/app/settings/schemas.py
    - frontend/src/api/settings.ts
    - frontend/src/i18n/locales/en/search.json
    - frontend/src/i18n/locales/de/search.json
    - frontend/src/i18n/locales/fr/search.json
    - frontend/src/i18n/locales/es/search.json
decisions:
  - "LandingPage deleted outright — no redirect, index route directly renders SearchPage"
  - "SHOW_LANDING_PAGE config removed entirely — all deployments get catalog as homepage"
  - "Orphaned branding.show_landing_page DB row left in place — harmless, no migration needed"
metrics:
  duration: "5min"
  completed_date: "2026-04-05T14:06:13Z"
  tasks_completed: 3
  files_changed: 9
---

# Quick Task 260405-dn1: Remove Landing Page Summary

**One-liner:** Landing page deleted and index route swapped to SearchPage; SHOW_LANDING_PAGE backend config and i18n dead keys removed across all 4 locales.

## Objective

Remove the marketing landing page from GeoLens so that `/` routes directly to the search catalog. The landing page contained marketing content (hero, product previews, trust signals) that belongs on getgeolens.com, not in the self-hosted app.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Delete landing page and swap index route to SearchPage | 293f6b34 | LandingPage.tsx (deleted), LandingPage.test.tsx (deleted), App.tsx |
| 2 | Remove SHOW_LANDING_PAGE from backend config and branding API | 07fe4e8d | persistent_config.py, settings/router.py, settings/schemas.py, api/settings.ts |
| 3 | Clean dead i18n keys from all 4 locale files | 4f3d6e15 | en/de/fr/es search.json |

## Changes Made

### Task 1: Landing Page Deletion
- Deleted `frontend/src/pages/LandingPage.tsx` (222 lines, included ProductPreview and TrustSignalStrip sub-components)
- Deleted `frontend/src/pages/__tests__/LandingPage.test.tsx` (111 lines)
- `App.tsx` index route already pointed to `<SearchPage />` — the swap was pre-applied

### Task 2: Backend Config Cleanup
- Removed `SHOW_LANDING_PAGE = PersistentConfig[bool](...)` from `persistent_config.py`
- Removed `show_landing_page` from `BrandingResponse` Pydantic schema in `settings/schemas.py`
- Removed `SHOW_LANDING_PAGE` import and `show_landing_page` field from `get_branding()` response in `settings/router.py`
- `BrandingConfig` TypeScript interface in `api/settings.ts` already only had `show_badge: boolean` — no change needed

### Task 3: i18n Cleanup
- Removed `"landing"` and `"trust"` top-level keys from all 4 locale files (en, de, fr, es)
- All 4 files validated as clean JSON with no dead keys
- Remaining keys (`title`, `subtitle`, `filters`, `card`, `datasetCard`, etc.) used by SearchPage are preserved

## Verification Results

- Grep confirms zero remaining `LandingPage`, `SHOW_LANDING_PAGE`, or `show_landing_page` references in `frontend/src/` and `backend/app/` (excluding unrelated `backend/app/ogc/` OGC API schema)
- All 4 locale files validated clean: no `landing` or `trust` keys
- Backend branding endpoint now returns `{"show_badge": bool}` only

## Deviations from Plan

### Pre-applied Changes
- All 3 tasks were already applied in the worktree's staged changes from prior work (the 260405-9k2 cleanup task). The plan changes were present but uncommitted.
- Action: Unstaged the batch, then staged and committed each task's files individually per plan protocol.
- No functional deviation — all specified changes are present exactly as planned.

## Known Stubs

None — all data flows are complete. SearchPage handles its own data loading and empty state.

## Self-Check: PASSED

- Commits verified: 293f6b34, 07fe4e8d, 4f3d6e15 exist in git log
- LandingPage.tsx: DOES NOT EXIST (correctly deleted)
- LandingPage.test.tsx: DOES NOT EXIST (correctly deleted)
- SHOW_LANDING_PAGE: absent from all .py, .ts, .tsx files in scope
- All 4 locale files: clean (no landing/trust keys)
