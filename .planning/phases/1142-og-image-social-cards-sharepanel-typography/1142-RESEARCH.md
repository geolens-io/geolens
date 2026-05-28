# Phase 1142: OG-Image Social Cards & SharePanel Typography — Research

**Researched:** 2026-05-28
**Domain:** Social-card OG meta + image pipeline + SharePanel CSS typography
**Confidence:** HIGH (all findings verified against live codebase)

---

## Summary

Phase 1142 covers two requirements: SHARE-08 (per-map OG/social-card meta backed by
a 1200x630 image) and SHARE-10 (SharePanel max-2 font weights). Both are fully
tractable. SHARE-10 is trivial CSS. SHARE-08 has one architecturally hard sub-problem
(crawler-visible meta on a Vite SPA) and one path-selection decision (Path A vs B for
the image). Both are resolved below with concrete file:line anchors.

**Primary recommendation:** Backend meta-HTML route at `GET /api/maps/shared/{token}/card`
for SHARE-08 crawler meta; **Path A** (new `og_image_uri` column + separate routes) for
the 1200x630 image; pure `font-medium` → `font-semibold` substitution at 3 sites for SHARE-10.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Do NOT add `@vercel/og` or `satori` (STACK do-not-add list).
- Feature-add on existing share/embed substrate (`3ed5ceb3` + v1030 SharePanel). Behavior preservation: existing share/thumbnail/embed flows unaffected.
- No architecture rewrites: no new files >500 LOC; no rename of >3 exported symbols.
- Backend changes (new column/route OR resize pipeline) trigger OpenAPI/SDK refresh in Phase 1143 — do NOT regen SDK in Phase 1142; flag in SUMMARY.
- v1031 HARD INVARIANTS apply: no new files >500 LOC, no rename of >3 exported symbols.

### Claude's Discretion
- Path A vs Path B for the 1200x630 image: recommend ONE based on the existing thumbnail pipeline.
- Crawler-facing meta mechanism: pick the smallest-blast-radius mechanism.
- SHARE-10 two-weight system: pick consistent with design tokens.

### Deferred Ideas (OUT OF SCOPE)
- Dynamic per-map OG text beyond title/description (e.g. layer-count badges).
- OG images for non-map pages.
</user_constraints>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OG meta tag injection | API / Backend | — | Crawlers don't run JS; must be server-rendered HTML |
| 1200x630 OG image capture | Browser / Client | — | Only the browser can read the WebGL canvas |
| OG image storage/serve | API / Backend | Storage (S3/local) | Same provider as the existing thumbnail pipeline |
| Share URL routing | Frontend Server (nginx) | — | nginx `try_files` already routes `/m/:token` to `index.html` |
| SharePanel typography | Browser / Client | — | Pure CSS class changes in a React component |

---

## SHARE-08 — Crawler-Facing Meta (the Hard Part)

### How shared map URLs are served today

**Route shape:** The share URL produced by `SharePanel.tsx:808` is:
```
window.location.origin + "/m/" + rawShareToken
```
Example: `https://geolens.example.com/m/abc123xyz`

**nginx handling** (`frontend/nginx.conf:154-159`):
```nginx
location ~ ^/m/ {
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    # X-Frame-Options intentionally omitted
    try_files $uri /index.html;
}
```
The `/m/:token` path hits nginx, which `try_files` falls through to `index.html`. No
backend HTML route handles it. The SPA then bootstraps, reads the token from the URL,
calls `GET /api/maps/shared/{token}` (a JSON API route — `router.py:484`), and renders.

**Embed URL shape** (`SharePanel.tsx:57-62`):
```
{origin}/m/{shareToken}?embed=true&et={embedTokenRaw}
```
Same nginx path, same `try_files` → `index.html` fallthrough.

**Critical fact:** There is NO backend HTML-serving path for `/m/:token` today. Both
share and embed URLs resolve to the static `index.html` via nginx. The static
`index.html` (`frontend/index.html:35-38`) contains only generic site-level OG tags:
```html
<meta property="og:title" content="GeoLens" />
<meta property="og:description" content="Open-source spatial data catalog..." />
<meta property="og:image" content="/og-image.png" />
<meta name="twitter:card" content="summary_large_image" />
```
These are static and identical for every URL. Social/chat crawlers (Slack, Twitter,
LinkedIn, WhatsApp) do NOT execute JavaScript, so they see only these generic tags
regardless of which map token is in the URL.

