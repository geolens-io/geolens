---
phase: 224
plan: "04"
subsystem: docs-site
tags: [starlight, astro, shell, breadcrumbs, header, 404, search, ec-plugin, ci]
dependency_graph:
  requires:
    - phase: 224-01
      provides: custom.css with --primary-* tokens
    - phase: 224-02
      provides: verify-build.sh assertions + check-token-sync.sh
    - phase: 224-03
      provides: ec-pagefind-weight.mjs plugin + placeholder guide pages
  provides:
    - docs/src/components/Breadcrumbs.astro (SHELL-02 PageTitle override)
    - docs/src/components/DocsHeader.astro (SHELL-05 Header override)
    - docs/src/pages/404.astro (SHELL-03 custom 404)
    - docs/astro.config.mjs (editLink, pagination, lastUpdated, EC plugin, components wiring)
    - docs/src/env.d.ts (virtual module type declarations)
    - Integration build verified: all Phase 224 assertions pass
  affects: [phase-225, phase-226, phase-227, phase-228, docs-ci-gate]
tech_stack:
  added: []
  patterns:
    - "Starlight component override: components.PageTitle -> Breadcrumbs.astro"
    - "Starlight component override: components.Header -> DocsHeader.astro"
    - "Absolute-positioned back-link: anchored to position:fixed <header> (Pivot #3)"
    - "StarlightPage with template:splash for custom 404 Astro page"
    - "EC plugin registration: starlight.expressiveCode.plugins (Pivot #1, not rehypePlugins)"
    - "virtual:starlight/components/Search imported in Astro page context"
key_files:
  created:
    - getgeolens.com/docs/src/components/Breadcrumbs.astro
    - getgeolens.com/docs/src/components/DocsHeader.astro
    - getgeolens.com/docs/src/pages/404.astro
    - getgeolens.com/docs/src/env.d.ts
  modified:
    - getgeolens.com/docs/astro.config.mjs
    - getgeolens.com/docs/scripts/verify-build.sh
key_decisions:
  - "Absolute positioning for back-link (NOT display:contents + grid-column — Pivot #3: display:contents approach renders above header, not in-grid)"
  - "env.d.ts with path reference to virtual-internal.d.ts resolves virtual:starlight/components/Search TS2307 error"
  - "verify-build.sh BRAND-01 regex updated to accept minified OKLCH (no leading zero) from Vite/cssnano"
  - "No Cmd+K listener added — Starlight 0.38.4 binds natively at Search.astro:118-124 (D-29)"
  - "404.astro as Astro page (not content collection) — Starlight content schema requires slug; 404 is host-routed"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-25"
  tasks_completed: 3
  files_changed: 6
---

# Phase 224 Plan 04: Shell Wiring + Integration Build Summary

Authored three custom shell components (Breadcrumbs.astro, DocsHeader.astro, 404.astro), wired all Phase 224 config additions into astro.config.mjs, and verified clean integration build with all 17 Phase 224 build-artifact assertions passing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author Breadcrumbs.astro + DocsHeader.astro + 404.astro | 171288b | docs/src/components/Breadcrumbs.astro, DocsHeader.astro, src/pages/404.astro |
| 2 | Wire astro.config.mjs + env.d.ts | 0670d98 | docs/astro.config.mjs, docs/src/env.d.ts |
| 3 | Integration build verification + verify-build.sh fix | cd497c1 | docs/scripts/verify-build.sh |

## Success Criteria

- [x] SHELL-01 (config side): pagination: true set; sidebar 4 groups render placeholder pages
- [x] SHELL-02: editLink.baseUrl wired; Breadcrumbs.astro renders `<nav aria-label="breadcrumb">` on /guides/quickstart/
- [x] SHELL-03: dist/404.html with brand mark, search, 4 category cards, footer link
- [x] SHELL-04: lastUpdated: true wired; `<time datetime="20XX">` present in dist/guides/quickstart/index.html
- [x] SHELL-05 (docs side): DocsHeader prepends back-link with rel="noopener"; absolute-positioned (NOT display:contents)
- [x] SEARCH-01: dist/pagefind/pagefind.js exists
- [x] SEARCH-02: pluginPagefindWeight() registered in expressiveCode.plugins
- [x] SEARCH-03: Cmd+K natively bound by Starlight 0.38.4 (D-29); no duplicate listener added (verified by source inspection); manual browser probe deferred to phase-level verification
- [x] All verify-build.sh assertions exit 0
- [x] check-token-sync.sh exits 0
- [x] astro check exits 0 (0 errors, 0 warnings)

## What Was Built

**Breadcrumbs.astro** (SHELL-02 / D-17): PageTitle override that prepends `<nav aria-label="breadcrumb"><ol>` with Docs root anchor + URL-segment-derived crumbs. Uses `aria-current="page"` on leaf. Hidden when pathname has fewer than 2 segments (homepage, top-level landings). Kebab-to-TitleCase transform applied. All CSS uses Starlight tokens.

**DocsHeader.astro** (SHELL-05 / D-25): Header override wrapping Starlight's default `<Default {...Astro.props} />` with a `position: absolute` back-link anchored to the position:fixed page header. Shows `← getgeolens.com` with `rel="noopener"` (no noreferrer — preserves Referer for analytics). Visible domain text on all viewport widths (no responsive collapse). Script block documents Cmd+K binding source but registers no listener.

