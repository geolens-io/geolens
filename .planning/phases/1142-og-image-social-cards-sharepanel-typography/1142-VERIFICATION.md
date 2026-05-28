---
phase: 1142-og-image-social-cards-sharepanel-typography
verified: 2026-05-28T20:55:00Z
status: human_needed
score: 9/9
overrides_applied: 0
deferred:
  - truth: "OpenAPI snapshot and Python/TypeScript SDK regenerated for og-image routes and MapResponse.og_image_url"
    addressed_in: "Phase 1143"
    evidence: "Phase 1143 SC-4: 'OpenAPI snapshot and Python/TypeScript SDK artifacts are regenerated where backend routes or schemas changed (e.g., OG-image routes under Path A)'"
human_verification:
  - test: "Fetch /api/maps/shared/{token}/card for a saved, publicly-shared map and assert og:image + twitter:card meta present and the og:image content is an absolute URL that resolves with a 200"
    expected: "Response 200 text/html; body contains property=\"og:image\" and name=\"twitter:card\" with content=\"summary_large_image\"; og:image URL starts with http and returns a valid image response"
    why_human: "Requires a live stack with a real shared map token; Playwright MCP can fetch the /card route and assert meta tags via DOM or regex — not verifiable by offline grep"
  - test: "After a map save on the live builder, GET /api/maps/{id}/og-image/ and verify the returned image is a valid JPEG at or near 1200x630"
    expected: "Response 200 image/jpeg; image dimensions 1200x630 (or close to it given center-crop from the live WebGL canvas); non-zero file size"
    why_human: "Live WebGL canvas capture cannot be exercised headlessly; requires Playwright MCP to trigger a save, wait for the OG upload, then assert the GET endpoint returns a valid image"
  - test: "Real-client social unfurl spot-check: paste the /card URL into a social preview tool (e.g. Twitter/X Card Validator, LinkedIn post inspector, or OpenGraph.io) and confirm the 1200x630 preview image, title, and description render correctly"
    expected: "Card previewer shows the map thumbnail at 1200x630, the map title, and the map description — no 'card not found' or fallback generic card"
    why_human: "Requires a 3rd-party crawler with network access to the live public URL; cannot be automated in the development environment"
---

# Phase 1142: OG-Image Social Cards & SharePanel Typography — Verification Report

**Phase Goal:** Shared map links emit valid OG/Twitter card meta backed by a 1200x630 preview image, and SharePanel uses <=2 font weights.
**Verified:** 2026-05-28T20:55:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | GET /api/maps/shared/{token}/card returns text/html with og:image, og:title, og:description, twitter:card=summary_large_image meta for a publicly-shared map | VERIFIED | `shared_map_card_endpoint` at router.py:499; `test_card_route_public_map_emits_og_meta` passes; returns 200 text/html with all required meta tags |
| 2 | The /card route returns 404 for private maps, invalid tokens, and expired/revoked tokens (T-1142-02) | VERIFIED | router.py:531-543: `_validate_share_token` + `isinstance(token_obj, str)` + `visibility != "public"` → 404; 3 BLOCKING security tests pass (`test_card_route_404_for_private_map`, `_invalid_token`, `_expired_token`) |
| 3 | A malicious map title containing quotes/markup is HTML-escaped in the rendered /card meta (T-1142-01) | VERIFIED | router.py:565-566: `html.escape()` on name + description; router.py:562: `html.escape(image_url, quote=True)` defense-in-depth; `test_card_route_escapes_html_in_title` passes with unconditional `assert "&lt;script&gt;" in body` (IN-02 weak fallback removed) |
| 4 | og:image and twitter:image content are absolute URLs (scheme+host), not relative paths | VERIFIED | router.py:549: `base = await get_public_api_url(db, request=request)` (WR-01 fix applied — uses CORS-validated URL helper, not raw `request.base_url`); `test_card_route_og_image_url_is_absolute` passes |
| 5 | PUT /maps/{id}/og-image/ stores a 1200x630-class JPEG (payload up to ~750KB base64) for the map owner only; GET /maps/{id}/og-image/ serves it back; 404 when none uploaded | VERIFIED | router.py:1751-1879: `upload_og_image` (owner-only auth, PIL verify, 750KB cap via OgImageUploadRequest, storage key maps/og-images/{id}.ext) + `get_og_image` (404 when og_image_uri is None, public, max-age=86400); 7 integration tests pass |
| 6 | Existing PUT/GET /maps/{id}/thumbnail/ routes and ThumbnailUploadRequest contract are unchanged | VERIFIED | schemas.py: `ThumbnailUploadRequest.data_uri max_length=100_000` unchanged; `test_thumbnail_upload_request_max_length_unchanged` passes |
| 7 | Alembic migration 0024 adds catalog.maps.og_image_uri TEXT NULL and downgrades cleanly | VERIFIED | `backend/alembic/versions/0024_maps_og_image_uri.py`: revision="0024", down_revision="0023_geolens_readonly_role"; upgrade adds TEXT NULL, downgrade drops; 22 tests run through migration on each test session pass |
| 8 | Saving a map captures a 1200x630 OG image in the same render pass as the 400x250 thumbnail (one triggerRepaint) and uploads it via PUT /maps/{id}/og-image/ | VERIFIED | use-builder-save.ts:74-84: `cropResize(srcCanvas, 1200, 630)` + `uploadOgImage(...)` inside the existing single `onRender` callback; single `map.triggerRepaint()` at line 92; SHARE-08 vitest asserts `triggerRepaint` called exactly once AND both uploads called once |
| 9 | SharePanel renders exactly 2 explicit font weights: font-semibold for 4 section headers, font-medium for secondary labels (SHARE-10) | VERIFIED | SharePanel.tsx: `git grep font-semibold` returns 4 lines (898, 920, 945, 1054); `git grep font-bold` returns 0 lines; 4 `font-medium` sites at 315, 336, 389, 1117 retained; SharePanel.test.tsx SHARE-10 describe asserts semiboldEls.length > 0 and boldEls.length === 0 |