### Recommended Crawler-Meta Mechanism

**A new backend HTML route at `GET /api/maps/shared/{token}/card`.**

This is the smallest-blast-radius approach that requires zero SSR framework,
zero changes to nginx, and does not alter the existing `/m/:token` SPA flow.

**How it works:**

1. A new FastAPI endpoint returns a minimal HTML document (`text/html`) that contains:
   - Server-rendered `<meta>` tags: `og:title`, `og:description`, `og:image`,
     `og:type=website`, `twitter:card=summary_large_image`, `twitter:image`
   - A `<meta http-equiv="refresh" content="0;url=/m/{token}">` redirect so any human
     visitor who accidentally lands on the `/card` URL is immediately redirected to the
     real SPA viewer at `/m/{token}`.
   - The `og:image` URL points to `GET /api/maps/{map_id}/og-image/` (Path A) or
     `GET /api/maps/{map_id}/thumbnail/` (Path B — reuse existing) depending on path choice.

2. The `/m/:token` route in nginx is unchanged. The existing SPA flow for human visitors
   is completely unaffected.

3. To make social cards work, the **share URL shown in SharePanel** changes from
   `window.location.origin + "/m/" + rawShareToken` to
   `window.location.origin + "/api/maps/shared/" + rawShareToken + "/card"`.

   OR: the frontend continues to use `/m/` links for copy-to-clipboard but the
   displayed "Share link" is the `/card` URL. A simpler alternative: only document the
   `/card` URL as the "canonical social-card unfurl URL" in the dialog hint text.

   **Simplest approach without breaking the existing flow:** Add a "Copy social card
   link" button or hint in SharePanel that produces the `/card` URL for social sharing,
   while "Copy Link" continues to produce the `/m/` URL for normal viewer access. This
   way existing share tokens, iframe embeds, and viewer flows are completely undisturbed.

4. The endpoint (`router.py`) looks up the share token (same `_validate_share_token`
   helper used by `get_shared_map_endpoint`), fetches the Map row for `name`,
   `description`, and `og_image_uri` / `thumbnail_uri`, then returns an HTMLResponse.

**Route registration:** Add to `backend/app/modules/catalog/maps/router.py` (which already
has the maps APIRouter at prefix `/maps`):
```python
@router.get("/shared/{token}/card", response_class=HTMLResponse, include_in_schema=False)
async def shared_map_card_endpoint(token: str, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
```
The `include_in_schema=False` keeps it out of OpenAPI (it's a crawler-only surface, not
part of the JSON API contract). No OpenAPI/SDK refresh needed for this endpoint.

**Why not user-agent sniffing at nginx?** UA-based routing at nginx is fragile —
crawler UA strings change, the list is unbounded, and getting it wrong means real users
see the meta-redirect HTML. The dedicated `/card` route is explicit and zero-ambiguity.

**Why not inject OG tags into `index.html` at build time with Vite?** Per-map tags are
dynamic (per-token map name/description/image). Build-time injection only works for
static tags. No SSR; no Vite plugin that solves this without a full SSR framework.

