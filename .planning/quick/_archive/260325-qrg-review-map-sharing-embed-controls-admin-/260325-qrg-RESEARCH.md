# Quick Task 260325-qrg: Map Sharing/Embed Controls Audit - Research

**Researched:** 2026-03-25
**Domain:** Admin shared maps page + Map creator SharePanel wiring
**Confidence:** HIGH

## Summary

End-to-end audit of the admin `/admin/shared-maps` page (`AdminSharedMapsPage.tsx`) and the map creator's `ShareDialog` (formerly `SharePanel`). Traced every hook, API call, mutation, and backend endpoint. The wiring is fundamentally correct -- both admin and creator paths connect to the right endpoints with matching schemas. There are a few specific issues worth addressing.

**Primary finding:** The wiring is solid. The issues are (1) a missing cache invalidation in `useBulkRevokeEmbedTokens` causing stale embed counts on the admin page, (2) the admin revoke of share tokens not cascading to embed tokens (backend gap), and (3) minor frontend type drift from the backend schema.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Admin page stays revoke-only -- it is an oversight dashboard, not an editing interface
- Editing share/embed settings happens in the map creator's SharePanel
- Admin can only revoke share tokens and bulk-revoke embed tokens
- End-to-end audit: trace every admin page hook/action to backend endpoints
- Verify status badges, pagination, search, and revoke flows are all correct
- Check that the SharePanel's share/embed controls properly wire to backend APIs
- Fix easy wins: layout issues, missing states, accessibility gaps, polish
- Skip major redesigns

### Claude's Discretion
- SharePanel completeness: check that all controls (embed code, domain restrictions, expiration) are properly wired and functional
</user_constraints>

## Wiring Audit: Admin SharedMapsPage

### Hook -> API -> Backend Trace

| Hook | API Function | Backend Endpoint | Status |
|------|-------------|------------------|--------|
| `useShareTokens(skip, limit, search, status)` | `listShareTokens()` -> `GET /admin/share-tokens` | `admin/router.py:624` -> `maps/service.py:list_share_tokens()` | CORRECT |
| `useAdminRevokeShareToken()` | `adminRevokeShareToken(tokenId)` -> `DELETE /admin/share-tokens/{token_id}` | `admin/router.py:646` -> `maps/service.py:revoke_share_token()` | CORRECT |
| `useAdminEmbedTokens({ map_id })` | `listAdminEmbedTokens()` -> `GET /admin/embed-tokens/?map_id=X` | `embed_tokens/admin_router.py:33` -> `embed_tokens/service.py:list_admin_embed_tokens()` | CORRECT |
| `useBulkRevokeEmbedTokens()` | `bulkRevokeEmbedTokens(ids)` -> `POST /admin/embed-tokens/bulk-revoke/` | `embed_tokens/admin_router.py:63` -> `embed_tokens/service.py:bulk_revoke_embed_tokens()` | CORRECT |

### Schema Alignment

**Backend `AdminShareTokenResponse`** (maps/schemas.py:165):
```
id, map_id, map_name, token, is_active, expires_at, created_at, created_by (str|None), embed_token_count (int)
```

**Frontend `AdminShareTokenResponse`** (types/api.ts:970):
```
id, map_id, map_name, token, is_active, expires_at, created_at, created_by (string|null), embed_token_count (number)
```
Result: **MATCH** -- all fields align.

**Backend `EmbedTokenResponse`** (embed_tokens/schemas.py:60):
```
id, map_id, name (str|None), token_hint, scoped_dataset_ids (list[str]), allowed_origins, expires_at, is_active, use_count, last_used_at, created_at
```

**Frontend `EmbedTokenResponse`** (types/api.ts:988):
```
id, map_id, token_hint, allowed_origins, expires_at, is_active, use_count, last_used_at, created_at
```
Result: **DRIFT** -- Frontend is missing `name` and `scoped_dataset_ids` fields. These are present in the backend response but not typed in the frontend. Neither field is rendered on the admin page or SharePanel, so there is no runtime error, but the types are incomplete.

### Status Badge Logic

**`getShareStatus()` (line 48-52):**
- `!is_active` -> "revoked"
- `expires_at` in the past -> "expired"
- Otherwise -> "active"