**Score: 9/9 truths verified**

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | OpenAPI snapshot and Python/TypeScript SDK regenerated for og-image routes and MapResponse.og_image_url | Phase 1143 | Phase 1143 SC-4: "OpenAPI snapshot and Python/TypeScript SDK artifacts are regenerated where backend routes or schemas changed (e.g., OG-image routes under Path A)" |

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/alembic/versions/0024_maps_og_image_uri.py` | og_image_uri column migration | VERIFIED | revision="0024", down_revision="0023_geolens_readonly_role"; adds TEXT NULL, drops in downgrade |
| `backend/app/modules/catalog/maps/router.py` | card route + og-image PUT/GET + MapResponse.og_image_url wiring | VERIFIED | shared_map_card_endpoint at line 494 (before /{map_id} catch-all at 881); upload_og_image at 1751; get_og_image at 1838; _build_map_response at 355 |
| `backend/app/modules/catalog/maps/schemas.py` | OgImageUploadRequest + MapResponse.og_image_url | VERIFIED | OgImageUploadRequest at line 958 (max_length=750_000); MapResponse.og_image_url at line 701 |
| `backend/tests/test_maps_og_image.py` | card route + og-image route + escaping + access-control + migration tests | VERIFIED | 22 tests, all passing (confirmed by pytest -n 4 run) |
| `frontend/src/api/maps.ts` | uploadOgImage(mapId, dataUri) API function | VERIFIED | line 289: PUT to `/maps/${mapId}/og-image/`; mirrors uploadThumbnail shape |
| `frontend/src/components/builder/hooks/use-builder-save.ts` | 1200x630 capture + uploadOgImage inside doCapture's onRender | VERIFIED | cropResize helper at line 30; OG capture at lines 82-84; single triggerRepaint at line 92 |
| `frontend/src/components/builder/SharePanel.tsx` | getShareCardUrl() (/card) + font-semibold headers | VERIFIED | getShareCardUrl at line 819; handleCopyShareLink uses it at 835; 4 font-semibold headers, 0 font-bold |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| GET /api/maps/shared/{token}/card | _validate_share_token / get_map | router.py:530-543: `_validate_share_token(db, token)` + `isinstance(token_obj, str)` guard + `get_map` + `visibility != "public"` → 404 | WIRED | Mirrors exact rule used by the /m viewer |
| PUT /maps/{id}/og-image/ | check_map_ownership | router.py:1755,1781: `require_permission("edit_metadata")` + `check_map_ownership(map_obj, user, db)` | WIRED | Owner-only auth identical to thumbnail PUT |
| doCapture onRender | PUT /maps/{id}/og-image/ | use-builder-save.ts:82-84: `uploadOgImage(mapId, og.toDataURL('image/jpeg', 0.85)).catch(silent)` | WIRED | Fire-and-forget inside single onRender; isolated failure |
| SharePanel handleCopyShareLink | /api/maps/shared/{token}/card | SharePanel.tsx:835: `getShareCardUrl()` returning `${origin}/api/maps/shared/${rawShareToken}/card` | WIRED | /card URL confirmed in vitest: clipboard value matches `/api/maps/shared/<token>/card` |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| shared_map_card_endpoint | map_obj.name, map_obj.description, map_obj.og_image_uri, map_obj.thumbnail_uri | `get_map(db, token_obj.map_id)` — DB query via SQLAlchemy ORM | Yes — reads from catalog.maps via token_obj.map_id | FLOWING |
| get_og_image | map_obj.og_image_uri | `get_map(db, map_id)` then `storage.get(map_obj.og_image_uri)` | Yes — reads from object storage by the stored key | FLOWING |
| doCapture / cropResize | srcCanvas | `map.getCanvas()` — live WebGL canvas read | Yes — reads pixel data from the active MapLibre canvas | FLOWING (headless verification limited; live canvas confirmed by vitest mock contract) |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 22 backend tests pass (card route + og-image routes + escaping + access control + migration) | `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 tests/test_maps_og_image.py -q` | 22 passed in 21.87s | PASS |
| 92 frontend vitest tests pass (use-builder-save + SharePanel) | `cd frontend && npx vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts src/components/builder/__tests__/SharePanel.test.tsx` | 2 test files, 92 tests passed | PASS |
| TypeScript typecheck clean | `cd frontend && npx tsc -b --noEmit` | 0 errors | PASS |
| i18n parity (no missing keys from font-weight / URL change) | `cd frontend && npx vitest run src/i18n/resources.test.ts` | 2 tests passed | PASS |
| No @vercel/og or satori added | `grep -n "@vercel/og\|satori" frontend/package.json frontend/package-lock.json` | No matches | PASS |
| 0 font-bold in SharePanel.tsx | `grep -c "font-bold" frontend/src/components/builder/SharePanel.tsx` | 0 | PASS |
| 4 font-semibold headers in SharePanel.tsx | `grep -c "font-semibold" frontend/src/components/builder/SharePanel.tsx` | 4 | PASS |

---

## Probe Execution

No `probe-*.sh` scripts declared for this phase. Step 7c skipped — phase is not a migration/tooling phase with conventional probe scripts.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SHARE-08 | Plans 01 + 02 | Shared map links emit OG/Twitter card meta backed by 1200x630 image; no @vercel/og or satori | SATISFIED | /card route + og-image PUT/GET + frontend dual doCapture all verified; 22 backend + 57 capture tests pass |
| SHARE-10 | Plan 02 Task 3 | SharePanel <=2 font weights | SATISFIED | 4 font-semibold headers, 0 font-bold, 4 font-medium labels; SharePanel.test.tsx regression assertion |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | - |

No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers in any phase-modified file. No stub patterns. No empty implementations. All debt markers from REVIEW.md (WR-01, WR-02, IN-01, IN-02) were addressed before this verification:
- **WR-01 FIXED**: `get_public_api_url(db, request=request)` at router.py:549 replaces raw `request.base_url`; SEC-05 CORS-allowlist gate applies
- **WR-02 FIXED**: `cropResize` docstring corrected — "Supports any target aspect ratio" (inaccurate equality claim removed)
- **IN-02 FIXED**: `test_card_route_escapes_html_in_title` uses unconditional `assert "&lt;script&gt;" in body` (weak `or "Evil" in body` fallback removed)
- **IN-01** (info, not a blocker): inline imports inside handler bodies noted but not blocking; consistent with pre-existing pattern in upload_thumbnail

---

## Human Verification Required

### 1. Live /card route meta verification (Phase 1143 close-gate)

**Test:** Using Playwright MCP, fetch `http://localhost:8080/api/maps/shared/{token}/card` for a live publicly-shared map. Assert the response is 200 text/html and the body contains `property="og:image"`, `name="twitter:card"`, `content="summary_large_image"`, an og:image content value that starts with `http`, and `http-equiv="refresh"`.
**Expected:** All meta tags present with correct attribute values; og:image is an absolute URL; twitter:card is `summary_large_image`
**Why human:** Requires a running stack with a live share token; Playwright MCP (orchestrator-driven) can verify the full HTTP response including meta tag values

