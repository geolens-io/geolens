# Quick Task 260405-dn1: Remove Landing Page - Research

**Researched:** 2026-04-05
**Domain:** Frontend routing, backend persistent config, i18n cleanup
**Confidence:** HIGH

## Summary

The landing page is a self-contained feature with a clean dependency graph. It touches 8 files for removal, plus 4 i18n locale files for key cleanup. The route change is a one-line swap in `App.tsx`. The backend `SHOW_LANDING_PAGE` persistent config and its schema/router references are straightforward to excise. No other components depend on the landing page internals.

**Primary recommendation:** Delete files, swap the index route to `<SearchPage />`, remove `show_landing_page` from the branding API contract, and clean i18n keys.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Straight to search**: Non-authenticated users hitting `/` see the catalog search page directly. No hero, no marketing copy. Login available in navbar.
- Remove the `LandingPage.tsx` component and its route entirely.
- The index route `/` should render the search page (same as `/search`).
- **Remove the `show_landing_page` branding toggle entirely**: `/` always shows search for all deployment types.
- No distinction between enterprise/community/cloud -- all deployments get the same experience.
- Delete the `SHOW_LANDING_PAGE` persistent config setting and related backend/frontend code.
- **Move product preview assets to getgeolens.com only**: Delete product preview mockup components from the app codebase.
- Phase 214 assets should be migrated to the marketing site repo (out of scope for this task -- just delete from app).

### Specific Ideas
- The search page already handles empty state gracefully -- no special "welcome" needed.
- i18n keys in `search.json` under `landing.*` namespace should be cleaned up.
- Branding settings admin UI should remove the `show_landing_page` toggle.

</user_constraints>

## Complete Dependency Graph

### Files to DELETE

| File | Purpose | Safe to Delete |
|------|---------|----------------|
| `frontend/src/pages/LandingPage.tsx` | Landing page component (222 lines, includes `ProductPreview` and `TrustSignalStrip` sub-components) | YES -- no other imports |
| `frontend/src/pages/__tests__/LandingPage.test.tsx` | Landing page tests (111 lines) | YES -- test-only |

### Files to MODIFY

| File | Line(s) | Change |
|------|---------|--------|
| `frontend/src/App.tsx` | L16, L54 | Remove `LandingPage` lazy import (L16); change `<Route index element={<LandingPage />} />` to `<Route index element={<SearchPage />} />` (L54) |
| `frontend/src/api/settings.ts` | L113 | Remove `show_landing_page: boolean` from `BrandingConfig` interface |
| `frontend/src/hooks/use-settings.ts` | -- | No change needed (hook is generic, passes through BrandingConfig) |
| `backend/app/persistent_config.py` | L530-535 | Delete `SHOW_LANDING_PAGE` constant |
| `backend/app/settings/router.py` | L26, L382-383 | Remove `SHOW_LANDING_PAGE` import (L26); remove `show_landing_page` from `get_branding` response (L382-383) |
| `backend/app/settings/schemas.py` | L130 | Remove `show_landing_page: bool` from `BrandingResponse` |
| `backend/tests/test_branding_settings.py` | L15 | Test already asserts `{"show_badge": True}` without `show_landing_page` -- no change needed (the test would actually start passing correctly after removal) |

### i18n Keys to DELETE (4 locale files)

Each file: `frontend/src/i18n/locales/{en,de,fr,es}/search.json`

Remove these top-level keys from each locale:
- `"landing"` -- entire object (keys: eyebrow, searchHelper, primaryCta, searchCta, openSourceTitle, openSourceBody, workspaceTitle, workspaceBody, features.*)
- `"trust"` -- entire object (keys: license, ogc, github) -- only used in LandingPage's TrustSignalStrip

Keys to KEEP (used by SearchPage and other components):
- `"title"`, `"subtitle"`, `"workspaceTitle"` (top-level, outside landing namespace)
- Everything under `"filters"`, `"empty"`, `"card"`, `"datasetCard"`, etc.

## Route Change Strategy

**Simplest approach: swap the element on the index route.**

Current (App.tsx L54):
```tsx
<Route index element={<LandingPage />} />
```

After:
```tsx
<Route index element={<SearchPage />} />
```

This means `/` and `/search` render the same component. No redirect needed. The `SearchPage` lazy import already exists at L17. Users who had `/?q=roads` bookmarked will still work because SearchPage reads query params from location.

