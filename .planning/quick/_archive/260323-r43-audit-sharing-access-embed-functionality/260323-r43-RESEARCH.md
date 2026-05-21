# Quick Task 260323-r43: Audit Sharing/Access/Embed - Research

**Researched:** 2026-03-23
**Domain:** Map sharing, embed tokens, visibility enforcement
**Confidence:** HIGH

## Summary

Thorough code review of the sharing/embed/access system. The codebase has a well-structured three-tier visibility model (private/internal/public) for maps, share tokens for link-based access, and embed tokens for iframe tile access. The critical gap is that visibility changes go through `PUT /maps/{id}` with no server-side validation -- `validate_public_visibility()` exists but is only called from the informational `GET /maps/{id}/visibility-check` endpoint, never enforced as a gate.

**Primary recommendation:** Add server-side enforcement in `update_map_endpoint` (router.py) to reject `visibility=public` when `validate_public_visibility()` returns non-empty, and add corresponding frontend UI error display.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Audit + document roadmap: validate audit against actual code, document all gaps as a structured findings report with prioritized recommendations
- No major UI refactoring or admin UI changes in this task
- Document only: don't change admin UI, just document what's needed for future phases
- Rename suggestions (Shared Maps -> Published Maps, Embed Tokens label) go into recommendations
- **Hard block**: prevent setting map visibility to 'public' if it contains non-public datasets
- Show clear error requiring removal of restricted layers before publishing
- This is the ONE code change to implement in this task

### Claude's Discretion
- Report format and organization
- Priority categorization of recommendations
- Document drawer recommendation for future phase but don't implement now

### Deferred Ideas (OUT OF SCOPE)
- Major UI refactoring
- Admin UI changes
- Share drawer implementation
</user_constraints>

## Current Implementation Analysis

### Visibility Model

**Map visibility** (`MapVisibility` enum in `maps/schemas.py`):
- `private` -- only owner + admins
- `internal` -- all authenticated users
- `public` -- anyone with share link

**Dataset visibility** (`DatasetVisibility` enum in `auth/visibility.py`):
- `public` -- visible to all
- `restricted` -- requires role-based grants
- `private` -- owner only

These are independent systems. A map can be public while containing non-public datasets -- this is the gap the hard-block must fix.

### How Visibility Changes Work (Current Flow)

1. **Frontend**: `ShareDialog` in `SharePanel.tsx` calls `handleVisibilityChange()` which calls `publishMap.mutateAsync({ id, visibility })`
2. **API call**: `publishMap()` in `api/maps.ts` does `PUT /maps/{id}` with `{ visibility: 'public' }`
3. **Backend**: `update_map_endpoint()` in `maps/router.py` calls `update_map()` service -- **NO validation of layer dataset visibility**
4. **Visibility check**: `GET /maps/{id}/visibility-check` exists as separate informational endpoint; frontend calls it via `checkMapVisibility()` in `runVisibilityCheck()` but only AFTER the visibility has already been set

**Current behavior**: User clicks "Anyone with the link" -> visibility immediately changes to public -> THEN a visibility check runs -> if non-public datasets exist, an info banner appears about embed tokens. There is NO blocking.

### Where the Hard Block Must Go

**Backend** (`backend/app/maps/router.py`, `update_map_endpoint` around line 290-348):
- Before calling `update_map()`, check if `body.visibility == 'public'`
- If so, call `validate_public_visibility(db, map_id)`
- If non-public datasets exist, return HTTP 400 with dataset names
- The `validate_public_visibility()` function already exists and works correctly (line 629-642 of `service.py`)

**Frontend** (`frontend/src/components/builder/SharePanel.tsx`, `handleVisibilityChange` around line 100-118):
- Catch the 400 error from the API
- Display the non-public dataset names in an error toast or inline error
- The i18n key `share.cannotPublish` already exists: `"Cannot publish: datasets {{datasets}} are not public"`

### Share Token System

- `MapShareToken` model with `token`, `is_active`, `expires_at`
- Created via `POST /maps/{map_id}/share` -- **already requires `map_obj.visibility == 'public'`** (line 479 of router.py)
- One active token per map, soft-revoke via `is_active=False`
- Share URL format: `/m/{token}`
- `GET /maps/shared/{token}` resolves the shared map -- also checks `map_obj.visibility != 'public'` returns None (line 745)

### Embed Token System

- Separate `EmbedToken` model with hashed tokens, origin restrictions, dataset scope snapshot
- Created per-map, scoped to current layer dataset_ids at creation time
- Origin-locked (optional `allowed_origins`), cached validation with 5-min TTL
- Token format: `et_` prefix + 32-byte urlsafe
- Used for tile access on non-public datasets in embedded/shared maps
- Admin can bulk-revoke via dedicated admin router

