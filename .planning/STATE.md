---
gsd_state_version: 1.0
milestone: v15.0
milestone_name: milestone
status: verifying
stopped_at: Completed Phase 999.5 Plan 05 (Starlight logo wiring, cross-repo D-11)
last_updated: "2026-04-26T15:14:28.693Z"
last_activity: 2026-04-26
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 17
  completed_plans: 17
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-25)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 999.5 — style-system-alignment

## Current Position

Phase: 999.5 (style-system-alignment) — EXECUTING
Plan: 8 of 8
Status: Phase complete — ready for verification
Last activity: 2026-04-26

## Performance Metrics

**Velocity:**

- Total plans completed: 2
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 223 | 2 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 223 P01 | 5 | 3 tasks | 15 files |
| Phase 224 P05 | 12min | 3 tasks | 3 files |
| Phase 999.5 P01 | 6min | 3 tasks | 4 files |
| Phase 999.5 P02 | 1min | 2 tasks | 2 files |
| Phase 999.5 P03 | 1min | 1 tasks | 1 files |
| Phase 999.5 P04 | 2min | 1 tasks | 1 files |
| Phase 999.5 P05 | 1min | 1 tasks tasks | 1 files files |
| Phase 999.5 P06 | 1min | 1 tasks | 1 files |
| Phase 999.5 P07 | 3min | 1 tasks | 1 files |

## Accumulated Context

### Decisions

- [v15.0 Scope]: Docs site lives in the existing `getgeolens-com` marketing repo (not a new repo, not the geolens monorepo) — shared design tokens, single source of truth for brand identity
- [v15.0 Scope]: Astro Starlight chosen over Mintlify/Docusaurus/VitePress — Astro-native, matches existing marketing-site stack, Pagefind search built in
- [v15.0 Scope]: Subdomain routing via separate Cloudflare Pages project from the same repo — `docs.getgeolens.com` decoupled from marketing-site deploys/caching
- [v15.0 Scope]: Single "latest" version for v15.0 — no versioning machinery; defer until 1.x.y churn justifies it
- [v15.0 Scope]: API reference auto-rendered from FastAPI `openapi.json` at build time — stays in sync with code, no hand-maintained endpoint docs in v15.0
- [v15.0 Scope]: Pagefind static search (Starlight default) — no Algolia DocSearch dependency
- [v15.0 Scope]: Phase 216 split — Quickstart/Install moves to docs site; Features page is built on marketing site as part of this milestone
- [v15.0 Scope]: Map builder polish is being handled in a parallel workstream — explicitly excluded from this milestone
- [v15.0 Roadmap]: Phase 223 is load-bearing — URL structure, CF Pages multi-project config, token-drift check, `_redirects` stub, GA4, canonical site URL, openapi snapshot strategy, version pin gate all locked here before content begins
- [v15.0 Roadmap]: MIG-01 split across Phase 226 (install stub) and Phase 227 (admin stub) — each stub replaced atomically with the phase that writes its canonical content
- [223-01]: Mirror marketing astro@^6.1.3 pin exactly (D-20); Starlight 0.38.4 peerDeps require Astro 6
- [223-01]: Empty /guides/ sidebar groups declared upfront via autogenerate so Phase 224 cannot regress to flat URLs (D-11)
- [223-01]: Belt-and-suspenders noindex (robots.txt Disallow + meta tag) — both flip together in Phase 228 (D-07/D-08)
- [223-01]: /quickstart explicitly excluded from docs _redirects (owned by marketing per D-14); 9 redirect rules total (3 paths × 3 variants)
- [223-01]: verify-build.sh has NO GA4 grep — SEO-06 deferred to Phase 228 per D-19
- [223-02]: Mirror marketing's `cloudflare/pages-action@v1` despite deprecation (D-01) — coordinated migration to wrangler-action@v3 is a future cross-repo task requiring user re-decision
- [223-02]: Reuse existing CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID GitHub secrets (D-05) — no new secrets minted; narrowed secret-leak surface
- [223-02]: Symmetric path filtering — docs-ci.yml `paths: ['docs/**', '.github/workflows/docs-ci.yml']` + ci.yml `paths-ignore: ['docs/**']`. Neither workflow references the other's path; self-edits to either workflow still trigger that workflow as a sanity check (RESEARCH §3.5 + §7.1)
- [223-02]: CF Pages dashboard + custom domain + TLS + probe PRs DEFERRED at operator's request — file infrastructure ready; resume steps preserved in 223-02-SUMMARY.md "Deferred Verification" section. Phase 228 must close this before launch.
- [Phase 224]: [224-05]: Sized --back-link-reserved-space at 10rem (160px) — clears back-link.right (~146.8px) with ~13.2px headroom; 9rem would re-introduce ~2.8px overlap
- [Phase 224]: [224-05]: Source-side grep in verify-build.sh (not dist-side) — Vite minification unstable across upgrades, same lesson as Plan 04 BRAND-01
- [Phase 224]: [224-05]: Playwright shell-layout probe is runtime-only, not wired into docs-ci.yml — preview-server lifecycle complicates CI; build-time grep guards against deletion
- [Phase 999.5-01]: @fontsource/inter devDep was unused (audit Case A); src/lib/og.ts loads inter-700.ttf locally from src/assets/fonts/, not from node_modules — safe to remove the package without script edits
- [Phase 999.5-01]: OG image script font swap (RESEARCH.md Pitfall 6) deferred — Plan 01 is package-manifest-only; the local inter-700.ttf TTF file is unaffected and remains a candidate for a future task
- [Phase ?]: [Phase 999.5-02]: Canonical logo SVG canonicalized on existing favicon geometry (viewBox 0 0 64 64, r=22, cx/cy 27) — NOT a JSX-to-SVG extraction of GeoLensLogo.tsx (different proportions r=18 cx/cy 26)
- [Phase ?]: [Phase 999.5-02]: Two byte-identical SVG copies (public/logo.svg + docs/src/assets/logo.svg) to satisfy Astro/Vite cross-project-root asset import constraint (RESEARCH Pitfall 3)
- [Phase ?]: [Phase 999.5-02]: stroke=currentColor only on logo.svg — favicon.svg keeps hardcoded #334155 because browser favicon contexts cannot resolve currentColor
- [Phase 999.5-03]: Marketing global.css IBM Plex swap applied via four edits — @import, @theme --font-sans, html font-family fallback, and header comment block (D-06 'Intentional / Rationale / Revisit if' format). Astro build green; IBM Plex woff2 subsets emitted.
- [Phase 999.5-03]: Did NOT add --font-mono to global.css (RESEARCH File 1 explicit guidance — marketing has no monospace usage). Mono token only added to docs custom.css in Plan 04.
- [Phase 999.5-04]: Docs custom.css fully replaced verbatim from RESEARCH.md File 2 (3084 chars byte-identical) — IBM Plex fonts, brand-blue Aside note+tip overrides, warmer light-mode sidebar tint; OKLCH primary palette mirror unchanged; 49 → 71 lines; +33/-11 diff.
- [Phase 999.5-04]: caution (--sl-color-orange-*) and danger (--sl-color-red-*) intentionally NOT overridden — Aside semantic warning colors preserved per D-04. note (blue) and tip (purple) hue groups overridden to brand primary cascade in both light and dark.
- [Phase 999.5-04]: Sidebar tint --sl-color-bg-sidebar: oklch(0.99 0.003 85) declared only in light :root per RESEARCH Pitfall 5; dark sidebar stays at Starlight default --sl-color-gray-6.
- [Phase ?]: [Phase 999.5-05]: Starlight logo block (logo: { src: './src/assets/logo.svg', alt: 'GeoLens', replacesTitle: false }) added to docs/astro.config.mjs additively after the title key. astro check + npm run build both green; rendered HTML confirms logomark + title text co-render in nav. Implementation commit 6fc8ab1 in getgeolens.com (branch gsd/phase-225-api-reference) per D-11; SUMMARY commits to geolens main.
- [Phase 999.5-06]: check-token-sync.sh extended verbatim from RESEARCH.md File 3 with Option-1 fail-OPEN guard (test -f $APP_CSS) for the cross-repo app leg; existing 10-stop primary-palette assertion (Phase 224 BRAND-04) preserved byte-identical. Implementation commit fca068e in getgeolens.com (branch gsd/phase-225-api-reference) per D-11; SUMMARY commits to geolens main.
- [Phase 999.5-07]: Cross-surface DESIGN-GUIDE.md authored at getgeolens.com root references geolens/docs/DESIGN-GUIDE.md upstream rather than duplicating tokens (D-07, D-09); 4-section structure (Shared / Marketing-Specific / Docs-Specific / Drift CI Contract) per D-08; quotes the verbatim D-06 light-only rationale comment from global.css; provenance tail names CONTEXT/RESEARCH/HANDOFF in geolens/.planning/. Implementation commit 86a4dab in getgeolens.com (branch gsd/phase-225-api-reference) per D-11; SUMMARY commits to geolens main.

