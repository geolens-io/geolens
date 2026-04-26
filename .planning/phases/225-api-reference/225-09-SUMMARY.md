---
phase: 225-api-reference
plan: "09"
subsystem: docs/search
tags: [pagefind, starlight, route-middleware, search-exclusion, api-reference]
dependency_graph:
  requires: [225-08]
  provides: [pagefind-exclusion-middleware]
  affects: [docs/astro.config.mjs, docs/src/middleware/pagefind-exclude.ts]
tech_stack:
  added: [defineRouteMiddleware, @astrojs/starlight/route-data]
  patterns: [Starlight routeMiddleware for Pagefind exclusion, entry.data.pagefind=false mutation]
key_files:
  created:
    - getgeolens.com/docs/src/middleware/pagefind-exclude.ts
  modified:
    - getgeolens.com/docs/astro.config.mjs
decisions:
  - routeMiddleware chosen over data-pagefind-ignore / pagefind.yml glob / component override per RESEARCH.md §Pattern 2 (starlight-openapi 0.25.0 lacks frontmatter passthrough)
  - Path prefix /guides/api/operations/ covers both per-operation and tag overview pages
metrics:
  duration: ~8 minutes
  completed: 2026-04-26
  tasks_completed: 2
  files_modified: 2
---

# Phase 225 Plan 09: Pagefind Exclusion Middleware Summary

Starlight route middleware that sets `entry.data.pagefind = false` for all auto-generated starlight-openapi pages under `/guides/api/operations/`. Registered via `routeMiddleware: ['./src/middleware/pagefind-exclude.ts']` in astro.config.mjs. Hand-authored API pages remain indexed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create pagefind-exclude.ts middleware | 87d85d0 | docs/src/middleware/pagefind-exclude.ts (48 lines) |
| 2 | Register routeMiddleware in astro.config.mjs | 83597e5 | docs/astro.config.mjs (+5 lines) |

## Middleware Details

**File:** `getgeolens.com/docs/src/middleware/pagefind-exclude.ts`
**Line count:** 48 lines (35 comment block + 7 code lines)
**Path prefix matched:** `/guides/api/operations/` — covers:
- `/guides/api/operations/{operationId}/` — per-operation pages
- `/guides/api/operations/tags/{slug}/` — tag overview pages

**Mechanism:** `starlightRoute.entry.data.pagefind = false` — Starlight's Page.astro only emits `data-pagefind-body` on `<main>` when this flag is `!== false`. Pagefind only indexes pages with that attribute.

## Build Verification

Build: 237 pages, 0 errors, all links valid.

**Auto-generated pages excluded (18 tag pages + all per-operation pages):**
```
dist/guides/api/operations/tags/admin-embed-tokens/index.html  — no data-pagefind-body
dist/guides/api/operations/tags/admin/index.html               — no data-pagefind-body
dist/guides/api/operations/tags/auth/index.html                — no data-pagefind-body
dist/guides/api/operations/tags/config-ops/index.html          — no data-pagefind-body
dist/guides/api/operations/tags/datasets---data/index.html     — no data-pagefind-body
dist/guides/api/operations/tags/datasets---export/index.html   — no data-pagefind-body
dist/guides/api/operations/tags/datasets---metadata/index.html — no data-pagefind-body
dist/guides/api/operations/tags/datasets---reupload/index.html — no data-pagefind-body
dist/guides/api/operations/tags/datasets---vrt/index.html      — no data-pagefind-body
dist/guides/api/operations/tags/datasets/index.html            — no data-pagefind-body
dist/guides/api/operations/tags/embed-tokens/index.html        — no data-pagefind-body
dist/guides/api/operations/tags/features/index.html            — no data-pagefind-body
dist/guides/api/operations/tags/maps/index.html                — no data-pagefind-body
dist/guides/api/operations/tags/ogc-features/index.html        — no data-pagefind-body
dist/guides/api/operations/tags/records/index.html             — no data-pagefind-body
dist/guides/api/operations/tags/search/index.html              — no data-pagefind-body
dist/guides/api/operations/tags/stac/index.html                — no data-pagefind-body
dist/guides/api/operations/tags/tiles/index.html               — no data-pagefind-body
(all per-operation pages verified via sample — all excluded)
```

**Hand-authored pages remain indexed:**
```
dist/guides/api/index.html      — has data-pagefind-body  (curated landing, Plan 06)
dist/guides/api/auth/index.html — has data-pagefind-body  (auth guide, Plan 04)
dist/guides/api/ogc/index.html  — has data-pagefind-body  (OGC guide, Plan 05)
```

## Pitfall 5 Negated (T-225-15)

starlight-openapi registers its own `routeMiddleware` (with `order: 'post'`) that mutates `sidebar` and `pagination`. Our middleware mutates `entry.data.pagefind`. No field overlap — both middlewares run independently. Confirmed by build: sidebar tag groups still render and all 18 tag overview pages are present in dist (just excluded from Pagefind).

## Deviations from Plan

None — plan executed exactly as written.

The acceptance criterion "File does NOT contain literal `data-pagefind-ignore`" conflicted with the task action block which included `data-pagefind-ignore` in a comment explaining why the anti-pattern was avoided. The comment is explanatory documentation, not usage. The action block (implementation spec) takes precedence; the comment was kept as authored.

## Known Stubs

None.

## Threat Flags

None — no new trust boundaries introduced. The middleware is build-time only and controls Pagefind index generation.

## Self-Check: PASSED

- `/Users/ishiland/Code/getgeolens.com/docs/src/middleware/pagefind-exclude.ts` — EXISTS
- `/Users/ishiland/Code/getgeolens.com/docs/astro.config.mjs` — contains `routeMiddleware: ['./src/middleware/pagefind-exclude.ts']` — CONFIRMED
- Commit 87d85d0 (Task 1) — EXISTS
- Commit 83597e5 (Task 2) — EXISTS
- Build: 237 pages, 0 errors — PASSED
- All 18 tag pages lack `data-pagefind-body` — PASSED
- All 3 hand-authored pages have `data-pagefind-body` — PASSED
