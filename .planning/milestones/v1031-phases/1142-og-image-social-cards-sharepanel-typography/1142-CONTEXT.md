# Phase 1142: OG-Image Social Cards & SharePanel Typography - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning (research-informed — Path A/B + crawler-meta mechanism decided at plan-phase)
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Two requirements on the sharing surface:
- **SHARE-08** — Shared map links emit OG-image / social-card meta (`og:image`, `og:title`, `twitter:card`) backed by a 1200×630 map preview, so links unfurl with a preview in social/chat clients.
- **SHARE-10** — SharePanel renders ≤2 distinct font weights (UI-SPEC max-2 conformance), reduced from the current 3 across ~5 sites. Cosmetic (v1030 audit finding F2).

</domain>

<decisions>
## Implementation Decisions

### SHARE-08 — research-informed (decide at plan-phase)
Two coupled questions the researcher MUST resolve before planning:
1. **Crawler-facing meta (the hard part):** GeoLens is a Vite SPA — `og:image` lives in static `frontend/index.html`, and social crawlers do NOT run JS, so a client-injected per-map meta tag is invisible to them. Determine how shared/embed map URLs are served and the right mechanism to emit PER-MAP OG meta that a crawler sees (e.g. a backend HTML route for the share/embed URL that server-renders the meta, or an existing share-render path). Pick the smallest-blast-radius mechanism that fits the existing architecture and the no-rewrite invariant.
2. **1200×630 image — Path A vs Path B** (from the backlog disposition):
   - **Path A:** nullable `og_image_uri` column (migration) + `PUT /maps/{id}/og-image/` upload route + `GET /maps/{id}/og-image/` serve route + a second frontend `doCapture` at 1200×630 alongside the existing 400×250 thumbnail capture.
   - **Path B:** backend receives the native canvas capture (~1440×900) and resizes to both the 400×250 thumbnail and the 1200×630 OG variants on upload (one capture, server-side resize).
   Recommend ONE path based on the existing thumbnail pipeline (where the 400×250 thumbnail is captured, stored, and served — research noted `use-builder-save.ts` ~line 33-34 `thumbW/thumbH` and a backend thumbnail column/route in `backend/app/modules/catalog/maps/`).

### Known constraints (v1031 HARD INVARIANTS)
- **Do NOT add `@vercel/og` or `satori`** (STACK do-not-add list). Use the existing canvas-capture pipeline + (if Path B) the backend's existing image libs (e.g. Pillow/GDAL — verify what's available).
- Feature-add on existing share/embed substrate (the `3ed5ceb3` share/viewer work + v1030 SharePanel). Behavior preservation: existing share/thumbnail/embed flows unaffected.
- **No architecture rewrites:** no new files >500 LOC; no rename of >3 exported symbols. A small backend meta-HTML route or a resize step is fine; a full SSR framework is NOT.
- Backend changes (new column/route OR resize pipeline) → trigger OpenAPI/SDK refresh in Phase 1143 (do NOT regen SDK here; flag in SUMMARY).

### SHARE-10
- Reduce SharePanel to ≤2 font weights. Current sites use `font-medium` (multiple) + likely a `font-semibold`/`font-bold` somewhere = 3 weights. Pick a 2-weight system (e.g. regular 400 + medium 500, OR regular + semibold) consistent with the UI-SPEC/design tokens and apply across all SharePanel sites. Pure CSS class change; no behavior change.

</decisions>

<code_context>
## Existing Code Insights (analogs — investigate during research)

- `frontend/src/hooks/use-builder-save.ts` — the thumbnail capture (research cited `thumbW=400`/`thumbH=250`); locate the actual capture + PUT.
- `backend/app/modules/catalog/maps/{models.py,schemas.py,router.py,service_public.py,service_crud.py}` — the thumbnail column + serve route + map-model; Path A's `og_image_uri` column/routes would extend these; the share/embed serve path lives here too.
- `frontend/index.html` — static SPA meta tags (the crawler-meta limitation lives here).
- `frontend/src/components/builder/SharePanel.tsx` — SHARE-10 font-weight sites (lines ~315, 336, 389, 883, 905, 930, 1039, 1102 use `text-xs/text-sm font-medium`); also the SharePanel test file.

</code_context>

<specifics>
## Specific Ideas
- SHARE-08: prefer reusing the existing thumbnail storage/serve mechanism for the OG variant (extend, don't parallel-build). The meta must include `og:image`, `og:title`, `og:description`, `twitter:card=summary_large_image`.
- SHARE-10: a single consistent 2-weight pass across SharePanel; add a regression assertion if practical.
- Backend tests for any new route (focused pytest, DB up on 5434). Frontend vitest for capture/meta wiring + SharePanel.
- New/changed i18n only if copy changes — keep 4-locale parity.

</specifics>

<deferred>
## Deferred Ideas
- Dynamic per-map OG text beyond title/description (e.g. layer-count badges) — out of scope.
- OG images for non-map pages — out of scope (this is map share links).

</deferred>