### Roadmap Evolution

- 2026-04-25: Milestone v15.0 initiated — documentation site scope confirmed
- 2026-04-25: Roadmap created — 6 phases (223–228), 61 requirements mapped, 100% coverage

### Pending Todos

None yet.

### Blockers/Concerns

- **Deferred deploy verification (Phase 223 Plan 02 Task 3)**: CF Pages getgeolens-docs project not yet created; docs.getgeolens.com custom domain not attached; TLS not verified; build-isolation probe PRs not run; PR preview comment not validated. File infrastructure (docs-ci.yml + ci.yml paths-ignore) is in place — operator can resume any time using the "Deferred Verification" section of `.planning/phases/223-bootstrap-infrastructure-lock/223-02-SUMMARY.md`. This must close before Phase 228 (SEO go-live) ships, since Phase 228's robots.txt flip + sitemap submission both require a live URL.

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260425-h8k | Review map builder labeling with Playwright | 2026-04-25 | pending | Verified | [260425-h8k-review-map-builder-labeling-with-playwri](./quick/260425-h8k-review-map-builder-labeling-with-playwri/) |
| 260425-lbc | Fix map overlay positioning conflicts (filter chips vs measure widget, bottom-left stacking) | 2026-04-25 | cd2e5a3f | Needs Review | [260425-lbc-in-the-map-builder-review-the-map-overla](./quick/260425-lbc-in-the-map-builder-review-the-map-overla/) |
| 260425-oxh | Layer popup config: enable/disable + custom expression with validation | 2026-04-25 | 8ca90a9f | Verified | [260425-oxh-layer-popup-config-enable-disable-custom](./quick/260425-oxh-layer-popup-config-enable-disable-custom/) |
| 260425-sl1 | Address backend test debt (15 failures from audit 2026-04-25) — restored green-baseline (1965/1965) | 2026-04-26 | d6c5a4c8 | Verified | [260425-sl1-address-the-debt-in-docs-internal-audits](./quick/260425-sl1-address-the-debt-in-docs-internal-audits/) |

## Session Continuity

Last session: 2026-04-26T14:49:51.391Z
Stopped at: Completed Phase 999.5 Plan 05 (Starlight logo wiring, cross-repo D-11)
Resume file: None

**Planned Phase:** 223 (Bootstrap & Infrastructure Lock) — 2 plans — 2026-04-25T17:13:13.520Z