Backend `list_share_tokens` applies these same filters server-side (`status_filter` param). The frontend derives status client-side for display, server-side for filtering. **CORRECT** -- logic is consistent.

**`getEmbedStatus()` (line 60-66):**
- `!is_active` -> "revoked"
- `daysLeft <= 0` -> "expired"
- `daysLeft <= 7` -> "expiring_soon"
- Otherwise -> "active"

Backend `list_admin_embed_tokens` applies matching server-side filters. **CORRECT**.

### Pagination and Search

- Page size: 50 (hardcoded `PAGE_SIZE`). Backend limit max: 200. **CORRECT**.
- `DataTablePagination` receives `page`, `totalPages`, `rangeStart`, `rangeEnd`, `total`, `onPageChange`. Uses `paginationRange()` utility. **CORRECT**.
- `DataTableSearch` debounced (300ms), resets page to 0 on change. **CORRECT**.
- Status filter buttons: `''`, `'active'`, `'expired'`, `'revoked'`. Backend accepts regex `^(active|expired|revoked)$`. **CORRECT**.

### Cache Invalidation

| Mutation | Invalidates | Should Also Invalidate | Issue |
|----------|------------|----------------------|-------|
| `useAdminRevokeShareToken` | `['admin', 'share-tokens']` | -- | OK |
| `useBulkRevokeEmbedTokens` | `['admin', 'embed-tokens']` | `['admin', 'share-tokens']` | **BUG** -- embed_token_count on parent rows goes stale |

**Finding BUG-1:** After bulk-revoking embed tokens, the share token list still shows the old `embed_token_count` because `useBulkRevokeEmbedTokens` only invalidates `['admin', 'embed-tokens']` but not `['admin', 'share-tokens']`. The embed count in the share tokens list is computed server-side by counting active embed tokens, so after revoking some, the parent share token row shows a stale count until the user navigates away and back.

**Fix:** Add `qc.invalidateQueries({ queryKey: ['admin', 'share-tokens'] })` to `useBulkRevokeEmbedTokens.onSuccess` in `use-admin.ts` line 217.

## Wiring Audit: Map Creator ShareDialog

### Hook -> API -> Backend Trace

| Hook | API Function | Backend Endpoint | Status |
|------|-------------|------------------|--------|
| `usePublishMap()` | `publishMap(id, visibility)` -> `PUT /maps/{id}` | `maps/router.py` | CORRECT |
| `useCreateShareToken()` | `createShareToken(mapId)` -> `POST /maps/{mapId}/share` | `maps/router.py` | CORRECT |
| `useRevokeShareToken()` | `revokeShareToken(mapId)` -> `DELETE /maps/{mapId}/share` | `maps/router.py:574` -> `revoke_share_token_by_map()` | CORRECT |
| `useMapShareToken(mapId)` | `getMapShareToken(mapId)` -> `GET /maps/{mapId}/share` | `maps/router.py` | CORRECT |
| `useUpdateShareToken()` | `updateShareTokenExpiration(mapId, expiresAt)` -> `PATCH /maps/{mapId}/share` | `maps/router.py` | CORRECT |
| `useCreateEmbedToken()` | `createEmbedToken(mapId, days, origins)` -> `POST /maps/{mapId}/embed-tokens/` | `embed_tokens/router.py` | CORRECT |
| `useMapEmbedTokens(mapId)` | `listEmbedTokens(mapId)` -> `GET /maps/{mapId}/embed-tokens/` | `embed_tokens/router.py` | CORRECT |
| `useUpdateEmbedToken()` | `updateEmbedTokenOrigins(mapId, tokenId, origins)` -> `PATCH /maps/{mapId}/embed-tokens/{tokenId}/` | `embed_tokens/router.py` | CORRECT |

### ShareDialog Edge Cases

1. **No share token exists:** Shows "Generate Share Link" button (line 457-471). `shareToken` is null from query, so share/embed sections are hidden. **CORRECT**.

2. **Map is not public:** Share link section only renders when `isPublic` (line 298). Visibility selector still shows. **CORRECT**.

3. **Expired token:** `getMapShareToken` returns the token even if expired (server stores `is_active` and `expires_at` separately). The dialog shows it as active with the copy/open buttons. There is no visual indicator in the ShareDialog that the share link is expired. The admin page handles this correctly with status badges, but the creator dialog does not.