**Why not an nginx sub-request / proxy trick?** This would require either a separate
backend endpoint (which is what we're building) or a complex nginx `auth_request` +
`sub_filter` setup that is more than 3x the code and fragile under nginx version updates.

---

## SHARE-08 — Path A vs Path B for the 1200x630 Image

### Existing thumbnail pipeline (verified)

**Frontend capture** (`frontend/src/components/builder/hooks/use-builder-save.ts`):
- Function: `doCapture()` at **line 29**
- Constants: `thumbW = 400` (line 33), `thumbH = 250` (line 34)
- Mechanism: `map.once('render', onRender)` + `map.triggerRepaint()` → reads
  `map.getCanvas()`, crop-centers to 400x250, `offscreen.toDataURL('image/jpeg', 0.7)`,
  calls `uploadThumbnail(mapId, dataUri)` (`frontend/src/api/maps.ts:282`).

**Backend PUT** (`backend/app/modules/catalog/maps/router.py`):
- Route: `PUT /{map_id}/thumbnail/` at **line 1504**
- Schema: `ThumbnailUploadRequest(data_uri: str = Field(min_length=22, max_length=100_000))`
  (`schemas.py:933-954`). The **100KB `max_length` limit is the binding constraint**
  for the existing thumbnail upload path.
- Validation: PIL `Image.open(BytesIO(image_bytes)); img.verify()` (lines 1571-1573)
  — Pillow is already imported and `PIL` is in `pyproject.toml` as `Pillow>=12.2.0`.
- Storage: `storage.put(f"maps/thumbnails/{map_id}.{ext}", image_bytes)` (line 1587-1591)
  via `StorageProvider.put()` — supports both local and S3/MinIO backends.
- Column: `Map.thumbnail_uri = storage_key` (line 1599), stored in
  `catalog.maps.thumbnail_uri` (models.py:100).

**Backend GET** (`backend/app/modules/catalog/maps/router.py`):
- Route: `GET /{map_id}/thumbnail/` at **line 1605**
- Serves bytes from storage; cache-control is `public, max-age=3600` for public maps.

### Path A vs Path B analysis

**Path A: new `og_image_uri` column + separate PUT/GET OG-image routes**

- Add `og_image_uri: Mapped[str | None]` to the `Map` model (`models.py` after line 100)
- New Alembic migration (`0024_maps_og_image_uri.py`)
- New `ThumbnailUploadRequest`-shaped schema for the OG image — or reuse
  `ThumbnailUploadRequest` but with `max_length` raised to ~2_500_000 (a 1200x630 JPEG
  at quality 0.85 is ~150-400KB as base64 = ~200-540KB base64 string).
- New routes: `PUT /{map_id}/og-image/` and `GET /{map_id}/og-image/`
- Frontend: second `doCapture`-style function at 1200x630, called after the existing
  400x250 capture during `handleSave` (or in the same `doCapture` by parameterizing width/height)
- Storage key: `maps/og-images/{map_id}.jpg`

**Path B: server-side resize from native canvas capture**

- Frontend sends the native canvas at its original size (~1440x900 device pixels or
  whatever the browser window provides, typically 2-4x DPR on retina)
- Backend receives the raw image bytes, uses Pillow to resize to BOTH 400x250 AND 1200x630
- One HTTP upload instead of two; no second frontend capture
- BUT: the `ThumbnailUploadRequest.data_uri` has a hard `max_length=100_000` (100KB)
  constraint at the Pydantic schema level (`schemas.py:954`). The native canvas at
  1440x900 JPEG encodes to 200-600KB base64 — well over the 100KB cap.
  To implement Path B, the thumbnail route's schema must be relaxed, or a new route
  accepting multipart/raw binary (not base64 data URI) must be added.
- This means Path B **still requires a new route** (to accept the larger payload),
  plus the server-side Pillow resize logic. The simplicity win of "one capture" is
  partially offset by the need to modify or replace the existing thumbnail pipeline.

**Recommendation: Path A.**

Rationale:
1. The existing `PUT /thumbnail/` route has a hard 100KB Pydantic `max_length` on the
   `data_uri` field (`schemas.py:954`). Relaxing it changes the existing contract for
   existing callers. Path A adds a parallel route without touching the existing schema.
2. The existing thumbnail capture (`doCapture`) is a well-understood function with
   debouncing, StrictMode guards, and test coverage. Parameterizing it (or duplicating
   it at 1200x630) is a smaller blast radius than refactoring the entire upload path.
3. Pillow is already installed (`Pillow>=12.2.0` in `pyproject.toml`) — nothing new
   to install; the PIL validation block on the thumbnail route (`router.py:1565-1583`)
   already demonstrates the correct import pattern.
4. The two captures can share a single render event: after `map.triggerRepaint()` +
   `map.once('render', onRender)`, the `onRender` callback can call `offscreen.toDataURL`
   twice at different target dimensions in one pass. Total cost: 1 repaint, 2 uploads.
5. Path A produces a clean separation: thumbnail (400x250, fast, shown in map listings)
   vs. OG image (1200x630, larger, only needed for social sharing). If the user never
   shares, the OG image is never captured.

### Path A Integration Points

**Backend — new column:**
- File: `backend/app/modules/catalog/maps/models.py` — add after line 100:
  ```python
  og_image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
  ```
- Migration: `backend/alembic/versions/0024_maps_og_image_uri.py`
  (next in sequence after `0023_geolens_readonly_role.py`)
  ```python
  op.add_column("maps", sa.Column("og_image_uri", sa.Text(), nullable=True), schema="catalog")
  ```

**Backend — new schema:**
- File: `backend/app/modules/catalog/maps/schemas.py` — add after `ThumbnailUploadRequest`:
  ```python
  class OgImageUploadRequest(BaseModel):
      """JSON body for PUT /maps/{map_id}/og-image/.
      max_length covers a 1200x630 JPEG at quality 0.85 encoded as base64 (~540KB string).
      """
      data_uri: str = Field(min_length=22, max_length=750_000)
  ```
  (750KB base64 ceiling = ~562KB decoded bytes = generous for 1200x630 JPEG)

**Backend — new routes (add to router.py after the existing thumbnail routes at line ~1641):**
- `PUT /{map_id}/og-image/` — mirrors the thumbnail upload handler; same PIL verify,
  same `storage.put()`, sets `map_obj.og_image_uri = f"maps/og-images/{map_id}.jpg"`
- `GET /{map_id}/og-image/` — mirrors `get_thumbnail`; reads `map_obj.og_image_uri`;
  same `_check_map_read_access`; cache-control `public, max-age=86400` for public maps
  (OG images change less frequently than thumbnails)

**Backend — `_build_map_response` (router.py:339-373):**
Add `og_image_url = f"/maps/{map_obj.id}/og-image/" if map_obj.og_image_uri else None`
and include in `MapResponse`. Update `MapResponse` schema to include `og_image_url: str | None`.

**Backend — meta-card route:**
```python
@router.get("/shared/{token}/card", response_class=HTMLResponse, include_in_schema=False)
async def shared_map_card_endpoint(token: str, db: AsyncSession = Depends(get_db)):
    from app.modules.catalog.maps.service_public import _validate_share_token
    from app.modules.catalog.maps.service_crud import get_map
    token_obj = await _validate_share_token(db, token)
    if not token_obj or isinstance(token_obj, str):
        raise HTTPException(status_code=404, detail="Share link not found")
    map_obj = await get_map(db, token_obj.map_id)
    if map_obj is None or map_obj.visibility != "public":
        raise HTTPException(status_code=404, detail="Share link not found")
    # Determine OG image URL
    if map_obj.og_image_uri:
        image_url = f"/api/maps/{map_obj.id}/og-image/"
    elif map_obj.thumbnail_uri:
        image_url = f"/api/maps/{map_obj.id}/thumbnail/"
    else:
        image_url = "/og-image.png"   # site-level fallback
    title = map_obj.name or "GeoLens Map"
    description = map_obj.description or "View this map on GeoLens"
    viewer_url = f"/m/{token}"
    html = f"""<!doctype html>
<html><head>
<meta charset="UTF-8">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{image_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{image_url}">
<meta http-equiv="refresh" content="0;url={viewer_url}">
</head><body></body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "public, max-age=300"})
```
Note: title/description must be HTML-escaped in the real implementation
(use `html.escape()` from the stdlib). The snippet above is pseudocode for planning.

**Frontend — OG image capture:**
- File: `frontend/src/components/builder/hooks/use-builder-save.ts`
- In `doCapture()` (starting line 29), after the existing 400x250 JPEG is uploaded,
  add a second capture at 1200x630 using a separate offscreen canvas, then call a new
  `uploadOgImage(mapId, dataUri)` API function (mirrors `uploadThumbnail` at `maps.ts:282`
  but posts to `/maps/{mapId}/og-image/`).
  The two captures share the same `onRender` callback and the same `srcCanvas` reference —
  only the offscreen canvas dimensions change. Zero additional repaints.

**Frontend — share card URL:**
- File: `frontend/src/components/builder/SharePanel.tsx`
- The card URL is `/api/maps/shared/{rawShareToken}/card` (note: proxied through nginx's
  `/api/` block to the FastAPI backend — `nginx.conf:103-120`).
- Add a secondary "Copy social card link" affordance or hint text explaining that the
  `/card` URL is for social sharing. The primary "Copy Link" continues to emit the
  `/m/token` URL for normal viewer use.
- Alternative (simpler): replace the primary share URL with the `/card` URL. The
  `<meta http-equiv="refresh">` in the card HTML redirects human visitors to `/m/:token`
  immediately, so UX is identical. The risk: the 0-second refresh may be jarring in
  some browsers or if the redirect is blocked. Prefer the two-URL approach.

**OpenAPI/SDK refresh flag:** The new routes (`PUT /og-image/`, `GET /og-image/`) and
the updated `MapResponse` schema (`og_image_url` field) ARE in the OpenAPI schema. These
changes require `make openapi` + `npm run fetch-openapi` in Phase 1143 per the dual-snapshot
refresh order (MEMORY.md: `[OpenAPI dual-snapshot refresh order]`).

---

## SHARE-10 — SharePanel Font Weights

### Current state (verified)

All font-weight occurrences in `SharePanel.tsx` are `font-medium`. No `font-semibold`
or `font-bold` found. The file uses `font-mono` for code snippets (not a weight class).

**Sites using `font-medium`** (all verified by grep):

| Line | Context | Size | Role |
|------|---------|------|------|
| 315 | Settings toggle trigger | `text-xs` | Secondary label |
| 336 | Expiration label | `text-xs` | Secondary label |
| 389 | Domain restriction label | `text-xs` | Secondary label |
| 883 | Visibility section header | `text-sm` | **Section header** |
| 905 | Visibility option title | `text-sm` | **Option title** |
| 930 | "Share Link" section header | `text-sm` | **Section header** |
| 1039 | "Embed Code" section header | `text-sm` | **Section header** |
| 1102 | Customize params label | `text-xs` | Secondary label |

**Weight analysis:** Only ONE distinct weight class exists today: `font-medium` (500).
The non-weight text elements use Tailwind's default (no explicit weight = `font-normal`
= 400). Lines 349, 379, 549, 590, 596, 854, 906, etc. have `text-xs`/`text-sm` with no
`font-*` class = normal weight.

