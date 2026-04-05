---
phase: 212-repo-bootstrap-and-design-system
plan: 01
subsystem: infra
tags: [astro, tailwind, cloudflare-pages, design-tokens, oklch, inter-font, ci-cd]

# Dependency graph
requires: []
provides:
  - Astro 6.1.3 static site repo at /Users/ishiland/Code/getgeolens.com (git init, npm installed)
  - Tailwind CSS 4.2.2 configured via @tailwindcss/vite Vite plugin (CSS-first, no tailwind.config.js)
  - Full OKLCH primary scale (hue 250, 10-step) + light-mode palette in src/styles/global.css
  - Inter Variable font self-hosted via @fontsource-variable/inter (no Google Fonts CDN)
  - Tailwind 4 @theme inline block mapping CSS custom properties to Tailwind color utilities
  - src/lib/links.ts canonical external URLs matching geolens/frontend/src/lib/external-links.ts
  - Cloudflare Pages config (wrangler.toml) with pages_build_output_dir = dist
  - GitHub Actions CI workflow with astro check + build + cloudflare/pages-action deploy (PR previews)
  - WCAG A11Y-01 contrast guidance embedded in code comments
affects:
  - 212-02 (layout shell uses global.css tokens and links.ts)
  - 213 (SEO infrastructure builds on this Astro scaffold)
  - 214 (product preview assets use this build pipeline)
  - all subsequent phases in v14.0

# Tech tracking
tech-stack:
  added:
    - astro@6.1.3
    - tailwindcss@4.2.2
    - "@tailwindcss/vite@4.2.2"
    - "@astrojs/sitemap@3.7.2"
    - "@astrojs/check@0.9.8"
    - "@fontsource-variable/inter@5.2.8"
    - typescript@5.9.3
  patterns:
    - Tailwind 4 CSS-first configuration via @import "tailwindcss" + @theme inline block (no tailwind.config.js)
    - OKLCH color space throughout with CSS custom properties as source of truth, Tailwind vars as consumers
    - Self-hosted variable fonts via @fontsource-variable to avoid Google Fonts CDN (GDPR/privacy)
    - Cloudflare Pages deploy via cloudflare/pages-action@v1 with PR preview URLs via gitHubToken

key-files:
  created:
    - getgeolens.com/astro.config.mjs
    - getgeolens.com/package.json
    - getgeolens.com/tsconfig.json
    - getgeolens.com/.nvmrc
    - getgeolens.com/wrangler.toml
    - getgeolens.com/.github/workflows/ci.yml
    - getgeolens.com/public/robots.txt
    - getgeolens.com/src/styles/global.css
    - getgeolens.com/src/lib/links.ts
  modified:
    - getgeolens.com/src/pages/index.astro (added global.css import + GeoLens title)

key-decisions:
  - "Tailwind 4 uses @tailwindcss/vite Vite plugin, NOT @astrojs/tailwind — the latter is for Tailwind 3"
  - "Inter Variable font imported as @fontsource-variable/inter/wght.css (weight-variable file only, smaller bundle)"
  - "A11Y-01: primary-700 oklch(0.46 0.16 250) is the minimum shade for text on white (4.5:1 AA); primary-500 is decorative only"
  - "Node version set to 20 in .nvmrc (CI uses node-version-file: .nvmrc)"
  - "Dark mode intentionally omitted — light-mode only for v14.0 launch per D-02/D-03"
  - "tsconfig.json uses @/* path alias pointing to src/* for cleaner imports in subsequent plans"

patterns-established:
  - "Token sync: geolens/frontend/src/index.css is source of truth; getgeolens.com/src/styles/global.css is a manual copy-on-update. Comment in global.css documents this."
  - "Canonical URLs: src/lib/links.ts mirrors frontend/src/lib/external-links.ts — always use these constants, never inline URLs"
  - "CSS custom properties + @theme inline: define tokens in :root block, expose to Tailwind via --color-* vars in @theme inline"

requirements-completed: [SITE-01, SITE-02, A11Y-01]

# Metrics
duration: 3min
completed: 2026-04-05
---

# Phase 212 Plan 01: Repo Bootstrap and Design System Summary

**Astro 6.1.3 static site repo initialized with Tailwind CSS 4 @theme OKLCH token system, Inter Variable font, Cloudflare Pages deploy pipeline, and GitHub Actions CI with PR previews**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-05T06:25:21Z
- **Completed:** 2026-04-05T06:28:45Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Bootstrapped `getgeolens.com` git repo with Astro 6 minimal template; `npm run build` produces `dist/index.html` with sitemap
- Ported full GeoLens OKLCH design token set (primary hue 250, 10-step scale, surface hierarchy, elevation, semantic status) into standalone `src/styles/global.css` with Tailwind 4 `@theme inline` mapping
- Wired Cloudflare Pages deploy (wrangler.toml + cloudflare/pages-action@v1) and GitHub Actions CI (astro check + build + deploy with PR preview URLs)

