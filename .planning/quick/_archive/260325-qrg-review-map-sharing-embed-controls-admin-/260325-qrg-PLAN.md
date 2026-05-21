---
phase: 260325-qrg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/admin/router.py
  - backend/app/maps/service.py
  - backend/tests/test_maps.py
  - frontend/src/hooks/use-admin.ts
  - frontend/src/types/api.ts
  - frontend/src/components/builder/SharePanel.tsx
  - frontend/src/pages/admin/AdminSharedMapsPage.tsx
autonomous: true
requirements: [QRG-01]

must_haves:
  truths:
    - "Admin bulk-revoking embed tokens immediately updates the embed count shown on parent share token rows"
    - "Admin revoking a share token also deactivates all embed tokens for that map"
    - "Map creator ShareDialog shows a warning when the share link has expired"
    - "Frontend EmbedTokenResponse type includes all backend-returned fields"
  artifacts:
    - path: "backend/app/admin/router.py"
      provides: "Cascade revoke of embed tokens when admin revokes share token"
      contains: "bulk_revoke_embed_tokens"
    - path: "frontend/src/hooks/use-admin.ts"
      provides: "Cache invalidation for share-tokens after embed bulk-revoke"
      contains: "admin.*share-tokens"
    - path: "frontend/src/components/builder/SharePanel.tsx"
      provides: "Expired share link warning in ShareDialog"
      contains: "expired"
    - path: "frontend/src/types/api.ts"
      provides: "Complete EmbedTokenResponse type matching backend schema"
      contains: "scoped_dataset_ids"
    - path: "backend/tests/test_maps.py"
      provides: "Test for cascade revoke behavior"
      contains: "cascade"
  key_links:
    - from: "backend/app/admin/router.py"
      to: "backend/app/embed_tokens/service.py"
      via: "cascade revoke call in admin_revoke_share_token"
      pattern: "bulk_revoke.*embed"
    - from: "frontend/src/hooks/use-admin.ts"
      to: "TanStack Query cache"
      via: "invalidateQueries in useBulkRevokeEmbedTokens.onSuccess"
      pattern: "share-tokens"
---

<objective>
Fix wiring bugs and easy UI/UX wins in the admin shared maps page and map creator ShareDialog.

Purpose: The research audit identified three bugs (stale cache after embed bulk-revoke, missing cascade on share token revoke, expired share link shown as functional) and two type/i18n drift issues. All are surgical fixes to existing working code.

Output: Corrected cache invalidation, backend cascade revoke, expired-link warning in ShareDialog, aligned frontend types, i18n fix for document title.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260325-qrg-review-map-sharing-embed-controls-admin-/260325-qrg-RESEARCH.md
@.planning/quick/260325-qrg-review-map-sharing-embed-controls-admin-/260325-qrg-CONTEXT.md

<interfaces>
<!-- Key types and contracts the executor needs. Extracted from codebase. -->

From frontend/src/hooks/use-admin.ts (line 212-220):
```typescript
export function useBulkRevokeEmbedTokens() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenIds: string[]) => bulkRevokeEmbedTokens(tokenIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'embed-tokens'] });
      // BUG-1: Missing invalidation of ['admin', 'share-tokens']
    },
  });
}
```

From frontend/src/types/api.ts (line 988-998):
```typescript
export interface EmbedTokenResponse {
  id: string;
  map_id: string;
  token_hint: string;
  allowed_origins: string[] | null;
  expires_at: string;
  is_active: boolean;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
  // DRIFT: missing name?: string | null, scoped_dataset_ids?: string[]
}
```

From backend/app/admin/router.py (line 646-660):
```python
async def admin_revoke_share_token(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.maps.service import revoke_share_token
    revoked = await revoke_share_token(db, token_id)
    if not revoked:
        raise HTTPException(...)
    await db.commit()
    # BUG-2: No cascade to embed tokens
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

From backend/app/maps/service.py (line 928-940):
```python
async def revoke_share_token(session, token_id):
    # Only sets share token is_active=False
    # Does NOT touch embed tokens for the same map_id
