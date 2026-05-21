# Sharing, Access & Embed Functionality: Audit Findings Report

**Date:** 2026-03-23
**Scope:** Third-party audit validation of map sharing, embed tokens, and visibility enforcement
**Status:** Audit validated, critical fix implemented, remaining items documented

## Executive Summary

GeoLens implements a well-structured three-tier visibility model (private/internal/public) for maps, with share tokens for link-based access and embed tokens for iframe tile access on non-public datasets. The system correctly defaults maps to private and requires explicit user action to publish. The critical gap identified by the audit -- that maps containing non-public datasets could be set to public without enforcement -- has been closed with a server-side hard block (HTTP 400) in `update_map_endpoint`. The remaining audit recommendations are UI polish and architectural suggestions that do not represent security risks.

## Audit Validation

| # | Audit Recommendation | Verdict | Evidence |
|---|---------------------|---------|----------|
| 1 | Rename "Shared Maps" to "Published Maps" | **Valid (P2)** | Admin sidebar and page use `adminNav.sharedMaps` / `sharedMaps.title` i18n keys. Rename is a text-only change in locale files + component references. |
| 2 | Separate internal sharing vs external publishing | **Partially Correct** | Current model uses `MapVisibility` enum (private/internal/public) which maps to internal/external concepts. The distinction exists but is dataset-centric rather than user-group-centric. Adding org-wide policies would require new infrastructure. |
| 3 | Add org-wide sharing/publishing policy controls | **Valid (P3)** | No dedicated Permissions admin page for sharing policies. Current permissions are role-based (`edit_metadata` required). Would need new settings schema + enforcement layer. |
| 4 | Replace "Embed Tokens" label with product language | **Partially Correct** | "Embed Tokens" appears only in admin-only surfaces (`AdminSharedMapsPage.tsx` table header). The builder `SharePanel.tsx` already uses user-friendly "Embed Code" language. Less critical than audit suggested since end users never see "Embed Tokens". |
| 5 | Add search/filter/sort to Shared Maps page | **Valid (P2)** | `AdminSharedMapsPage.tsx` currently shows a flat list without search, filter, or sort capabilities. At scale this becomes unwieldy. |
| 6 | Add exposure type, last accessed, access count columns | **Valid (P3)** | Share tokens track `created_at` and `expires_at` but not access counts or last-accessed timestamps. Would require new fields on `MapShareToken` model. |
| 7 | Move Share into right-side drawer with tabs | **Valid (P3)** | Current implementation uses a centered `Dialog` modal. A drawer with Access/Link/Embed/Advanced tabs would improve organization but is a significant UI change. |
| 8 | Move Share button next to Save in map header | **Already Addressed** | Share/Export/Duplicate are grouped in a `MoreHorizontal` dropdown in the builder header (Phase 0202 decision). The current placement follows the v12.3 header tray design. |
| 9 | Add visibility badge near map title | **Valid (P2)** | No visibility indicator is shown in the builder header. A small badge (Private/Internal/Public) near the map title would improve awareness. |
| 10 | Hard-block publishing maps with non-public datasets | **IMPLEMENTED** | `validate_public_visibility()` existed as informational-only (GET endpoint). Now enforced as a gate in `update_map_endpoint` -- returns HTTP 400 with dataset names. See "Implemented Fix" section. |
| 11 | Default all new maps/datasets to Private | **Partially Correct** | Maps already default to private. Datasets default to `public` visibility (set in `DatasetVisibility` enum default). The dataset default is intentional for catalog discoverability -- restricted datasets must be explicitly marked. |
| 12 | Default link expiry to 30 days, require expiry | **Partially Correct** | Embed tokens already default to 30 days expiry (1-365 range). Share tokens have optional expiry (`expires_at` nullable). Requiring expiry on share tokens would need a schema change. |
| 13 | Only Admin + Publisher can create public links/embeds | **Partially Correct** | Share token creation requires `edit_metadata` permission. There is no separate "Publisher" role -- the current RBAC model uses admin/editor/viewer roles. Adding a Publisher role is a broader RBAC change. |
| 14 | Block public maps with restricted layers | **IMPLEMENTED** | This is the foundational rule. `validate_public_visibility()` now enforces this at the API layer before any visibility change to public. |

## Implemented Fix

### Hard Block: Non-Public Dataset Enforcement

**File:** `backend/app/maps/router.py` -- `update_map_endpoint`
**Commit:** 757280ce

**Before:** `PUT /maps/{id}` with `visibility=public` was accepted unconditionally. `validate_public_visibility()` existed but was only called from the informational `GET /maps/{id}/visibility-check` endpoint.

**After:** When `body.visibility == MapVisibility.public`, the endpoint calls `validate_public_visibility(db, map_id)` before `update_map()`. If non-public datasets are found, it returns:

```
HTTP 400: "Cannot set visibility to public: datasets are not public: Dataset A, Dataset B"
```

**Frontend:** `SharePanel.tsx` catches the 400 error in `handleVisibilityChange`, extracts dataset names, and displays a localized toast using the existing `share.cannotPublish` i18n key: "Cannot publish: datasets {names} are not public".

