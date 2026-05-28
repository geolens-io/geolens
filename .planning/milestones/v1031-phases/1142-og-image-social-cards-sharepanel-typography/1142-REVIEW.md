---
phase: 1142-og-image-social-cards-sharepanel-typography
reviewed: 2026-05-28T18:00:00Z
depth: deep
files_reviewed: 10
files_reviewed_list:
  - backend/alembic/versions/0024_maps_og_image_uri.py
  - backend/app/modules/catalog/maps/models.py
  - backend/app/modules/catalog/maps/schemas.py
  - backend/app/modules/catalog/maps/router.py
  - backend/tests/test_maps_og_image.py
  - frontend/src/api/maps.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - frontend/src/components/builder/SharePanel.tsx
  - frontend/src/components/builder/__tests__/SharePanel.test.tsx
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 1142: Code Review Report

**Reviewed:** 2026-05-28
**Depth:** deep
**Files Reviewed:** 10
**Status:** issues_found (2 warnings, 2 info — no blockers)

## Summary

Phase 1142 adds a public-facing OG/Twitter social-card HTML route (`GET /shared/{token}/card`), an authenticated OG image upload/serve pipeline (`PUT`/`GET /maps/{id}/og-image/`), Alembic migration 0024, and SharePanel typography promotion. The core security controls are sound: `html.escape()` is applied to the user-controlled title and description before HTML attribute injection, access control is correct (invalid/expired/private → 404 with no data leak), the upload route requires owner auth and PIL image verification, and the Pydantic cap (750KB) stops oversized payloads.

Two warnings were identified. The more significant is a deviation from the project's established SEC-05 URL-validation pattern: the `/card` route builds its absolute `og:image` URL using raw `request.base_url` (influenced by the HTTP Host header, which nginx passes through unfiltered as `$http_host`) rather than the project's `get_public_api_url()` helper, which applies CORS-allowlist validation. This matters both for URL correctness in non-standard deployments and for defense-in-depth. The second warning is a factually incorrect aspect-ratio claim in a docstring that could mislead future maintainers into assuming the two target sizes share a common crop ratio.

No blockers. The test coverage for the security-critical paths (T-1142-01, T-1142-02) is adequate. SHARE-10 typography changes are correct (4 sites promoted to `font-semibold`, 4 secondary labels remain `font-medium`, 0 `font-bold`).

---

## Warnings

### WR-01: `og:image` URL built from raw `request.base_url` instead of project's validated URL resolver

**File:** `backend/app/modules/catalog/maps/router.py:542`
**Issue:** The `/card` endpoint constructs the absolute `og:image` URL with:
```python
base = str(request.base_url).rstrip("/")
```
`request.base_url` in Starlette is derived from the HTTP Host header. Nginx is configured with `proxy_set_header Host $http_host` (nginx.conf:72,108), which forwards the client-supplied Host value verbatim to the backend. An external attacker can send a crafted Host header (e.g., `Host: evil.com`) and cause the card route to emit `og:image content="http://evil.com/api/maps/{id}/og-image/"`. This is an OG metadata URL hijack: the social card's preview image becomes attacker-controlled.

The project already has a hardened resolver in `backend/app/core/public_urls.py` — `get_public_api_url(db, request=request)` — that: (1) prefers the admin-configured `PUBLIC_API_URL` if set; (2) otherwise validates the request-derived origin against `CORS_ALLOWED_ORIGINS` (SEC-05 at `public_urls.py:106-115`). The card route bypasses both of these checks.

Additionally, `image_url` (which carries `base`) is interpolated into the HTML `content="..."` attribute without `html.escape()`. The URL characters produced by UUID + fixed path segments are safe, but a malicious Host value containing `"` or `>` would break the attribute boundary without escaping. These are independent gaps that each call for the same fix.

**Fix:**
```python
# At top of shared_map_card_endpoint, replace:
#   base = str(request.base_url).rstrip("/")
# with the project-standard resolver (db is already a parameter):
from app.core.public_urls import get_public_api_url
base = await get_public_api_url(db, request=request)
base = base.rstrip("/")

# Also html.escape the assembled image_url before interpolation:
image_url = html.escape(image_url)  # defense-in-depth on the URL value
```
The function signature already has `request: Request` and `db: AsyncSession = Depends(get_db)` so this is a drop-in change. When `PUBLIC_API_URL` is set in production, `get_public_api_url` returns that value directly and request headers are never consulted. When it is not set, the CORS allowlist gate applies.

---

### WR-02: Inaccurate aspect-ratio claim in `cropResize` docstring will mislead maintainers

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:25`
**Issue:** The docstring for `cropResize` states:
```
 *  target (400×250 thumbnail, 1200×630 OG image — both share the same 1.6
 *  aspect ratio)
```
`400 / 250 = 1.6`. `1200 / 630 = 1.905` (approximately 40:21). These are different aspect ratios. The function implementation is correct — it computes `targetRatio = targetW / targetH` from its arguments so it works for any pair — but a maintainer reading the comment who wants to add a third capture size and believes the function is optimised only for "16:10 targets" may make a wrong inference. The comment also understates the generality of the helper.

**Fix:** Remove the aspect-ratio equality claim:
```typescript
/** Center-crop `srcCanvas` to the given target dimensions and return the
 *  resulting offscreen canvas. Crops from the center without distortion
 *  (letterbox / pillarbox math). Supports any target aspect ratio.
 *
 *  SHARE-08 (Phase 1142): extracted from the former inline doCapture crop block
 *  to allow two crops (400×250 thumbnail, 1200×630 OG image) to share one
 *  render event with a single triggerRepaint(). */
```

---

## Info

### IN-01: Inline imports (`base64`, `BytesIO`, `PIL`, `_validate_share_token`) inside handler bodies

**File:** `backend/app/modules/catalog/maps/router.py:1765,1800,1802,523`
**Issue:** The `upload_og_image` handler performs deferred imports inside the async function body:
```python
import base64                              # line 1765
from io import BytesIO                     # line 1800
from PIL import Image, UnidentifiedImageError  # line 1802
```
And the card handler:
```python
from app.modules.catalog.maps.service_public import _validate_share_token  # line 523
```
Python's import machinery caches modules in `sys.modules` after the first load, so these are not expensive at runtime. However, they are inconsistent with the module-level imports at lines 1–65 (`html`, `uuid`, `HTMLResponse`, etc.) and duplicate the pattern already present in the `upload_thumbnail` handler (pre-existing). The `_validate_share_token` import buried inside the handler is particularly hard to grep when auditing the dependency graph.

**Fix:** Move all four to the top of the file with the existing imports. The `service_public` circular-import risk (if any) was already resolved when the existing shared-map endpoint imports the same module at the top level in `service_public.py`.

---

### IN-02: Test assertion for HTML-escaping has a weak secondary branch

**File:** `backend/tests/test_maps_og_image.py:363`
**Issue:** `test_card_route_escapes_html_in_title` asserts:
```python
assert "&lt;script&gt;" in body or "Evil" in body
```
The primary assertion `assert "<script>" not in body` (line 359) is the critical check. The secondary `or "Evil" in body` is too permissive: if a future regression caused `html.escape()` to silently strip the `<script>` tag entirely (returning only `Evil "> ` without the literal `<script>`) rather than escaping it, this branch would still pass — a false PASS on an escaping regression.

**Fix:** Make the positive assertion unconditional:
```python
# Remove the 'or "Evil" in body' fallback:
assert "&lt;script&gt;" in body, (
    "Expected HTML-escaped <script> tag in card HTML; title was not properly escaped"
)
```

---

_Reviewed: 2026-05-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