4. **Revoked token:** After revoke, `useRevokeShareToken.onSuccess` invalidates `['map-share-token', mapId]` which causes re-fetch. The query returns null/no-token, so the dialog correctly switches to "Generate Share Link" state. **CORRECT**.

5. **Embed token auto-creation:** `handleGetShareLink()` (line 157-170) creates a share token, then runs `runVisibilityCheck()`. If `has_non_public` is true, it auto-creates an embed token. This handles the mixed public/non-public dataset scenario. **CORRECT**.

### ShareDialog Completeness Assessment

| Control | Wired | Working |
|---------|-------|---------|
| Visibility selector (private/internal/public) | Yes | Yes |
| Generate share link | Yes | Yes |
| Copy share link | Yes | Yes |
| Open share link in new tab | Yes | Yes |
| Set expiration | Yes | Yes (PATCH) |
| Domain restrictions (embed token) | Yes | Yes (PATCH) |
| Revoke share link | Yes | Yes |
| Copy embed code | Yes | Yes |
| Embed code generation | Yes | Yes |

## Identified Issues

### BUG-1: Stale embed_token_count after bulk revoke (use-admin.ts:217)
**Severity:** Low (cosmetic)
**What:** `useBulkRevokeEmbedTokens.onSuccess` invalidates `['admin', 'embed-tokens']` but not `['admin', 'share-tokens']`.
**Impact:** After bulk-revoking embed tokens, the parent share token row shows the old embed count.
**Fix:** Add `qc.invalidateQueries({ queryKey: ['admin', 'share-tokens'] })` to `onSuccess`.

### BUG-2: Admin share token revoke does not cascade to embed tokens (backend)
**Severity:** Medium (data integrity)
**What:** `revoke_share_token()` in `maps/service.py:928` only sets `is_active=False` on the share token. It does NOT revoke associated embed tokens. Meanwhile, the map creator's `revoke_share_token_by_map()` (line 1019) also does not revoke embed tokens -- but the frontend `useRevokeShareToken.onSuccess` invalidates `['map-embed-tokens', mapId]` which refreshes the list, giving the illusion of cleanup.
**Impact:** After admin revokes a share token, its embed tokens remain technically "active" in the database. The shared map endpoint will reject requests (no active share token), but the embed tokens remain in a zombie state -- they show as "active" in the admin embed tokens sub-table even though they're useless.
**Fix (backend):** In `revoke_share_token()`, also revoke embed tokens for the same `map_id`. Or, in `admin_revoke_share_token` endpoint, call both `revoke_share_token` and `bulk_revoke_embed_tokens` for that map.

### BUG-3: Expired share link shows as functional in ShareDialog
**Severity:** Low (UX)
**What:** The ShareDialog shows copy/open buttons for an expired share token with no warning. The admin page correctly shows "Expired" badge.
**Impact:** Map creator may copy and share an expired link that returns errors.
**Fix:** Check `shareExpires` in ShareDialog and show a warning badge when `new Date(shareExpires) < new Date()`. Could reuse the same `getShareStatus` logic pattern.

### DRIFT-1: Frontend EmbedTokenResponse missing fields
**Severity:** Very low (no runtime impact)
**What:** Backend `EmbedTokenResponse` includes `name` and `scoped_dataset_ids`. Frontend type omits both.
**Impact:** No runtime error (extra fields ignored), but TypeScript types are inaccurate.
**Fix:** Add `name?: string | null` and `scoped_dataset_ids?: string[]` to frontend `EmbedTokenResponse`.

### UX-1: No visual indicator for embed token revocation scope
**Severity:** Very low
**What:** When selecting embed tokens for bulk revoke, there's no indication of which map they belong to (since they're already scoped to one map's sub-table, this is minor).
**Impact:** None in practice -- the sub-table is already scoped to one map.

### UX-2: Embed tokens sub-table has no "revoked" tokens filter
**Severity:** Very low
**What:** The sub-table (`EmbedTokensSubTable`) fetches ALL embed tokens (limit 200) for a map, including already-revoked ones. Revoked tokens show with a "Revoked" badge but cannot be hidden/filtered.
**Impact:** Over time, revoked tokens accumulate and clutter the sub-table.
**Possible fix:** Add a toggle to hide revoked tokens, or pass `status=active` to the `useAdminEmbedTokens` params.