So the current state is **TWO effective weights** (normal/400 implicitly + medium/500
explicitly) — not three as the v1030 audit finding F2 characterized. The CONTEXT.md
phrasing "3 across ~5 sites" may have referred to an earlier version of the file.

**Conclusion: SHARE-10 is already at ≤2 effective weights.**

However, the UI-SPEC "max-2" rule specifically addresses EXPLICIT weight classes in the
component tree — not implicit defaults. Eight explicit `font-medium` usages across a
single component is the audited finding. The ≤2 conformance means:

- **Option A (no change needed):** If the spec counts effective weights (implicit normal
  + explicit medium = 2), the file already conforms. Write a regression comment and close.
- **Option B (make the hierarchy explicit):** Promote section headers (lines 883, 905,
  930, 1039) to `font-semibold` and keep secondary labels (315, 336, 389, 1102) as
  `font-medium`. Result: 2 explicit weights (`font-medium` for small labels +
  `font-semibold` for sm-size section headers), 0 sites using `font-normal` explicitly.
  This creates a clear visual hierarchy without adding a third weight.

**Recommendation: Option B.** The v1030 audit flagged F2 as "font-medium hygiene" —
the intent was to create a clearer 2-weight system with explicit hierarchy, not just
to reduce the count. Promoting the 4 section-header sites from `font-medium` to
`font-semibold` produces the intended visual distinction.