### 2. OG image exists after save (Phase 1143 close-gate)

**Test:** After triggering a map save on the live builder (`http://localhost:8080/maps/{id}`), wait for the save to complete, then GET `/api/maps/{id}/og-image/` and verify the response is 200 image/jpeg with a non-zero body.
**Expected:** 200 image/jpeg returned; image resolves without error; content is a valid JPEG (not a 404 or empty body)
**Why human:** Live WebGL canvas capture via `map.triggerRepaint()` + `map.once('render')` cannot be exercised headlessly; requires Playwright MCP to interact with the running builder and assert the upload succeeded

### 3. Real-client social unfurl spot-check

**Test:** Paste the copied Share Link (which now emits the `/card` URL) into a social card preview tool such as the Twitter/X Card Validator (`https://cards-dev.twitter.com/validator`), LinkedIn post inspector, or `https://www.opengraph.io/`. Confirm the 1200x630 map thumbnail, map title, and map description appear correctly.
**Expected:** The social previewer shows the correct map preview image at 1200x630, the map title, and the map description — not a generic site card or "card not found" error
**Why human:** Requires a 3rd-party crawler with network access to the live public deployment; cannot be automated in a local development environment

---

## Gaps Summary

No code gaps. All 9 must-have truths are VERIFIED by code inspection and passing test suites (22 backend + 92 frontend tests). The OpenAPI/SDK refresh is explicitly deferred to Phase 1143 per plan design (the `/card` route is `include_in_schema=False`; the og-image routes and `MapResponse.og_image_url` are flagged for Phase 1143 refresh).

The 3 human verification items are live-execution checks that cannot be satisfied by offline grep or headless test runs. They are the Phase 1143 close-gate items per VALIDATION.md and SUMMARY.md design.

---

_Verified: 2026-05-28T20:55:00Z_
_Verifier: Claude (gsd-verifier)_