### User-Facing Text Audit

| Location | Current Text | Audit Concern |
|----------|-------------|---------------|
| Share dialog title | "Share" | Fine |
| Public option | "Anyone with the link" | Correct |
| Public description | "Visible to anyone -- enables share links and embedding" | Correct -- audit's claim matches |
| Admin sidebar | "Shared Maps" | Audit suggests "Published Maps" |
| Admin page title | "Shared Maps" | Same |
| Admin table header | "Embed Tokens" | Technical -- audit flags this |
| Embed info banner | "Non-public layers are included. An embed token handles access automatically." | Technical -- could be clearer |
| Admin nav key | `adminNav.sharedMaps` in `common.json` | Text: "Shared Maps" |

**"Embed Tokens" in user-facing UI**: Appears in the admin Shared Maps page table header and expandable section title. These are admin-only surfaces, so less critical than if they appeared in the builder. The term does NOT appear in the builder SharePanel -- that UI shows "Embed Code" and handles tokens transparently.

### Admin Structure

Admin sidebar groups:
1. **Overview**: Dashboard
2. **Operations**: Users, Jobs, Audit Log, Shared Maps
3. **Settings**: General, Auth, AI, Network, Storage, Appearance, Permissions + Config Ops

The "Shared Maps" page (`AdminSharedMapsPage.tsx`) shows share tokens with expandable embed token sub-tables. No separate dedicated embed tokens page exists -- they're nested under share tokens.

## Hard Block Implementation Details

### Backend Change (maps/router.py)

In `update_map_endpoint`, before line 312 (`await update_map(db, map_id, **kwargs)`):

```python
# Hard block: prevent publishing maps with non-public datasets
if body.visibility == MapVisibility.public:
    non_public = await validate_public_visibility(db, map_id)
    if non_public:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot set visibility to public: datasets are not public: {', '.join(non_public)}",
        )
```

Need to import `MapVisibility` from schemas (already imported in schemas import block, just need to use it).

### Frontend Change (SharePanel.tsx)

In `handleVisibilityChange`, the catch block (line 115-117) already catches errors and shows `toast.error(t('toasts.visibilityFailed'))`. Two options:

1. **Minimal**: Parse the error detail from the API response and show it in the toast. The API returns the dataset names in the detail string.
2. **Better**: Extract dataset names from the 400 response and use the existing `share.cannotPublish` i18n key: `"Cannot publish: datasets {{datasets}} are not public"`.

The `publishMap` mutation calls `apiFetch` which throws `ApiError` with `status` and `message`. The catch block should check for 400 status and show the specific message.

### Files to Modify

| File | Change |
|------|--------|
| `backend/app/maps/router.py` | Add validation before `update_map()` call in `update_map_endpoint` |
| `frontend/src/components/builder/SharePanel.tsx` | Improve error handling in `handleVisibilityChange` catch block to show specific error from API |

### Edge Cases

- **Map has no layers**: `validate_public_visibility()` returns empty list (query finds no non-public records because there are no records) -- OK to publish
- **All layers are public datasets**: returns empty list -- OK to publish
- **Mixed public/non-public**: returns non-public names -- blocked
- **User removes non-public layer then retries**: should succeed on second attempt
- **Race condition**: Dataset visibility changes between check and update -- acceptable risk for this enforcement level; the shared map viewer (`get_shared_map`) already applies visibility filtering at render time

## Common Pitfalls

### Pitfall 1: API Error Detail Parsing
**What goes wrong:** Frontend `apiFetch` may wrap the error differently than expected
**How to avoid:** Check `ApiError` class in `api/client.ts` to confirm how `detail` is exposed. The existing code in `api/maps.ts` line 108-111 shows it throws `ApiError(detail, response.status)`.

### Pitfall 2: Forgetting MapVisibility Import
**What goes wrong:** Using string comparison instead of enum
**How to avoid:** `MapVisibility` is already imported in `router.py` schemas block (line 22). Use `MapVisibility.public` or compare `body.visibility == "public"` (it's a str enum so both work).

## Sources

### Primary (HIGH confidence)
- Direct code review of all listed files in the codebase
- `backend/app/maps/service.py` -- validate_public_visibility (lines 629-642)
- `backend/app/maps/router.py` -- update_map_endpoint (lines 290-348), share_map_endpoint (lines 463-502)
- `frontend/src/components/builder/SharePanel.tsx` -- full file
- `frontend/src/i18n/locales/en/builder.json` -- share.* keys
- `frontend/src/i18n/locales/en/admin.json` -- sharedMaps.*, embedTokens.* keys
- `frontend/src/i18n/locales/en/common.json` -- adminNav.sharedMaps key