**Exact edits:**

| Line | Before | After |
|------|--------|-------|
| 883 | `text-sm font-medium` | `text-sm font-semibold` |
| 905 | `text-sm font-medium` | `text-sm font-semibold` |
| 930 | `text-sm font-medium` | `text-sm font-semibold` |
| 1039 | `text-sm font-medium` | `text-sm font-semibold` |

Lines 315, 336, 389, 1102 stay as `font-medium` (secondary labels).

4 single-token class changes, no behavior change, no i18n impact.

---

## Recommended Approach Summary

### SHARE-08 Crawler Meta

**Mechanism:** `GET /api/maps/shared/{token}/card` (new FastAPI endpoint in `router.py`)
- Returns `HTMLResponse` with server-rendered OG/Twitter meta tags
- `<meta http-equiv="refresh" content="0;url=/m/{token}">` for human visitors
- Does NOT change nginx config; does NOT change the `/m/:token` SPA flow
- `include_in_schema=False` — not in OpenAPI, no SDK refresh needed for this route alone
- Requires a "Copy social card link" affordance (or URL hint) in SharePanel

### SHARE-08 Image — Path A

**Migration:** `0024_maps_og_image_uri.py` — adds `catalog.maps.og_image_uri TEXT NULL`

**Backend integration points:**
- `backend/app/modules/catalog/maps/models.py`: add `og_image_uri` column (after line 100)
- `backend/app/modules/catalog/maps/schemas.py`: add `OgImageUploadRequest` (after line 954); update `MapResponse` with `og_image_url: str | None`
- `backend/app/modules/catalog/maps/router.py`: add `PUT /{map_id}/og-image/` (after line 1641) and `GET /{map_id}/og-image/` (after the PUT); update `_build_map_response` (line 339) to include `og_image_url`