```

From backend/app/embed_tokens/service.py (line 360-383):
```python
async def bulk_revoke_embed_tokens(
    db: AsyncSession,
    token_ids: list[uuid.UUID],
) -> int:
    """Bulk-revoke embed tokens. Returns count of tokens actually revoked."""
    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.id.in_(token_ids),
            EmbedToken.is_active.is_(True),
        )
    )
    tokens = list(result.scalars().all())
    for token in tokens:
        token.is_active = False
    await db.flush()
    # Best-effort cache invalidation
    try:
        cache = get_cache()
        for token in tokens:
            await cache.delete(f"embed_token:{token.token_hash}")
    except Exception:
        pass
```

From backend/app/embed_tokens/models.py:
```python
class EmbedToken(Base):
    map_id: Mapped[uuid.UUID]  # FK to catalog.maps.id
    is_active: Mapped[bool]
```

From frontend/src/components/builder/SharePanel.tsx (line 88-90):
```typescript
const shareTokenQuery = useMapShareToken(mapId);
const shareToken = shareTokenQuery.data?.token ?? null;
const shareExpires = shareTokenQuery.data?.expires_at ?? null;
// No expired check anywhere -- BUG-3
```

From frontend/src/i18n/locales/en/admin.json (line 305-306):
```json
"sharedMaps": { "title": "Published Maps", ... }
```

From backend/tests/test_maps.py (line 1502):
```python
class TestAdminShareTokenListing:
    # This is the correct class for admin share token tests
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix backend cascade revoke and stale cache invalidation</name>
  <files>backend/app/admin/router.py, backend/app/maps/service.py, backend/tests/test_maps.py, frontend/src/hooks/use-admin.ts, frontend/src/types/api.ts</files>
  <action>
**BUG-2 fix -- Cascade embed token revocation (backend):**

In `backend/app/admin/router.py`, update `admin_revoke_share_token` (line 646-660) to cascade-revoke embed tokens. Do NOT add a new function to `maps/service.py` -- instead, call the existing `bulk_revoke_embed_tokens` from `embed_tokens/service.py` directly in the admin endpoint. This keeps embed token revocation logic in one place.

Steps:
1. Modify `revoke_share_token` in `backend/app/maps/service.py` to return `MapShareToken | None` instead of `bool`. Return the token object on success, `None` on not-found. Update the admin endpoint to check `if token_obj is None` for 404. Use `token_obj.map_id` for the cascade step.
2. In `admin_revoke_share_token` in `backend/app/admin/router.py`, after calling `revoke_share_token(db, token_id)` and before `db.commit()`:
   - Query all active embed token IDs for the map: `SELECT id FROM embed_tokens WHERE map_id = token_obj.map_id AND is_active = true`
   - If any exist, call `bulk_revoke_embed_tokens(db, token_ids)` imported from `app.embed_tokens.service`. This reuses the existing function which already handles cache invalidation and flush.
   - Import: `from app.embed_tokens.service import bulk_revoke_embed_tokens` and `from app.embed_tokens.models import EmbedToken`
3. Also update `revoke_share_token_by_map` callers if any depend on the bool return -- they are independent functions, so no change needed.

**BUG-1 fix -- Stale embed count cache (frontend):**

In `frontend/src/hooks/use-admin.ts`, in `useBulkRevokeEmbedTokens` `onSuccess` (line 216-218), add:
```typescript
qc.invalidateQueries({ queryKey: ['admin', 'share-tokens'] });
```
right after the existing `['admin', 'embed-tokens']` invalidation.

**DRIFT-1 fix -- Frontend EmbedTokenResponse type:**

In `frontend/src/types/api.ts`, add to `EmbedTokenResponse` (line 988-998):
```typescript
name?: string | null;
scoped_dataset_ids?: string[];
```
Place after `map_id` field.

**Test -- Cascade revoke:**

In `backend/tests/test_maps.py`, add a test `test_admin_revoke_share_token_cascades_embed_tokens` inside the `TestAdminShareTokenListing` class (line 1502). The test should:
1. Create a public map, create a share token, create an embed token for that map.
2. Call `DELETE /admin/share-tokens/{token_id}` with admin auth.
3. Assert 204 response.
4. Verify the embed token is now `is_active=False` by calling `GET /admin/embed-tokens/?map_id={map_id}` or directly querying.
Follow the existing test patterns in `TestAdminShareTokenListing` (e.g., `test_admin_list_share_tokens` at line 1503 for admin auth patterns).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T api python -m pytest tests/test_maps.py::TestAdminShareTokenListing::test_admin_revoke_share_token_cascades_embed_tokens -xvs 2>&1 | tail -20</automated>
  </verify>
  <done>
    - `revoke_share_token` returns `MapShareToken | None` (not bool)
    - `admin_revoke_share_token` endpoint cascades to deactivate embed tokens by calling existing `bulk_revoke_embed_tokens` from `embed_tokens/service.py`
    - `useBulkRevokeEmbedTokens.onSuccess` invalidates both `['admin', 'embed-tokens']` and `['admin', 'share-tokens']`
    - `EmbedTokenResponse` type includes `name` and `scoped_dataset_ids`
    - New test passes proving cascade behavior
  </done>
