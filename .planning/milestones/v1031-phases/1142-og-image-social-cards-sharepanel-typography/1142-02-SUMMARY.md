---
phase: 1142-og-image-social-cards-sharepanel-typography
plan: 02
subsystem: ui
tags: [react, maplibre, canvas, share, og-image, typography, tailwind]

# Dependency graph
requires:
  - phase: 1142-01
    provides: "PUT /maps/{id}/og-image/ route, GET /shared/{token}/card HTML meta route, MapResponse.og_image_url"

provides:
  - "uploadOgImage(mapId, dataUri) API function in frontend/src/api/maps.ts"
  - "1200x630 OG capture in same doCapture repaint as 400x250 thumbnail (one triggerRepaint)"
  - "getShareCardUrl() returning /api/maps/shared/{token}/card — wired into Copy Link"
  - "SharePanel section headers promoted to font-semibold (4 sites); font-medium kept on secondary labels (4 sites)"

affects: [1143-quality-sweep-playwright-close-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "cropResize(srcCanvas, w, h) helper — reusable center-crop for any target dimension sharing the same render pass"
    - "Dual upload in one onRender callback — OG upload fire-and-forget with isolated catch alongside thumbnail upload"
    - "getShareCardUrl() alongside getShareUrl() — two URL shapes for two purposes (social unfurl vs direct viewer)"

key-files:
  created: []
  modified:
    - frontend/src/api/maps.ts
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
    - frontend/src/components/builder/SharePanel.tsx
    - frontend/src/components/builder/__tests__/SharePanel.test.tsx

key-decisions:
  - "OG capture failure is isolated — separate .catch() so a failed PUT /og-image/ never prevents the thumbnail save"
  - "One triggerRepaint() — both toDataURL() calls happen synchronously in the same onRender callback (Pitfall #5)"
  - "Copy Link emits /card URL; Open button retains /m/{token} for direct redirect-free viewer load"
  - "font-semibold on 4 text-sm section headers; font-medium stays on 4 text-xs secondary labels — net 2 explicit weights"

patterns-established:
  - "cropResize helper: extract crop-resize into parameterized helper when multiple target sizes share a single canvas read"
  - "Dual-upload in one render: two uploads can share ONE map.once('render') + ONE triggerRepaint"

requirements-completed: [SHARE-08, SHARE-10]

# Metrics
duration: 5min
completed: 2026-05-28
---

# Phase 1142 Plan 02: OG Capture + Copy-Link /card + SHARE-10 Typography Summary

**1200x630 OG JPEG captured in the existing doCapture repaint and uploaded via uploadOgImage; Copy Link now emits the /card URL for social unfurling; 4 SharePanel section headers promoted to font-semibold for a clean 2-weight hierarchy**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-28T16:31:31Z
- **Completed:** 2026-05-28T16:36:00Z
- **Tasks:** 3 (Task 1 TDD RED + GREEN; Tasks 2-3 auto)
- **Files modified:** 5

## Accomplishments
- `uploadOgImage(mapId, dataUri)` added to `maps.ts` (mirrors `uploadThumbnail` — PUT to `/maps/{id}/og-image/`)
- `cropResize(srcCanvas, w, h)` helper extracted; `doCapture` now captures 400×250 thumbnail + 1200×630 OG image in ONE render pass; OG failure is silently isolated from thumbnail save
- `getShareCardUrl()` added adjacent to `getShareUrl()`; `handleCopyShareLink` copies the `/card` URL so pasted links unfurl in social clients; `getShareUrl()` preserved for "Open in new tab"
- SHARE-10: 4 section headers (`visibilityTitle`, `opt.titleKey`, `shareLink`, `embedCode`) promoted from `font-medium` → `font-semibold`; 4 secondary labels (`text-xs`) kept at `font-medium`; 0 `font-bold`
- 92 tests pass (57 use-builder-save + 35 SharePanel); 0 typecheck errors

## Task Commits

Each task was committed atomically:

1. **TDD RED gate** — `6b21a786` (test: add failing SHARE-08 OG capture test)
2. **Task 1: uploadOgImage + 1200x630 OG capture** — `4f4bc429` (feat)
3. **Task 2: Copy Link emits /card URL** — `453fb56f` (feat)
4. **Task 3: SHARE-10 font-semibold promotion** — `81562423` (feat)

_Note: Task 1 followed TDD: RED commit `6b21a786` then GREEN commit `4f4bc429`._

## Files Created/Modified
- `frontend/src/api/maps.ts` — added `uploadOgImage(mapId, dataUri)` after `uploadThumbnail`
- `frontend/src/components/builder/hooks/use-builder-save.ts` — extracted `cropResize` helper; extended `doCapture` to upload both 400×250 thumbnail and 1200×630 OG image in one `onRender`; imports `uploadOgImage`
- `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` — mocked `uploadOgImage` in `@/api/maps` vi.mock; added SHARE-08 test asserting both uploads called once + triggerRepaint once
- `frontend/src/components/builder/SharePanel.tsx` — added `getShareCardUrl()`; wired into `handleCopyShareLink`; promoted 4 `font-medium` → `font-semibold`
- `frontend/src/components/builder/__tests__/SharePanel.test.tsx` — added SHARE-08 describe (clipboard writes `/card` URL; embed code preserves `/m/` + `embed=true`); added SHARE-10 describe (font-semibold > 0; font-bold === 0)

## Decisions Made

- `getShareUrl()` is preserved unchanged so the "Open in new tab" button still lands directly in the SPA viewer without the `/card` meta-refresh bounce.
- `getShareCardUrl()` returns `''` if `rawShareToken` is null (same guard as `getShareUrl()`), so the clipboard write is a no-op when no token exists.
- OG upload failure uses a separate `.catch()` from thumbnail upload; both are fire-and-forget; thumbnail's `invalidateQueries` is also isolated from OG path.
- SHARE-10: `font-semibold` chosen (not `font-bold`) for section hierarchy — consistent with v1030 audit intent ("clearer 2-weight system") and the existing design token precedent in the builder.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

The frontend `MapResponse` type in `types/api.ts` did not yet include `og_image_url` (Plan 01 added the field on the backend but the frontend type snapshot was not updated — that refresh is deferred to Phase 1143 per plan). Plan 02 does not consume `og_image_url` in any frontend type check, so this was a non-issue for this plan.

## Note on Phase 1143 Dependency

This plan consumes the Plan 01 routes (`PUT /og-image/`, `GET /shared/{token}/card`). Phase 1143 owns the OpenAPI/SDK refresh (`make openapi` + `npm run fetch-openapi`) as flagged in Plan 01 SUMMARY and RESEARCH.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced by this plan. The `getShareCardUrl()` exposes the share token in the copied URL — this is the same token already in `getShareUrl()` (T-1142-07 accepted in plan threat model).

## Next Phase Readiness

- SHARE-08 frontend complete: 1200×630 OG capture on every save + Copy Link emits `/card` URL
- SHARE-10 complete: 2-weight font hierarchy in SharePanel
- Phase 1143 (Quality Sweep & Playwright Close-Gate) can verify the full social card flow end-to-end via live MCP

## Self-Check: PASSED

- `frontend/src/api/maps.ts` — FOUND: uploadOgImage
- `frontend/src/components/builder/hooks/use-builder-save.ts` — FOUND: cropResize + uploadOgImage call
- `frontend/src/components/builder/SharePanel.tsx` — FOUND: getShareCardUrl + /card
- Commits: 6b21a786, 4f4bc429, 453fb56f, 81562423 — all confirmed in git log
- Tests: 92/92 pass; typecheck: 0 errors

---
*Phase: 1142-og-image-social-cards-sharepanel-typography*
*Completed: 2026-05-28*