**Frontend integration points:**
- `frontend/src/components/builder/hooks/use-builder-save.ts`: extend `doCapture()` (line 29) to capture a second 1200x630 JPEG in the same `onRender` callback and call `uploadOgImage()`
- `frontend/src/api/maps.ts`: add `uploadOgImage(mapId, dataUri)` function (mirrors `uploadThumbnail` at line 282)
- `frontend/src/components/builder/SharePanel.tsx`: add card URL affordance; `getShareCardUrl()` returns `/api/maps/shared/{rawShareToken}/card`

**Phase 1143 OpenAPI/SDK refresh flag:** YES — `PUT /og-image/`, `GET /og-image/`, and
updated `MapResponse.og_image_url` field all appear in the OpenAPI schema. Phase 1143
must run `make openapi` + `npm run fetch-openapi` before the close-gate.

### SHARE-10

4 targeted class changes in `frontend/src/components/builder/SharePanel.tsx`:
- Lines 883, 905, 930, 1039: `font-medium` → `font-semibold`
- Lines 315, 336, 389, 1102: unchanged (`font-medium` stays)

---

## Architecture Patterns

### Existing pattern: thumbnail PUT (reference implementation for OG image)

Path A's new `PUT /og-image/` route is structurally identical to `PUT /thumbnail/`
(`router.py:1504-1602`). The planner should use the thumbnail handler as the
reference implementation and clone it, changing only:
- Route path: `/og-image/`
- Storage key prefix: `maps/og-images/` instead of `maps/thumbnails/`
- Column update: `map_obj.og_image_uri = storage_key` instead of `map_obj.thumbnail_uri`
- `max_length` on the request schema: `750_000` (not `100_000`)

The PIL image verify block, storage error handling, ownership check, and commit
sequence are all reuse-as-is.

### Existing pattern: thumbnail GET (reference for OG image GET)

`GET /thumbnail/` (`router.py:1605-1641`) is the reference for `GET /og-image/`.
The only changes: read `map_obj.og_image_uri`, use `maps/og-images/` key convention.
Cache-control can be more aggressive (`max-age=86400`) since OG images change less
frequently than thumbnails.

### Frontend capture pattern: two-size capture in one render callback

The `doCapture()` function at line 29 already creates an offscreen canvas and calls
`toDataURL` once. Extending it to produce two crops at different sizes:

```typescript
function doCapture(map: MaplibreMap, mapId: string, queryClient: ...) {
  const onRender = () => {
    try {
      const srcCanvas = map.getCanvas();
      // Existing: 400x250 thumbnail
      const thumb = cropResize(srcCanvas, 400, 250);
      uploadThumbnail(mapId, thumb.toDataURL('image/jpeg', 0.7))
        .then(...).catch(...);
      // New: 1200x630 OG image
      const og = cropResize(srcCanvas, 1200, 630);
      uploadOgImage(mapId, og.toDataURL('image/jpeg', 0.85))
        .catch(...); // silent failure OK
    } catch (err) { ... }
  };
  map.once('render', onRender);
  map.triggerRepaint();
}
```

