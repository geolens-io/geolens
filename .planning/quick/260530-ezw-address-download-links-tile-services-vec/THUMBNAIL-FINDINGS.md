# Thumbnail Load Errors — Root-Cause Findings (READ-ONLY investigation)

Date: 2026-05-30
Scope: Intermittent thumbnail `ERR_FILE_NOT_FOUND` console errors on the map-list page and the search page.

## TL;DR

Both error shapes come from the **same bug**: `blob:` object URLs are created per-component-instance via TanStack Query, but the `useEffect` cleanup in `useMapThumbnail` / `useQuicklook` calls `URL.revokeObjectURL()` while the *same* blob URL value is still cached in React Query (shared across query-key-identical consumers). When a sibling/replacement component re-uses that cached (now-revoked) URL as `<img src>`, the browser logs `ERR_FILE_NOT_FOUND`.

- Shape (B) `GET blob:http://localhost:8080/<uuid> net::ERR_FILE_NOT_FOUND` — an `<img>` pointing at a revoked `blob:` URL. This is the dominant case.
- Shape (A) `<uuid>:1 Failed to load resource: net::ERR_FILE_NOT_FOUND` — the same thing; Chrome sometimes prints only the trailing UUID segment of the `blob:` URL (the blob's UUID), not the full `blob:` scheme. It is **not** a separate same-origin file fetch. (Both `thumbnail_url` and quicklook are server routes fetched via `apiFetchBlob`, never used directly as `<img src>` — see below — so there is no real same-origin `/<uuid>` asset request in this code path.)

The stored/displayed thumbnail source is **NOT** a persisted blob URL — that part is correct. `thumbnail_url` is a server route (`/maps/{id}/thumbnail/`). The bug is purely in the client-side blob-URL *lifecycle*, not in what gets persisted.

---

## Task 1 — What src do the cards use, and where does it come from?

### Map-list cards (`MapCard` and `MapCardGrid`)
- Backend populates `thumbnail_url = "/maps/{id}/thumbnail/"` only when `thumbnail_uri` is set — `backend/app/modules/catalog/maps/_router_helpers.py:265,282`. Schema field: `backend/app/modules/catalog/maps/schemas.py:739,854`. So the API field is a **server route**, not a blob/data URL. Good — survives reload.
- The card does NOT use that route directly as `<img src>`. Browser `<img>` requests carry no `Authorization` header, so it routes the fetch through `useMapThumbnail`:
  - `frontend/src/components/maps/hooks/use-map-thumbnail.ts:33-42` — `useQuery` calls `apiFetchBlob(thumbnailPath, {cache:'reload'})` (Bearer-attached, `client.ts:174`) then `URL.createObjectURL(blob)`.
  - Returned `blob:` URL is fed to `<img src>` at `MapCard.tsx:39` and `MapCardGrid.tsx:34`.
- `imgError` local state + `onError` falls back to a `MapIcon` placeholder (`MapCard.tsx:26,44`; `MapCardGrid.tsx:21,39`).

### Search-page result cards (`SearchResultCard`)
- Quicklook image at `SearchResultCard.tsx:339-345` uses `quicklookBlobUrl` from `useQuicklook` (`SearchResultCard.tsx:158`).
- `frontend/src/components/maps/hooks/use-quicklook.ts:57-65` — `useQuery` → `apiFetchBlob('/datasets/{id}/quicklook?size=...')` → `URL.createObjectURL(blob)`.
- Fallback is `BBoxPreview` (`SearchResultCard.tsx:347`), and a session 404 negative-cache (`quicklook-cache.ts`) prevents re-fetching genuinely-missing files. There is **no `onError`→placeholder** swap on the quicklook `<img>` (unlike MapCard), so a dead blob URL here stays broken until re-render.

Both hooks are structurally identical and share the same lifecycle defect.

---

## Task 2 — Root cause of each error shape

The defect (both hooks):

```ts
// use-map-thumbnail.ts:33  /  use-quicklook.ts:51
const { data: src } = useQuery({ queryKey: ['map-thumbnail', thumbnailUrl, version], queryFn: () => URL.createObjectURL(blob), gcTime: 10*60_000, ... });

// use-map-thumbnail.ts:45 / use-quicklook.ts:68
useEffect(() => {
  if (typeof src === 'string') return () => URL.revokeObjectURL(src);  // <-- BUG
}, [src]);
```

The `blob:` URL string is **stored in the React Query cache** (it is the query's `data`, kept alive `gcTime: 10min`). But each consuming component independently runs the `useEffect` cleanup that revokes that exact same shared string when the component unmounts. React Query does not know the cached value was revoked, so it hands the dead string to the next consumer.

Concrete triggers (all reproduce intermittently):

1. **View-mode toggle on the maps page** (`MapsPage.tsx:219-233`). Switching `viewMode` list↔grid unmounts every `MapCard` and mounts a `MapCardGrid` (different component, same `map.id`/`key`). Unmount cleanup revokes the blob URL; the new `MapCardGrid` immediately reads the *same cached blob URL* from React Query and renders it → `ERR_FILE_NOT_FOUND`. (`useQuery` returns cached data synchronously because the key + `staleTime` match.)

2. **React 18/19 StrictMode double-invoke (dev) + remounts**: mount→cleanup(revoke)→remount returns the cached, now-revoked URL.

3. **Two cards sharing one query key**: any time two consumers mount with identical `queryKey` (same `thumbnail_url`+`version`, or same `datasetId`+`size`), the first to unmount revokes the URL out from under the survivor.

4. **Navigation away and back** while the query is still within `gcTime`: the cached blob URL was revoked on the prior unmount, but a fast back-nav re-reads it before garbage collection / refetch.

### Shape (B) — `GET blob:http://localhost:8080/<uuid> ... ERR_FILE_NOT_FOUND`
An `<img src="blob:...">` whose underlying blob was already `revokeObjectURL`'d by a peer/predecessor component's effect cleanup (trigger #1/#3 above). The browser can no longer resolve the blob handle.

### Shape (A) — `<uuid>:1 Failed to load resource: net::ERR_FILE_NOT_FOUND`
Same root event. Chrome's console abbreviates a failing `blob:` resource to the final path segment (the blob's UUID) on the "Failed to load resource" line, while a separate line prints the full `blob:` URL. The two shapes are the **two console lines emitted for one failed blob `<img>` load**, not two different requests. The UUIDs are blob UUIDs, not map/thumbnail IDs, and there is no genuine same-origin `/<uuid>` file route in this flow (the real route is `/maps/{id}/thumbnail/`, always Bearer-fetched).

> Historical note: the doc-comment at `use-map-thumbnail.ts:23-25` claims revoke-on-unmount was *added* to prevent "post-redirect ERR_FILE_NOT_FOUND (SF-05)". That fix over-corrected — revoking a value still live in the React Query cache is exactly what now causes the errors.

---

## Task 3 — Recommended minimal fix

The cleanest minimal fix: **stop revoking a blob URL that is still owned by the React Query cache.** Tie the blob's lifetime to the query cache entry, not to component mount, so the URL is revoked exactly once when React Query evicts it.

### Option A (recommended) — revoke in a query-cache removal subscription, not in `useEffect`
Replace the per-component `useEffect`-revoke in both hooks with a one-time revoke when the query is removed/garbage-collected. TanStack Query exposes this via the query cache:

```ts
// once, app-level (e.g. where the QueryClient is created):
queryClient.getQueryCache().subscribe((event) => {
  if (event.type === 'removed' && Array.isArray(event.query.queryKey)
      && (event.query.queryKey[0] === 'map-thumbnail' || event.query.queryKey[0] === 'quicklook')) {
    const url = event.query.state.data;
    if (typeof url === 'string' && url.startsWith('blob:')) URL.revokeObjectURL(url);
  }
});
```
Then **delete** the `useEffect` cleanup blocks at `use-map-thumbnail.ts:45-51` and `use-quicklook.ts:68-74`. This guarantees the URL stays valid for every concurrent/successive consumer and is revoked exactly once on cache eviction.
Affected files:
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts:45-51` (remove effect)
- `frontend/src/components/maps/hooks/use-quicklook.ts:68-74` (remove effect)
- wherever `QueryClient` is instantiated (add the one-time subscription) — search `new QueryClient(` in `frontend/src/`.

### Option B (smaller, defensive) — keep revoke but make consumers self-heal
If touching the QueryClient is undesirable, at minimum stop the broken-image flash and make MapCard's existing `onError` actually recover, plus give the quicklook `<img>` the same treatment:
1. Add `onError` → placeholder to the quicklook image (`SearchResultCard.tsx:340`, mirror `MapCard.tsx:44`). Currently missing.
2. On `<img onError>`, also invalidate the query so the next render re-fetches a fresh blob instead of re-reading the revoked one (`queryClient.invalidateQueries({ queryKey: ['map-thumbnail', ...] })`). Without this, the cached dead URL is re-served on every re-render.

Option B suppresses the user-visible broken image but does **not** eliminate the console error (the failed `<img>` load still logs once before `onError` fires). Option A eliminates the error at the source. **Recommend Option A.**

### Why not "don't use blob URLs at all"
You can't: `<img src="/maps/{id}/thumbnail/">` would 401/404 because browser image requests don't send the Bearer JWT (this is exactly why the blob-fetch indirection exists — `use-quicklook.ts:14-19`). The `?api_key=` query-param fallback (`backend .../auth/dependencies.py:23`) could in principle let `<img>` hit the route directly, but that exposes the key in the DOM/referrer and is a bigger change. Keep blob URLs; fix their lifecycle.

---

## Affected files (summary)
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts:33-51` — blob create + premature revoke (PRIMARY)
- `frontend/src/components/maps/hooks/use-quicklook.ts:51-74` — same pattern (PRIMARY)
- `frontend/src/components/maps/MapCard.tsx:27,38-45` — list-view consumer
- `frontend/src/components/maps/MapCardGrid.tsx:22,33-40` — grid-view consumer (view-toggle remount trigger)
- `frontend/src/pages/MapsPage.tsx:219-233` — list↔grid swap that remounts cards under one key (TRIGGER)
- `frontend/src/components/search/SearchResultCard.tsx:158,339-348` — search-page consumer; missing `onError` fallback on quicklook img
- `frontend/src/api/client.ts:174-189` — `apiFetchBlob` (Bearer-attached blob fetch; not buggy)
- `backend/app/modules/catalog/maps/_router_helpers.py:265,282` — `thumbnail_url` route population (server route, not a blob; not buggy)
- `frontend/src/lib/quicklook-cache.ts` — session 404 negative-cache (orthogonal; not the cause)
