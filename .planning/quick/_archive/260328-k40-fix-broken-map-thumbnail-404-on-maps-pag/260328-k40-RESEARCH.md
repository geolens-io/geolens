# Quick Task: Fix Broken Map Thumbnail 404 on /maps Page

**Researched:** 2026-03-28
**Domain:** Map thumbnail rendering pipeline (backend + frontend)
**Confidence:** HIGH

## Summary

The 404 error on `GET /api/maps/{id}/thumbnail` is a **data-level issue, not a missing route**. The backend endpoint exists and works correctly. The root cause is that `thumbnail_url` is being returned in the API response for maps that have no actual thumbnail stored.

**Two possible failure modes produce this 404:**

1. **The map's `thumbnail_uri` column is NULL** -- The `GET /{map_id}/thumbnail` endpoint (router.py:666) returns 404 when `map_obj.thumbnail_uri` is falsy. However, the `list_maps` service (service.py:260) and `_build_map_response` helper (router.py:106) both correctly gate `thumbnail_url` behind `if map_obj.thumbnail_uri`. So the frontend should receive `thumbnail_url: null` and show the placeholder icon instead. **This path should not produce the 404 unless the frontend is constructing the URL itself.**

2. **The map's `thumbnail_uri` is set but the file is missing from storage** -- The `GET` endpoint catches `FileNotFoundError` from storage (router.py:692) and returns 404. This happens when a thumbnail was uploaded at some point but the storage file was deleted (e.g., Docker volume reset, manual cleanup).

**Primary recommendation:** The most likely scenario is #2 -- the `thumbnail_uri` column has a value, so the API returns a `thumbnail_url` in the list response, but the actual file on disk is gone. The fix should make the frontend gracefully handle broken thumbnail images (e.g., `onError` fallback on the `<img>` tag), and optionally clean up stale `thumbnail_uri` values.

## Findings

### Backend Route Analysis (HIGH confidence)

The thumbnail routes exist and are correctly implemented in `backend/app/maps/router.py`:

- **`PUT /{map_id}/thumbnail`** (line 593): Accepts base64 data URI, decodes, stores via storage provider at key `maps/thumbnails/{id}.{ext}`, sets `map_obj.thumbnail_uri`.
- **`GET /{map_id}/thumbnail`** (line 656): Reads from storage, serves raw image bytes with `Cache-Control: public, max-age=3600`. Returns 404 if `thumbnail_uri` is NULL or file not found in storage.

### URL Construction Analysis (HIGH confidence)

Both `list_maps()` (service.py:260) and `_build_map_response()` (router.py:106) use the same pattern:

```python
thumbnail_url = f"/maps/{map_obj.id}/thumbnail" if map_obj.thumbnail_uri else None
```

This correctly returns `null` when no thumbnail exists. The frontend then constructs the full URL:

```typescript
// MapCard.tsx:42, MapCardGrid.tsx:37
src={`${API_BASE}${map.thumbnail_url}`}
// API_BASE = '/api', so result is: /api/maps/{id}/thumbnail
```

The frontend only renders the `<img>` when `thumbnail_url` is truthy (MapCard.tsx:40, MapCardGrid.tsx:35), so the 404 only occurs when the backend returns a non-null `thumbnail_url` but the file is missing.

### Nginx Routing (HIGH confidence)

The nginx config correctly proxies `/api/maps/{id}/thumbnail` to the backend:

```nginx
location /api/ {
    rewrite ^/api/(.*) /$1 break;
    proxy_pass $upstream_api;
}
```

No routing issue here.

### Frontend Resilience Gap

The `<img>` tag in both `MapCard.tsx` and `MapCardGrid.tsx` has **no `onError` handler**. When the thumbnail 404s, the browser shows a broken image icon instead of gracefully falling back to the placeholder `<MapIcon>`.

## Root Cause

The map has `thumbnail_uri` set in the database (a previous save captured and uploaded a thumbnail), so the API returns `thumbnail_url: "/maps/{id}/thumbnail"`. But the actual file no longer exists in storage -- likely because:

- Docker volumes were reset/rebuilt
- The storage directory was cleaned up
- The map was created/saved in a different environment

## Recommended Fix

### Option A: Frontend-only fix (recommended -- minimal, resilient)

Add an `onError` fallback to the `<img>` tags in both `MapCard.tsx` and `MapCardGrid.tsx` that hides the broken image and shows the placeholder icon instead. This handles the 404 gracefully regardless of the cause.

```typescript
// In both MapCard.tsx and MapCardGrid.tsx
const [imgError, setImgError] = useState(false);

{map.thumbnail_url && !imgError ? (
  <img
    src={`${API_BASE}${map.thumbnail_url}`}
    alt={...}
    className="w-full h-full object-cover"
    loading="lazy"
    onError={() => setImgError(true)}
  />
) : (
  <MapIcon className="..." />
)}
```

### Option B: Backend cleanup (complementary)

Clear stale `thumbnail_uri` values where the storage file no longer exists. This is a data cleanup task, not a code fix -- the backend already handles the 404 correctly.

### Option C: Backend returns null when file missing (complementary)

Modify `list_maps()` and `_build_map_response()` to verify the file exists before returning `thumbnail_url`. This adds a storage check per map in list queries, which has performance implications and is not recommended for the list endpoint.

**Recommendation: Option A is the right fix.** It is resilient, performant, and handles all failure modes (missing file, storage errors, network issues). Options B/C are optional follow-ups.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/maps/MapCard.tsx` | Add `onError` handler to `<img>`, fallback to placeholder |
| `frontend/src/components/maps/MapCardGrid.tsx` | Same `onError` handler |

## Sources

- `backend/app/maps/router.py` lines 106, 260, 593-702 -- thumbnail URL construction and endpoints
- `backend/app/maps/service.py` line 260 -- list_maps thumbnail_url logic
- `frontend/src/components/maps/MapCard.tsx` lines 40-49 -- thumbnail rendering
- `frontend/src/components/maps/MapCardGrid.tsx` lines 35-44 -- thumbnail rendering
- `frontend/src/hooks/use-builder-save.ts` lines 12-74 -- thumbnail capture and upload
- `backend/app/storage/local.py` lines 27-29 -- get() raises on missing file