Extract the crop-resize logic into a small helper `cropResize(srcCanvas, w, h): HTMLCanvasElement`
to avoid duplication (already implicit in the existing code at lines 40-54).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Image resize on backend | Custom pixel math | Pillow (already installed: `Pillow>=12.2.0`) |
| HTML escaping in meta route | Custom replace | `html.escape()` from Python stdlib |
| OG image storage | Custom file system | Existing `StorageProvider.put()` / `get()` |
| Meta tag injection in SPA | Helmet / client inject | Backend route (crawlers don't run JS) |

---

## Common Pitfalls

### Pitfall 1: Absolute vs relative OG image URLs

**What goes wrong:** OG `<meta>` `content` attributes with relative URLs (`/api/maps/...`)
are NOT resolved by all crawlers. Twitter/X in particular requires a fully-qualified URL.

**Prevention:** The backend card route must emit absolute URLs. The route receives the
`Request` object and can use `str(request.base_url)` to build the absolute origin.
Pattern: `f"{str(request.base_url).rstrip('/')}/api/maps/{map_obj.id}/og-image/"`.

Add `request: Request` as a parameter to `shared_map_card_endpoint`.

### Pitfall 2: OG image requires public visibility check

**What goes wrong:** If the OG image is served from `GET /og-image/` with the same
`_check_map_read_access` logic as thumbnails, and a crawler hits it anonymously, it will
get a 404 for non-public maps — resulting in a broken image in the social card.

**Prevention:** The card route only emits an `og:image` if the map is public
(already the case: `map_obj.visibility != "public"` returns 404 in the card route).
The `GET /og-image/` serve route must use the same `public, max-age=86400` cache-control
for public maps so CDN caches serve it to crawlers without auth.

### Pitfall 3: HTML injection in the meta card route

**What goes wrong:** Map `name` or `description` containing `"` or `<` characters breaks
the HTML attribute values in the meta tags.

**Prevention:** `html.escape(title)` and `html.escape(description)` before interpolation.
This is a one-liner; do not omit it.

### Pitfall 4: Base64 size limit on the OG image upload

**What goes wrong:** A 1200x630 JPEG at quality 0.85 encodes to ~150-400KB. The base64
data URI for a 400KB image is ~540KB. The existing `ThumbnailUploadRequest` has a
`max_length=100_000` Pydantic constraint that would reject this.

**Prevention:** Path A uses a new `OgImageUploadRequest` with `max_length=750_000`.
Do NOT relax `ThumbnailUploadRequest.max_length` — that would break the existing
tested contract.

### Pitfall 5: doCapture shares one render event — don't double-trigger

**What goes wrong:** Calling `map.triggerRepaint()` twice (once for thumbnail, once for
OG image) causes two render events, two canvas reads, and potential race conditions with
the save debounce.

**Prevention:** Both captures must be done inside ONE `onRender` callback registered via
`map.once('render', onRender)` with ONE `triggerRepaint()` call. The two offscreen canvas
operations (`cropResize`) happen synchronously in the same callback. Only the uploads
are async (fire-and-forget).

### Pitfall 6: Meta-card route must be declared BEFORE `/{map_id}` catch-all in router

**What goes wrong:** FastAPI matches routes in declaration order. If `GET /{map_id}` is
declared before `GET /shared/{token}/card`, FastAPI may interpret `shared` as a
`map_id` UUID — but `shared` is not a UUID, so it would raise a 422 validation error.

**Prevention:** Verify registration order in `router.py`. `GET /shared/{token}` is
already registered at line 484 BEFORE `GET /{map_id}` at line 773. The new
`GET /shared/{token}/card` should be registered in the same vicinity (near line 484),
which is already before `/{map_id}`.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (backend), vitest (frontend) |
| Config file | `backend/pyproject.toml` [tool.pytest.ini_options], `frontend/vitest.config.ts` |
| Quick run command (backend) | `cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_maps_og_image.py -x` |
| Full suite command | `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4` |
| Frontend quick run | `cd frontend && npm run typecheck && npm run test -- SharePanel` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| SHARE-08-backend | `PUT /og-image/` stores image; `GET /og-image/` serves it; 404 if none | unit/integration | `pytest tests/test_maps_og_image.py -x` |
| SHARE-08-card | `GET /shared/{token}/card` returns HTML with og:image/og:title meta | unit | same |
| SHARE-08-frontend | `doCapture` uploads both 400x250 and 1200x630; `uploadOgImage` called | unit | `vitest run use-builder-save` |
| SHARE-10 | SharePanel renders ≤2 explicit font weights | snapshot/manual | `vitest run SharePanel` + visual check |

### Wave 0 Gaps

- [ ] `backend/tests/test_maps_og_image.py` — covers SHARE-08 backend routes (new file)
- [ ] Verify `SharePanel.test.tsx` snapshot passes after SHARE-10 class changes

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Pydantic `max_length` on `OgImageUploadRequest.data_uri`; PIL `img.verify()` |
| V4 Access Control | yes | `check_map_ownership` on PUT; `_check_map_read_access` on GET; card route public-only |
| V6 Cryptography | no | OG image is not encrypted — same as thumbnail |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| HTML injection in meta tags | Tampering | `html.escape()` on map name/description |
| Oversize image upload DoS | DoS | Pydantic `max_length=750_000` rejects before decoding |
| Image content masquerading | Spoofing | PIL `img.verify()` (already proven on thumbnail route) |
| Cache poisoning via public OG image | Tampering | OG image URL keyed by `map_id` UUID (not by token); revoked tokens still point to the same image |

---

## Assumptions Log

> All claims in this research were verified against the live codebase.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pillow version is `>=12.2.0` and available in the backend image | Standard Stack | Resize path may need a different API; unlikely given explicit pyproject.toml entry |
| A2 | Social crawlers (Slack, Twitter) follow `<meta http-equiv="refresh">` and still read OG tags from the redirect source | SHARE-08 mechanism | If they don't follow refresh, the canonical share URL MUST be the `/card` URL, not `/m/token` — both options are addressed in the plan |

---

## Open Questions

1. **Should the primary "Copy Link" button in SharePanel emit the `/card` URL or the
   `/m/` URL?**
   - What we know: `/card` gives crawlers the OG meta; `/m/` gives users the SPA.
   - What's unclear: user expectation when pasting in Slack — do they want the link
     to open the SPA directly (prefer `/m/`) or show a rich preview (prefer `/card`)?
   - Recommendation: Keep "Copy Link" as `/m/token` (existing behavior, no regression).
     Add a distinct "Copy social link" affordance for the `/card` URL. This is a
     one-line addition to SharePanel and a clean separation of concerns.

2. **Should the OG image be captured automatically on every save, or only when the
   user explicitly opts in via SharePanel?**
   - What we know: the thumbnail is captured automatically on every save
     (`use-builder-save.ts:507`). The OG image is 3x larger and only needed for sharing.
   - Recommendation: Capture the OG image on every save alongside the thumbnail
     (same `doCapture` call, no extra repaint). The incremental cost is one more
     offscreen canvas + one more HTTP PUT per save. This means the OG image is always
     ready when the user generates a share link.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Pillow | OG image validation (backend) | yes | >=12.2.0 (pyproject.toml) | — |
| html.escape | HTML injection prevention | yes | Python stdlib | — |
| StorageProvider | OG image storage | yes | same as thumbnail | — |

---

## Sources

### Primary (HIGH confidence — verified against live files)

- `backend/app/modules/catalog/maps/router.py` — thumbnail PUT (line 1504), thumbnail GET (line 1605), `_build_map_response` (line 339), `/shared/{token}` endpoint (line 484), route ordering
- `backend/app/modules/catalog/maps/models.py` — `Map.thumbnail_uri` column (line 100), `Map` model schema
- `backend/app/modules/catalog/maps/schemas.py` — `ThumbnailUploadRequest` (line 933), `max_length=100_000` constraint (line 954)
- `backend/app/modules/catalog/maps/service_public.py` — `_validate_share_token`, `get_shared_map`, no HTMLResponse
- `backend/pyproject.toml` — `Pillow>=12.2.0`
- `frontend/nginx.conf` — `/m/` location block (line 154), SPA `try_files` fallthrough
- `frontend/index.html` — static OG tags (lines 32-38)
- `frontend/src/App.tsx` — `/m/:token` route → `PublicViewerPage` (line 51)
- `frontend/src/components/builder/hooks/use-builder-save.ts` — `doCapture` at line 29, `thumbW=400`/`thumbH=250` at lines 33-34, `captureThumbnail` call at line 507
- `frontend/src/components/builder/SharePanel.tsx` — `font-medium` usages (lines 315, 336, 389, 883, 905, 930, 1039, 1102); `getShareUrl()` (line 806); share URL shape (line 808)
- `backend/app/api/router.py` — maps router registration (line 72)
- `backend/alembic/versions/` — latest migration `0023_geolens_readonly_role.py`

---

## Metadata

**Confidence breakdown:**
- Crawler-meta mechanism: HIGH — confirmed by nginx config + index.html static inspection + no HTMLResponse in backend
- Path A rationale: HIGH — `max_length=100_000` verified in schemas.py:954; Pillow verified in pyproject.toml
- SHARE-10 weight count: HIGH — exhaustive grep of SharePanel.tsx confirms only `font-medium` explicit
- Migration numbering: HIGH — `0023` is confirmed latest, `0024` is correct next

**Research date:** 2026-05-28
**Valid until:** 2026-07-01 (stable stack, low churn)