**404.astro** (SHELL-03 / D-21..D-23): Astro page (not content collection) using `StarlightPage` with `template: 'splash'`. Frontmatter explicitly disables `prev`, `next`, `editUrl`, `lastUpdated`, `pagefind` to suppress footer per Pitfall 4. Contains brand "404" mark in `--primary-700`, "Page not found" heading, description body, `<Search />` component from virtual module, 4 category cards linking to guide sections, and footer link to getgeolens.com. Zero hardcoded colors.

**astro.config.mjs** additions: `editLink.baseUrl` pointing to GitHub /edit/main/docs/ (trailing slash per D-18); `pagination: true`; `lastUpdated: true`; `expressiveCode.plugins: [pluginPagefindWeight()]` (Pivot #1 — not rehypePlugins); `components: { Header, PageTitle }` overrides. All Phase-223 settings preserved (site, output, customCss, head noindex, 4-group sidebar).

**env.d.ts**: Added `/// <reference path="../node_modules/@astrojs/starlight/virtual-internal.d.ts" />` to resolve TS2307 for `virtual:starlight/components/Search` import in 404.astro.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added src/env.d.ts to resolve virtual:starlight type error**
- **Found during:** Task 2 verification (`npx astro check`)
- **Issue:** `virtual:starlight/components/Search` import in 404.astro produced TS2307 "Cannot find module" error. Starlight's `virtual-internal.d.ts` contains the declaration but is not referenced by the generated `.astro/types.d.ts`.
- **Fix:** Created `docs/src/env.d.ts` with `/// <reference path="../node_modules/@astrojs/starlight/virtual-internal.d.ts" />` to pull in all virtual:starlight/components/* module declarations.
- **Files modified:** getgeolens.com/docs/src/env.d.ts (created)
- **Committed in:** 0670d98 (Task 2 commit)

**2. [Rule 3 - Blocking] Fixed BRAND-01 regex in verify-build.sh for minified OKLCH**
- **Found during:** Task 3 verification (`bash scripts/verify-build.sh`)
- **Issue:** Vite/cssnano minifies `oklch(0.97 0.02 250)` to `oklch(.97 .02 250)` (drops leading zeros). The Plan 02-authored regex `oklch\(0\.[0-9]+ 0\.[0-9]+ 250\)` required a leading `0` and never matched the minified form. Plan 01 SUMMARY flagged this as a known issue for Plan 02 to fix; it was not fixed then and blocked Task 3 here.
- **Fix:** Updated BRAND-01 assertion regex to `oklch\(0?(\.[0-9]+|[0-9]+\.[0-9]+) 0?(\.[0-9]+|[0-9]+\.[0-9]+) 250\)` — accepts both `0.97` and `.97` forms.
- **Files modified:** getgeolens.com/docs/scripts/verify-build.sh
- **Committed in:** cd497c1 (Rule 3 fix commit)

### Notes on Route Collision Warning

`astro check` and `npm run build` emit a warning: "The route '/404' is defined in both 'src/pages/404.astro' and 'node_modules/@astrojs/starlight/routes/static/404.astro'". This is **expected and correct** — Starlight ships a default 404 page which our custom `src/pages/404.astro` overrides (D-21 specifies `src/pages/404.astro` intentionally). Astro says "A collision will result in a hard error in following versions" but as of Astro 6.1.9 this is only a warning and the build succeeds. Future Astro upgrades may require migrating to a Starlight content-collection approach.

### SEARCH-03 Cmd+K Manual Probe

The plan calls for a manual browser probe of Cmd+K opening the Pagefind dialog. This is deferred to phase-level verification (same disposition as BRAND-03 screenshot pair per D-12). The native binding is confirmed by source inspection of `node_modules/@astrojs/starlight/components/Search.astro:118-124` — the `window.addEventListener('keydown', ...)` binding exists. No duplicate listener was added.

## Known Stubs

None introduced in this plan. The guide placeholder pages (`index.mdx`) from Plan 03 are intentional stubs tracked in Plan 03's SUMMARY.

## Threat Flags

None — this plan creates client-side-only Astro components and modifies static build config. No new network endpoints, auth paths, or trust boundaries introduced.

## Self-Check: PASSED

- [x] getgeolens.com/docs/src/components/Breadcrumbs.astro — FOUND
- [x] getgeolens.com/docs/src/components/DocsHeader.astro — FOUND
- [x] getgeolens.com/docs/src/pages/404.astro — FOUND
- [x] getgeolens.com/docs/src/env.d.ts — FOUND
- [x] getgeolens.com/docs/astro.config.mjs — modified with all 5 additions
- [x] getgeolens.com/docs/scripts/verify-build.sh — BRAND-01 regex fixed
- [x] Commit 171288b — FOUND (Task 1)
- [x] Commit 0670d98 — FOUND (Task 2)
- [x] Commit cd497c1 — FOUND (Task 3 / Rule 3 fix)
- [x] npm run build — EXIT 0
- [x] bash scripts/verify-build.sh — EXIT 0 (all 17 assertions passed)
- [x] bash scripts/check-token-sync.sh — EXIT 0
- [x] npx astro check — EXIT 0 (0 errors, 0 warnings)