### UX-3: Admin page `useDocumentTitle` uses hardcoded English
**Severity:** Very low
**What:** Line 223: `useDocumentTitle('Admin Published Maps')` is not i18n'd.
**Fix:** Use `useDocumentTitle(t('sharedMaps.title'))`.

## Common Pitfalls

### Pitfall 1: Cache key mismatch between admin and creator mutations
**What goes wrong:** Admin operations (revoking share tokens) don't invalidate creator-side query keys (`['map-share-token', mapId]`, `['map-embed-tokens', mapId]`). If admin and creator have the same browser session, stale data could appear.
**Why it happens:** Admin and creator hooks use different query key prefixes (`['admin', ...]` vs `['map-share-token', ...]`).
**How to avoid:** This is acceptable for now since admin and creator pages are separate contexts. Only matters if a single user rapidly switches between admin and builder.
**Warning signs:** Admin revokes a share token, then navigates to the map builder -- ShareDialog still shows the old share link until refetch.

### Pitfall 2: Domain restriction toggle clears immediately
**What goes wrong:** In ShareDialog line 403-406, unchecking the "Restrict to domains" switch immediately calls `handleSaveDomains()` with empty `domainsValue`, sending `allowed_origins: null` to the backend. This is a fire-and-forget save with no confirmation.
**Why it happens:** The switch `onCheckedChange` handler calls the save function directly.
**Impact:** Low -- user can re-enable the toggle, but there's no undo.

## Validation Architecture

### Test Map
| Behavior | Test Type | How to Verify |
|----------|-----------|---------------|
| Admin share token list loads | Manual | Navigate to /admin/shared-maps, verify table loads |
| Admin revoke share token | Manual | Click revoke, confirm dialog, verify badge changes |
| Admin embed tokens sub-table loads | Manual | Expand a row with embed tokens, verify sub-table loads |
| Admin bulk revoke embed tokens | Manual | Select embed tokens, click revoke, confirm, verify |
| ShareDialog visibility change | Manual | Open share dialog, toggle visibility options |
| ShareDialog create/copy share link | Manual | Generate link, copy, verify URL works |
| ShareDialog set expiration | Manual | Open settings, set date, save, verify |
| ShareDialog domain restrictions | Manual | Enable domain restrict, set domains, save, verify |
| ShareDialog revoke share link | Manual | Click revoke, confirm, verify link is gone |

No automated tests exist for these UI flows. All verification is manual.

## Sources

### Primary (HIGH confidence)
- `frontend/src/pages/admin/AdminSharedMapsPage.tsx` -- full component read
- `frontend/src/components/builder/SharePanel.tsx` -- full component read
- `frontend/src/hooks/use-admin.ts` -- all sharing hooks traced
- `frontend/src/hooks/use-maps.ts` -- share token hooks traced
- `frontend/src/hooks/use-embed-tokens.ts` -- embed token hooks traced
- `frontend/src/api/admin.ts` -- admin API functions traced
- `frontend/src/api/maps.ts` -- map/share API functions traced
- `frontend/src/api/embed-tokens.ts` -- embed token API functions traced
- `frontend/src/types/api.ts` -- type definitions verified
- `backend/app/admin/router.py` -- share token endpoints traced
- `backend/app/embed_tokens/admin_router.py` -- embed token admin endpoints traced
- `backend/app/maps/schemas.py` -- response schemas compared
- `backend/app/embed_tokens/schemas.py` -- response schemas compared
- `backend/app/maps/service.py` -- service functions traced
- `backend/app/embed_tokens/service.py` -- service functions traced
- `frontend/src/i18n/locales/en/admin.json` -- i18n keys verified complete
- `frontend/src/i18n/locales/en/builder.json` -- share dialog i18n verified

## Metadata

**Confidence breakdown:**
- Wiring correctness: HIGH -- every hook/API/endpoint traced end-to-end
- Schema alignment: HIGH -- field-by-field comparison done
- Status badge logic: HIGH -- client and server logic compared
- Cache invalidation: HIGH -- all mutation onSuccess handlers reviewed
- UI/UX issues: MEDIUM -- based on code review, not runtime testing

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable domain, no external deps)