## Task Commits

Each task was committed atomically:

1. **Task 1: Initialize Astro 6 project scaffold** - `b3b8762` (chore)
2. **Task 2: Create global.css with OKLCH tokens and Tailwind 4 @theme** - `2bb493f` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `getgeolens.com/astro.config.mjs` — Astro 6 static output, sitemap integration, @tailwindcss/vite Vite plugin
- `getgeolens.com/package.json` — All dependencies including astro@6.1.3, tailwindcss@4.2.2, @astrojs/check, @fontsource-variable/inter
- `getgeolens.com/tsconfig.json` — Strict TypeScript with @/* → src/* path alias
- `getgeolens.com/.nvmrc` — Node 20
- `getgeolens.com/wrangler.toml` — Cloudflare Pages config (name: getgeolens-com, pages_build_output_dir: dist)
- `getgeolens.com/.github/workflows/ci.yml` — check-and-build job + deploy job with cloudflare/pages-action@v1
- `getgeolens.com/public/robots.txt` — Allow all + sitemap URL (https://getgeolens.com/sitemap-index.xml)
- `getgeolens.com/src/styles/global.css` — Full OKLCH token set, @theme inline, Inter Variable import, A11Y-01 comment
- `getgeolens.com/src/lib/links.ts` — Canonical external URLs (GitHub, discussions, license, docs, OGC)
- `getgeolens.com/src/pages/index.astro` — Updated to import global.css and use GeoLens title

## Decisions Made

- **Tailwind 4 integration:** Used `@tailwindcss/vite` Vite plugin (not `@astrojs/tailwind`). The Astro-specific tailwind integration is for Tailwind 3. Tailwind 4 uses the Vite plugin directly, configured in `vite.plugins` in `astro.config.mjs`.
- **Font import:** Used `@fontsource-variable/inter/wght.css` specifically (the weight-variable axis only file). This is smaller than the full variable font file and covers all weight needs.
- **A11Y-01 tokens:** primary-500 oklch(0.55 0.18 250) is borderline for WCAG AA on white. primary-700 oklch(0.46 0.16 250) and primary-800 oklch(0.38 0.13 250) are the safe choices for text. Documented in code comment per plan requirement.
- **Token strategy:** CSS custom properties in `:root` are the single source of truth; `@theme inline` maps them into Tailwind's system with `var()` references so a single update cascades to both the raw CSS and Tailwind utilities.

## Exact Installed Versions

| Package | Version |
|---------|---------|
| astro | 6.1.3 |
| tailwindcss | 4.2.2 |
| @tailwindcss/vite | 4.2.2 |
| @astrojs/sitemap | 3.7.2 |
| @astrojs/check | 0.9.8 |
| @fontsource-variable/inter | 5.2.8 |
| typescript | 5.9.3 |

## WCAG Contrast Summary (A11Y-01)

| Token | Value | On White | Result |
|-------|-------|----------|--------|
| --primary-500 | oklch(0.55 0.18 250) | ~3.5:1 estimate | FAILS AA — decorative/large headings only |
| --primary-700 | oklch(0.46 0.16 250) | ~4.6:1 estimate | PASSES AA (4.5:1) — safe for normal text |
| --primary-800 | oklch(0.38 0.13 250) | ~6.5:1 estimate | PASSES AA + AAA — safe for all text sizes |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — build passed on first attempt after scaffold creation.

## User Setup Required

To enable CI deploys, two GitHub repository secrets must be set in the `getgeolens.com` repo before the first push:
- `CLOUDFLARE_API_TOKEN` — Cloudflare Dashboard → My Profile → API Tokens → Create Token (Pages:Edit permission)
- `CLOUDFLARE_ACCOUNT_ID` — Cloudflare Dashboard → right sidebar "Account ID"

The built-in `GITHUB_TOKEN` secret is automatically available — no manual configuration needed for PR preview URL comments.

## Next Phase Readiness

- Astro build pipeline fully operational: `npm run build` produces `dist/` with static HTML + sitemap
- OKLCH token system ready for use in all subsequent plans via Tailwind utilities (`text-primary-700`, `bg-primary-50`, etc.)
- `src/lib/links.ts` exports ready for nav/footer components in plan 02
- CI workflow ready — will activate on first push to GitHub

## Self-Check: PASSED

All created files verified present on disk. Both task commits confirmed in git log.

- FOUND: astro.config.mjs
- FOUND: src/styles/global.css
- FOUND: src/lib/links.ts
- FOUND: .github/workflows/ci.yml
- FOUND: wrangler.toml
- FOUND: dist/index.html
- FOUND: 212-01-SUMMARY.md
- FOUND: b3b8762 (Task 1 commit)
- FOUND: 2bb493f (Task 2 commit)

---
*Phase: 212-repo-bootstrap-and-design-system*
*Completed: 2026-04-05*