</task>

<task type="auto">
  <name>Task 2: ShareDialog expired-link warning and i18n fix</name>
  <files>frontend/src/components/builder/SharePanel.tsx, frontend/src/pages/admin/AdminSharedMapsPage.tsx, frontend/src/i18n/locales/en/builder.json, frontend/src/i18n/locales/es/builder.json, frontend/src/i18n/locales/fr/builder.json, frontend/src/i18n/locales/de/builder.json</files>
  <action>
**BUG-3 fix -- Expired share link warning in ShareDialog:**

In `frontend/src/components/builder/SharePanel.tsx`:

1. Derive an `isExpired` boolean near line 90 (after `shareExpires` is assigned):
```typescript
const isExpired = shareExpires ? new Date(shareExpires) < new Date() : false;
```

2. In the share link section (around line 329-333 where the status summary renders), add an expired warning. When `isExpired` is true, show a destructive-styled badge/text before the "Expires" summary line. Use the existing Badge component from shadcn if available, or a styled span:
```tsx
{isExpired && (
  <div className="flex items-center gap-1.5 text-xs text-destructive">
    <AlertTriangle className="h-3.5 w-3.5" />
    <span>{t('share.expired')}</span>
  </div>
)}
```
Import `AlertTriangle` from `lucide-react`.

3. When `isExpired`, change the "Expires: {date}" summary text to show the date with destructive text color so it stands out.

4. Add i18n key `share.expired` to all 4 locale builder.json files:
   - en: `"expired": "This share link has expired"`
   - es: `"expired": "Este enlace ha caducado"`
   - fr: `"expired": "Ce lien de partage a expir\u00e9"`
   - de: `"expired": "Dieser Link ist abgelaufen"`

**UX-3 fix -- Admin page document title i18n:**

In `frontend/src/pages/admin/AdminSharedMapsPage.tsx` line 223, change:
```typescript
useDocumentTitle('Admin Published Maps');
```
to:
```typescript
useDocumentTitle(t('sharedMaps.title'));
```
Verify `t` is already imported from `useTranslation('admin')` (it should be, since the component already uses `t()` elsewhere). The key `sharedMaps.title` already exists in `admin.json` with value `"Published Maps"`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | tail -20</automated>
  </verify>
  <done>
    - ShareDialog shows "This share link has expired" warning with AlertTriangle icon when share token is past its expiration date
    - Expired date text uses destructive color for visual distinction
    - i18n keys added in all 4 locales (en, es, fr, de)
    - Admin page document title uses i18n key instead of hardcoded English
    - TypeScript compiles cleanly
  </done>
</task>

</tasks>

<verification>
- Backend: `docker compose exec -T api python -m pytest tests/test_maps.py -k "admin_revoke" -xvs` -- cascade test passes
- Backend: `docker compose exec -T api python -m pytest tests/test_embed_tokens.py -k "bulk_revoke" -xvs` -- existing bulk revoke tests still pass
- Frontend: `npx tsc --noEmit --project frontend/tsconfig.json` -- no type errors
- Manual: Navigate to /admin/shared-maps, expand a row with embed tokens, bulk-revoke them, verify parent row embed count updates without page refresh
- Manual: In map builder, open ShareDialog for a map with an expired share link, verify warning is displayed
</verification>

<success_criteria>
- Admin share token revoke cascades to deactivate all embed tokens for that map (BUG-2)
- Bulk embed token revoke refreshes the share token list to update embed counts (BUG-1)
- ShareDialog shows expired-link warning when share token past expiration (BUG-3)
- EmbedTokenResponse frontend type matches backend schema (DRIFT-1)
- Admin page title uses i18n (UX-3)
- All existing tests pass, new cascade test passes
</success_criteria>

<output>
After completion, create `.planning/quick/260325-qrg-review-map-sharing-embed-controls-admin-/260325-qrg-SUMMARY.md`
</output>