**Alternative considered (redirect):** `<Route index element={<Navigate to="/search" replace />} />` -- unnecessary indirection, adds a history entry replacement, and changes the visible URL. The component swap is cleaner.

## Admin Settings UI

`frontend/src/components/admin/settings/SettingsAppearanceTab.tsx` does NOT have a `show_landing_page` toggle. It only has `show_badge`. The `useBranding` hook and `updateBranding` mutation pass the full `BrandingConfig` object, but the admin UI never sets `show_landing_page`. **No admin UI change is needed** -- just remove the field from the TypeScript interface and backend schema.

## Shared Dependencies (DO NOT DELETE)

These are imported by LandingPage but used elsewhere:

| Import | Also Used By |
|--------|-------------|
| `GEOLENS_LICENSE_URL` from `@/lib/external-links` | `AppLayout.tsx` footer |
| `PageShell` from `@/components/layout/PageShell` | Many pages |
| `useBranding` from `@/hooks/use-settings` | `AppLayout.tsx`, `PublicViewerPage.tsx`, `SettingsAppearanceTab.tsx` |
| `useAuthStore` from `@/stores/auth-store` | Everywhere |
| `OGC_API_URL` from `@/lib/external-links` | **Only LandingPage** -- can be deleted from external-links if desired, but harmless to keep |

## Backend Branding Endpoint After Cleanup

After removing `show_landing_page`, the GET `/settings/branding/` endpoint returns:
```json
{"show_badge": true}
```

The `BrandingResponse` schema becomes:
```python
class BrandingResponse(BaseModel):
    show_badge: bool
```

The `updateBranding` frontend function sends `Partial<BrandingConfig>` which will only contain `show_badge` -- no breaking change.

## Common Pitfalls

### Pitfall 1: Stale Vite chunk cache
**What goes wrong:** After deleting LandingPage.tsx, users with cached JS chunks referencing the old lazy import get a runtime error.
**How to avoid:** The `LazyLoadErrorBoundary` in App.tsx already wraps all lazy routes. A page refresh will load the new chunks. No action needed.

### Pitfall 2: Forgetting i18n keys in non-English locales
**What goes wrong:** Dead keys in de/fr/es search.json accumulate as bundle bloat.
**How to avoid:** Remove `landing` and `trust` objects from all 4 locale files.

### Pitfall 3: Persistent config row in database
**What goes wrong:** Existing deployments have a `branding.show_landing_page` row in the `persistent_config` table. Removing the Python constant doesn't delete the DB row.
**How to avoid:** The orphaned row is harmless -- it just sits unused. No migration needed. If cleanliness is desired, an Alembic migration could delete it, but that's optional.

## Execution Checklist

1. Delete `frontend/src/pages/LandingPage.tsx`
2. Delete `frontend/src/pages/__tests__/LandingPage.test.tsx`
3. Edit `frontend/src/App.tsx`: remove LandingPage import, change index route to SearchPage
4. Edit `frontend/src/api/settings.ts`: remove `show_landing_page` from BrandingConfig
5. Edit `backend/app/settings/schemas.py`: remove `show_landing_page` from BrandingResponse
6. Edit `backend/app/settings/router.py`: remove SHOW_LANDING_PAGE import and usage in get_branding
7. Edit `backend/app/persistent_config.py`: delete SHOW_LANDING_PAGE constant
8. Edit 4 i18n files: remove `landing` and `trust` objects from en/de/fr/es search.json
9. Run frontend tests: `cd frontend && npx vitest run`
10. Run backend tests: `cd backend && python -m pytest tests/test_branding_settings.py -x`

## Sources

### Primary (HIGH confidence)
- Direct codebase grep and file reads -- all references traced exhaustively
- `frontend/src/App.tsx` -- route structure verified
- `backend/app/settings/router.py` -- branding endpoint verified
- `backend/app/persistent_config.py` -- SHOW_LANDING_PAGE definition verified
- `backend/tests/test_branding_settings.py` -- existing test assertions verified

## Metadata

**Confidence breakdown:**
- Dependency graph: HIGH -- exhaustive grep across codebase
- Route change strategy: HIGH -- straightforward React Router swap
- i18n cleanup: HIGH -- all 4 locales checked, key scoping verified
- Backend cleanup: HIGH -- all touchpoints identified and traced

**Research date:** 2026-04-05
**Valid until:** N/A (one-time removal task)