**Edge cases handled:**
- Maps with no layers: passes (empty dataset list)
- Maps with all public datasets: passes normally
- Mixed public/non-public: blocked with specific names
- User removes non-public layer and retries: succeeds on retry

## Prioritized Recommendations

### P1 -- Security/Data (Addressed)

| Item | Status | Details |
|------|--------|---------|
| Hard-block public maps with non-public datasets | Done | Commit 757280ce |
| Share token requires public visibility | Already existed | `share_map_endpoint` line 479 checks `map_obj.visibility != 'public'` |
| Embed tokens scoped to dataset IDs at creation | Already existed | Token creation snapshots current layer dataset_ids |

### P2 -- UX Polish (Future Phase)

| Item | Effort | Files | Notes |
|------|--------|-------|-------|
| Rename "Shared Maps" to "Published Maps" in admin | Low | `common.json` (4 locales), `AdminSidebar.tsx`, `AdminSharedMapsPage.tsx` | i18n key `adminNav.sharedMaps` + page title key |
| Rename "Embed Tokens" table header in admin | Low | `admin.json` (4 locales) | Key: `sharedMaps.embedTokens` or similar |
| Add visibility badge in builder header | Low | `MapBuilderPage.tsx` or header component | Small colored badge: Private/Internal/Public |
| Add search/filter to admin Shared Maps page | Medium | `AdminSharedMapsPage.tsx` | Pattern exists in other admin pages (Users, Jobs) |
| Clarify embed info banner text | Low | `builder.json` (4 locales) | Key: `share.embedTokenInfo` -- reword to be less technical |

### P3 -- Architecture (Future Phase)

| Item | Effort | Notes |
|------|--------|-------|
| Share drawer with tabs (Access/Link/Embed/Advanced) | High | Replace Dialog with Sheet/Drawer component. Significant restructure of SharePanel. |
| Internal vs external sharing distinction | High | Would require user-group model, org-level policies, new admin settings section. Current visibility enum covers the core use case. |
| Org-wide publishing policies | High | New settings category under Permissions. Would need: policy schema, enforcement middleware, admin UI. |
| Access analytics (last accessed, count) | Medium | New columns on `MapShareToken`, middleware to track access, admin display. |
| Required share token expiry | Low | Make `expires_at` non-nullable on `MapShareToken`, default 30 days, migration. |

### P4 -- Nice-to-Have

| Item | Effort | Notes |
|------|--------|-------|
| Copy-to-clipboard visual feedback | Low | Brief checkmark animation on copy buttons. Current uses toast only. |
| Share URL preview | Low | Show shortened URL inline before copy. |
| Embed preview pane | Medium | Live iframe preview within share dialog. |

## Current Architecture Summary

### Three-Tier Map Visibility

```
private  --> Only owner + admins can view
internal --> All authenticated users can view
public   --> Anyone with share link can view
```

Maps default to `private`. Visibility changes go through `PUT /maps/{id}` with `visibility` field. As of this fix, setting `public` requires all layer datasets to have `public` visibility.

### Share Token Flow

1. Map must be `public` (enforced at creation)
2. `POST /maps/{id}/share` creates `MapShareToken` with optional `expires_at`
3. One active token per map; creating new soft-revokes previous
4. Share URL: `/m/{token}` resolves via `GET /maps/shared/{token}`
5. Shared map viewer applies visibility filtering at render time

### Embed Token Flow

1. Created per-map, scoped to current layer dataset_ids
2. Token format: `et_` prefix + 32-byte urlsafe
3. Optional origin restrictions (`allowed_origins`)
4. 5-minute validation cache TTL
5. Used for tile access on non-public datasets in embedded/shared maps
6. Expiry range: 1-365 days, default 30

### Key Files

| File | Purpose |
|------|---------|
| `backend/app/maps/router.py` | Map CRUD, sharing, embed endpoints |
| `backend/app/maps/service.py` | Business logic, `validate_public_visibility()` |
| `backend/app/maps/schemas.py` | `MapVisibility` enum, request/response models |
| `backend/app/embed/router.py` | Embed token admin endpoints |
| `backend/app/embed/service.py` | Embed token creation, validation, caching |
| `frontend/src/components/builder/SharePanel.tsx` | Share dialog UI |
| `frontend/src/api/maps.ts` | Map API client (`publishMap`, share token calls) |
| `frontend/src/hooks/use-maps.ts` | React Query hooks for map mutations |
| `frontend/src/hooks/use-embed-tokens.ts` | React Query hooks for embed tokens |

## Out of Scope (Deferred)

The following items were explicitly deferred per user decisions:

- **Admin UI changes**: No renaming of "Shared Maps" or "Embed Tokens" labels in this task
- **Share drawer implementation**: Documented as P3 recommendation; current modal is functional
- **Major UI refactoring**: No structural changes to SharePanel or admin pages
- **Publisher role**: RBAC expansion beyond current admin/editor/viewer model
- **Org-wide sharing policies**: Would require new settings infrastructure
- **Access analytics**: Tracking last-accessed and access counts on share tokens
