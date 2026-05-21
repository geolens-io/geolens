# Quick Task: Maps Page Thumbnail Error - Research

**Researched:** 2026-03-29
**Domain:** Map thumbnail auth pipeline (frontend img tags + backend visibility check)
**Confidence:** HIGH

## Summary

The maps page at `/maps` shows a 404 error in the browser console/network tab for `GET /api/maps/{id}/thumbnail`. The **visual** symptom was already fixed in phase 260328-k40 (onError fallback shows a placeholder icon instead of a broken image). The **root cause** remains: the `<img>` tag cannot send JWT auth headers, and the thumbnail endpoint returns 404 for non-public maps when no user is authenticated.

**Root cause chain:**
1. Map "Populated Places" (`83ef732f-...`) has `visibility = 'private'` and `thumbnail_uri = 'maps/thumbnails/83ef732f-...jpg'` set in the database
2. The API list response includes `thumbnail_url: "/maps/{id}/thumbnail"` because `thumbnail_uri` is truthy
3. The frontend renders `<img src="/api/maps/{id}/thumbnail">` -- a raw browser GET request with **no Authorization header**
4. The backend's `get_map_thumbnail` endpoint uses `get_optional_user` which resolves to `None` (no JWT, no API key)
5. Visibility check: `if user is None and map_obj.visibility != "public": raise 404`
6. The thumbnail file **actually exists and is valid** at `/app/staging/maps/thumbnails/83ef732f-...jpg` (8755 bytes, valid JPEG)

**Primary recommendation:** Fetch thumbnails through the authenticated API client and use object URLs, rather than direct `<img src>` pointing at the backend.

## Findings

### Playwright Investigation (HIGH confidence)

Automated browser testing confirmed:
- **Console errors:** `Failed to load resource: the server responded with a status of 404 (Not Found)` (appears twice -- list and grid view)
- **Failed request:** `404 http://localhost:8080/api/maps/83ef732f-31b8-4c64-9740-4576dcd640f6/thumbnail`
- **No page errors:** No uncaught JavaScript exceptions
- **No broken images:** The onError fallback (from 260328-k40 fix) works -- placeholder MapIcon shown
- **Visual:** Page renders correctly with placeholder icon, no broken image artifacts

### Auth Gap Analysis (HIGH confidence)

The `<img>` element cannot attach the JWT token from zustand. The backend's thumbnail endpoint (`router.py:662-705`) uses `get_optional_user` which supports:
- `Authorization: Bearer <JWT>` header -- works for `apiFetch()`, NOT for `<img>` tags
- `X-Api-Key` header -- same problem
- `?api_key=<key>` query parameter -- would work but requires generating/exposing API keys

The list response at `service.py:264` gates `thumbnail_url` on `if map_obj.thumbnail_uri` but does **not** consider visibility. It returns the URL for private maps, which the browser then tries to load without auth.

### Storage Verification (HIGH confidence)

- **File exists:** `/app/staging/maps/thumbnails/83ef732f-31b8-4c64-9740-4576dcd640f6.jpg`
- **File valid:** 8755 bytes, starts with `ffd8ffe0` (JPEG magic bytes)
- **DB record:** `thumbnail_uri = 'maps/thumbnails/83ef732f-31b8-4c64-9740-4576dcd640f6.jpg'`
- **Map visibility:** `private`
- This is NOT a missing file issue -- it is purely an auth issue

## Recommended Fix

### Option A: Authenticated thumbnail fetch via blob URLs (recommended)

Create a `useMapThumbnail(url)` hook that:
1. Uses `apiFetch()` to fetch the thumbnail as a blob (with auth headers)
2. Creates an object URL via `URL.createObjectURL()`
3. Returns the object URL for the `<img>` src
4. Cleans up on unmount via `URL.revokeObjectURL()`

This is the correct pattern for auth-gated image resources. It works for all visibility levels.

```typescript
// Hook sketch
function useMapThumbnail(thumbnailUrl: string | null) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!thumbnailUrl) return;
    let revoked = false;
    apiFetch<Blob>(thumbnailUrl, { headers: { Accept: 'image/*' } })
      // Need raw response, not JSON -- see implementation note below
      .then(...)
    return () => { if (src) URL.revokeObjectURL(src); revoked = true; };
  }, [thumbnailUrl]);
  return src;
}
```

**Implementation note:** `apiFetch()` currently always calls `.json()` on the response. You will need either:
- A new `apiFetchBlob()` function that returns the raw blob
- Or a flag on `apiFetch()` to skip JSON parsing

### Option B: Token-in-query-param for img tags (simpler but less secure)

Append `?token=<jwt>` to the img src URL and have the backend accept JWT from query params for image endpoints only. This leaks the token in browser history, server access logs, and referrer headers. Not recommended.

### Option C: Backend returns thumbnail as base64 in the list response (simple but wasteful)

Include the thumbnail data inline in the list response as a base64 data URI. This bloats the API response and breaks caching. Not recommended for list endpoints.

### Option D: Don't return thumbnail_url for non-public maps in list response (workaround)

Modify `list_maps()` to only include `thumbnail_url` when `visibility == 'public'`. This avoids the 404 but prevents authenticated users from seeing thumbnails for their own private maps. Not a real fix.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/api/client.ts` | Add `apiFetchRaw()` or `apiFetchBlob()` that returns raw Response |
| `frontend/src/hooks/use-map-thumbnail.ts` | New hook: authenticated thumbnail fetch with blob URL |
| `frontend/src/components/maps/MapCard.tsx` | Use `useMapThumbnail()` hook instead of direct img src |
| `frontend/src/components/maps/MapCardGrid.tsx` | Same change |

## Sources

- Playwright automated browser test -- console errors, network failures, screenshots
- `backend/app/maps/router.py` lines 662-705 -- thumbnail GET endpoint with visibility check
- `backend/app/maps/service.py` lines 258-266 -- list response thumbnail_url construction
- `backend/app/auth/dependencies.py` lines 20-41 -- API key resolution, lines 44+ -- get_optional_user
- `frontend/src/components/maps/MapCard.tsx` -- current img tag with onError fallback
- `frontend/src/api/client.ts` -- apiFetch always parses JSON, no blob support
- Database query: `catalog.maps` visibility='private', thumbnail_uri set
- Storage probe: file exists and is valid JPEG at `/app/staging/maps/thumbnails/`
