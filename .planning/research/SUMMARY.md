# Project Research Summary

**Project:** v15.0 Documentation Site (docs.getgeolens.com)
**Domain:** Static documentation site — Astro Starlight in existing Astro 6 marketing monorepo
**Researched:** 2026-04-25
**Confidence:** HIGH

## Executive Summary

GeoLens v15.0 is a standalone documentation site deployed to `docs.getgeolens.com`, built on Astro Starlight inside the existing `getgeolens-com` marketing repo. The expert approach is straightforward: Starlight is the only documentation framework that is Astro 6-native, ships Pagefind search without configuration, auto-generates an API reference from OpenAPI spec via `starlight-openapi`, and matches the existing build toolchain without introducing a parallel dependency tree. The site lives in a `docs/` subdirectory with its own `package.json` — independent from the marketing site — and deploys via a second Cloudflare Pages project pointed at that subdirectory. Design token parity with the marketing site is achieved through a hand-written `custom.css` mapping GeoLens OKLCH primary blue (hue ~250) into Starlight's `--sl-*` CSS custom properties. No npm workspaces, no symlinks, no shared build steps.

The recommended approach resolves the two blockers in STATE.md before writing any content. First, the `openapi.json` strategy is decided as a committed snapshot (not a live fetch) — a pre-build CI script refreshes it non-fatally, keeping builds reliable even when the production API is unreachable. Second, the canonical docs migration: `backend/docs/install.md` and `backend/docs/admin.md` in the geolens monorepo are replaced with one-line pointer stubs the moment the docs site content is published, eliminating dual-canonical indexing. URL structure must be prefixed (`/guides/`, `/admin/`, `/api/`) — not flat — to leave room for a future `/v2/` prefix without a breaking rename of every page.

The top risks are (1) Cloudflare Pages build contamination — both projects rebuild on every push without explicit path filtering; (2) design token drift — the Starlight `custom.css` file will silently diverge from the marketing site unless a CI diff check is enforced from Phase 1; (3) Satori OG image generation failing silently if OKLCH color values are copy-pasted from the marketing site templates without converting to hex (Satori does not support `oklch()`); and (4) Pagefind polluting search results with code block fragments. All four are preventable in Phase 1 (Bootstrap) if the right scaffolding decisions are locked before content work begins.

## Key Findings

### Recommended Stack

Starlight `0.38.4` is the exact match: it dropped Astro 5 support and added Astro 6 support in v0.38.0, aligning precisely with the existing marketing site toolchain. The docs site gets its own `package.json` in `docs/` — no version conflicts with marketing site deps. The Tailwind bridge package (`@astrojs/starlight-tailwind`) is optional and only needed if the docs site uses Tailwind utility classes in custom components; for token sharing alone, raw CSS variables in `custom.css` are sufficient and avoid coupling the docs build to the marketing site's Tailwind config.

**Core technologies:**
- `@astrojs/starlight@0.38.4`: Documentation framework — Astro 6-native, Pagefind built in, the only framework compatible with the existing stack
- `starlight-openapi@0.25.0`: API reference plugin — generates static pages from committed `openapi.json`; confirmed peer-compatible with Starlight 0.38 and Astro 6
- `pagefind@1.5.2` (bundled): Static full-text search — zero config, zero external service, runs automatically at `astro build`
- `@astrojs/sitemap`: Sitemap generation — required in `docs/astro.config.mjs` with `site: 'https://docs.getgeolens.com'` set from Phase 1
- `cloudflare/pages-action` (GitHub Actions): Deploy mechanism — reuses existing `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets; second Pages project `geolens-docs` with `rootDirectory: docs`

**Resolved contradiction — Tailwind bridge:** STACK.md recommends raw `customCss` over `@astrojs/starlight-tailwind` for token sharing. ARCHITECTURE.md agrees: the bridge is only needed if docs components use Tailwind utilities. For v15.0, use raw CSS variables only. The bridge is not installed.

### Expected Features

The full feature detail is in `.planning/research/FEATURES.md`. Summary below.

**Must have (table stakes — all low-complexity Starlight built-ins):**
- Sidebar with collapsible groups, breadcrumbs, prev/next page nav, right-side table of contents
- Pagefind search with keyboard shortcut (`/` or `Ctrl+K`) and result snippets
- Expressive Code: syntax highlighting, copy button, terminal frames, file title annotations, line highlighting
- Multi-language code tabs (curl / Python / JavaScript) via Starlight `<Tabs>` component
- `<Aside>`, `<Steps>`, `<CardGrid>`, `<FileTree>`, `<Badge>` components used consistently
- Dark/light mode with OKLCH token mapping; system preference detection
- "Last updated" timestamps from Git; "Edit this page" GitHub links
- Sitemap, `robots.txt`, `<meta description>` per page, canonical URL
- Custom 404 page with Pagefind search widget
- `llms.txt` and `llms-full.txt` static files in `public/`
- API reference from committed `openapi.json` snapshot via `starlight-openapi`
- Broken link validation in CI via `starlight-links-validator`
- Cross-links: marketing site Features page to docs; docs header to marketing site

**Should have (moderate complexity, v15.0 scope):**
- OG image per page via `astro-og-canvas` (reusing marketing site pattern; Satori requires hex/RGB, not OKLCH)
- GeoLens-specific API auth section: explicit curl examples for JWT Bearer and `?api_key=` patterns
- OGC API / QGIS connection guide — no peer OSS docs site handles this for the on-prem GIS audience
- Docker Compose topology diagram (Mermaid or SVG) in install guide

**Defer to v15.1+:**
- Interactive "Try it out" API console (`starlight-openapi-navigator`)
- Versioning UI (`starlight-versions`) — trigger: when two major versions in active use simultaneously
- Algolia DocSearch — trigger: when Pagefind quality is insufficient at 500+ pages
- Contributor attribution, per-page sidebar "New" badges

**Anti-features to avoid:**
- Login-gated doc pages, inline comments/Disqus, animated hero sections in docs, full Algolia for v15.0

### Architecture Approach

The `docs/` subdirectory is a fully independent Astro project — own `package.json`, own `astro.config.mjs`, own `wrangler.toml`. The marketing site is untouched except for a path-ignore filter added to `.github/workflows/ci.yml`. A new `.github/workflows/deploy-docs.yml` handles the docs CI: `npm ci` in `docs/`, then `npx tsx scripts/fetch-openapi.ts` (non-fatal fetch of `openapi.json`), then `npm run build`, then `cloudflare/pages-action` deploying to project `geolens-docs`. Pagefind runs automatically as part of `astro build` — no configuration. `@astrojs/sitemap` generates the sitemap; `site: 'https://docs.getgeolens.com'` must be set at bootstrap.

**Major components:**

1. `docs/` — Starlight project (independent deploy unit, own `package.json`)
2. `docs/src/content/docs/` — all MDX/MD content pages (quickstart, user guide, admin guide)
3. `docs/src/content/openapi/geolens.json` — committed OpenAPI snapshot; refreshed by CI script pre-build
4. `docs/src/styles/custom.css` — OKLCH-to-`--sl-*` token bridge (~15 lines; no symlinks, no workspace)
5. `docs/scripts/fetch-openapi.ts` — pre-build script; exits 0 on failure so committed snapshot serves as fallback
6. `.github/workflows/deploy-docs.yml` — new CI workflow with path filter `docs/**`
7. `docs/public/_redirects` — Cloudflare Pages redirect file; stub created at Phase 1, populated on every rename

### Critical Pitfalls

Five pitfalls require Phase 1 action. The remaining six are addressed during content phases.

1. **Cloudflare Pages build contamination** — Without explicit path filtering, every push to `main` triggers both the marketing build and the docs build. Fix: set `rootDirectory = docs` in the new Pages project dashboard settings AND add `paths: ['docs/**']` in `deploy-docs.yml` AND add `paths-ignore: ['docs/**']` in `ci.yml`. Verify with a marketing-only push before writing any docs content.

2. **Design token drift** — The Starlight `custom.css` OKLCH mapping will silently diverge from `src/styles/global.css` when brand tokens change. Fix: add a CI script that greps the primary hue (~250) and accent lightness values in both files and fails on delta. Document the mapping with inline comments in `custom.css` so any PR touching brand tokens is visibly incomplete without a matching docs update.

3. **Satori OKLCH incompatibility** — The marketing site uses `oklch()` in its OG image templates. Pasting those values into the docs Satori template produces black images with no error. Fix: maintain a separate `og-colors.ts` constants file with hex/RGB equivalents of the GeoLens primary palette. Verify built `.png` files are not black after Phase 2 OG setup.

4. **Pagefind code-block index pollution** — Pagefind indexes Docker Compose YAML, curl examples, and config file stanzas as first-class content. "install postgres" returns YAML snippets before the install guide prose. Fix: wrap all `<Code>` blocks in `data-pagefind-ignore`; add `pagefind: false` frontmatter to the auto-generated API reference index page. Audit with `astro build && astro preview` after each content phase.

5. **Flat URL structure locks out versioning** — Shipping `/install`, `/admin` (no prefix) makes a future `/v2/` prefix require renaming every page and breaking all external links. Fix: use `/guides/install`, `/admin/overview`, `/api/reference` from the start. Add a `version: '1.x'` frontmatter field stub to every migrated page. Create `public/_redirects` at Phase 1.

Two additional pitfalls are medium-recovery-cost but longer-horizon:

6. **Dual-canonical indexing** — GitHub renders `backend/docs/install.md` and Google indexes it. After migration, the source files must be replaced with stub redirectors pointing to `docs.getgeolens.com`. This must happen in the same commit as the docs site going live — not later. Recovery is high-cost (months to deindex GitHub versions).

7. **OpenAPI schema drift** — The committed snapshot goes stale with every backend change. Fix: CI job in the geolens monorepo fetches `/api/openapi.json` after tests pass and opens a PR to `getgeolens-com` updating the snapshot, with an `oasdiff` breaking-change report in the PR body. For v15.0 launch, the snapshot must be taken from the current 1.0.0 backend and committed before Phase 3 (API Reference).

## Implications for Roadmap

Based on research, a 5-phase structure is recommended. Phases 1-2 are infrastructure; Phases 3-5 are content. No phase should begin before the prior phase's locked decisions are confirmed.

---

### Phase 1: Bootstrap & Infrastructure Lock
**Rationale:** All four "forever-wrong if skipped" decisions must be hard-set before content exists: URL structure, CF Pages multi-project config, `openapi.json` snapshot strategy, and design token bridge. Reversing any of these after content is written is high-cost.
**Delivers:**
- `docs/` subdirectory scaffolded (own `package.json`, `astro.config.mjs`, `tsconfig.json`, `wrangler.toml`)
- Two CF Pages projects configured: `getgeolens-com` (existing, path filter added) and `geolens-docs` (new, `rootDirectory: docs`)
- `deploy-docs.yml` CI workflow with path filter; `ci.yml` updated with `paths-ignore: ['docs/**']`
- `site: 'https://docs.getgeolens.com'` set in `astro.config.mjs`
- `docs/src/styles/custom.css` OKLCH token bridge written and verified
- `public/_redirects` stub created
- `public/robots.txt` pointing to sitemap
- GA4 same measurement ID installed in Starlight `head` config
- First successful deploy to `*.pages.dev` (custom domain comes later)

**Locked decisions this phase must hard-set:**
- URL structure: `/guides/install`, `/admin/overview`, `/api/reference` — no flat paths
- CF Pages: two projects, explicit `rootDirectory`, Build Watch Paths configured
- `openapi.json`: committed snapshot strategy confirmed (no live fetch in build)
- Token bridge: raw `customCss`, not `@astrojs/starlight-tailwind`

**Avoids:** Pitfalls 1 (CF contamination), 2 (token drift), 5 (flat URL), 7 (dual canonical — `site` config prevents relative canonicals), 10 (GA4 measurement ID)

**Research flag:** Standard — no further research needed. All patterns are fully documented.

---

### Phase 2: Brand, Shell & Design Verification
**Rationale:** Verify the visual identity and all shell components before any content exists. It is faster to fix token mapping and OG template issues on a skeleton site than after 30+ pages are written.
**Delivers:**
- Dark/light mode verified: primary blue (`--sl-color-accent` = oklch ~250) matches marketing site
- Starlight sidebar, breadcrumbs, prev/next, right-side ToC, responsive mobile layout confirmed
- OG image pipeline set up via `astro-og-canvas` with hex/RGB color constants (not OKLCH)
- `llms.txt` and `llms-full.txt` static files in `public/`
- Custom 404 page with Pagefind search widget and site nav
- `starlight-links-validator` added to build
- CI token-drift check script added

**Avoids:** Pitfall 3 (Satori OKLCH), Pitfall 9 (OG image build cost — use caching from day 1)

**Research flag:** OG image caching strategy may need a quick implementation check if the marketing site's `astro-og-canvas` approach differs in structure. Otherwise standard.

---

### Phase 3: OpenAPI Snapshot & API Reference
**Rationale:** The API reference depends on a committed `openapi.json` that must exist before the reference pages can be generated. This phase isolates that dependency so content phases don't block on it.
**Delivers:**
- `docs/scripts/fetch-openapi.ts` script (non-fatal on failure)
- `docs/src/content/openapi/geolens.json` committed snapshot taken from live 1.0.0 backend
- `starlight-openapi` configured in `astro.config.mjs` with `base: 'api'`
- API reference sidebar section verified building and rendering correctly
- Authentication intro page hand-authored: JWT Bearer + `?api_key=` curl examples
- OGC API endpoints called out in a dedicated section
- `pagefind: false` set on the auto-generated API reference index page

**Avoids:** Pitfalls 4 (schema drift — snapshot committed), 5 (code-block search pollution)

**Requires before start:** Access to a running 1.0.0 GeoLens instance to produce the initial snapshot.

**Research flag:** `oasdiff` CI integration for auto-PR on schema changes is a medium-complexity addition. Can be deferred to post-launch but should be planned in this phase.

---

### Phase 4: Content — Quickstart & Install Guide
**Rationale:** The quickstart is the highest-value content for OSS adoption. A new visitor arriving at `docs.getgeolens.com` first needs to know how to run GeoLens — this is the content that converts GitHub stars into deployments.
**Delivers:**
- `docs/src/content/docs/quickstart/install.md` — migrated and expanded from `geolens/backend/docs/install.md`
- Docker Compose topology diagram (Mermaid or SVG)
- `<FileTree>` of Compose directory structure
- Multi-language code tabs for curl/Python/JS on authentication examples
- `<Steps>` numbered sequences for install flow
- `geolens/backend/docs/install.md` replaced with stub pointer (canonical migration)
- Broken link check passes

**Migration checklist (every file):** `title` frontmatter required; no `.md` cross-references; no `github.com/raw` image URLs; all code fences have explicit language IDs; `version: '1.x'` frontmatter field added.

**Avoids:** Pitfalls 6 (markdown migration breakage), 7 (dual canonical — source file replaced)

**Research flag:** Standard patterns. Content authoring, no technical research needed.

---

### Phase 5: Content — User Guide, Admin Guide & Marketing Cross-links
**Rationale:** User guide and admin guide are the reference depth that retains users after install. The marketing Features page (deferred Phase 216) is completed here, with cross-links from `getgeolens.com` into the docs site.
**Delivers:**
- `docs/src/content/docs/user-guide/` — search, dataset detail, map builder, collections, exports, AI chat
- `docs/src/content/docs/admin-guide/` — migrated and expanded from `geolens/backend/docs/admin.md` (RBAC, OAuth, settings, backups, infrastructure dashboard)
- `geolens/backend/docs/admin.md` replaced with stub pointer
- New Features page on `getgeolens.com` (marketing-site half of deferred Phase 216) with cross-links into docs
- Docs header with `getgeolens.com` navigation link
- Sitemap submitted to Google Search Console
- All internal links pass `starlight-links-validator`

**Avoids:** Pitfall 6 (migration checklist applied), Pitfall 7 (admin.md stub), Pitfall 11 (link rot — `_redirects` baseline from Phase 1)

**Research flag:** Standard patterns for content authoring. Features page component structure may reference existing marketing site components.

---

### Phase Ordering Rationale

- Infrastructure before content is non-negotiable: URL structure, CF project isolation, and the `site` config are "wrong forever if not set first" — they affect every page's canonical URL and every external link shared after launch.
- Brand verification before content avoids discovering a token mapping error after 30 pages are written and OG images are generated for all of them.
- API reference phase isolated because it has a hard prerequisite (committed snapshot) and its own plugin configuration that can be validated independently before content phases start.
- Quickstart before user/admin guides because it is the highest-impact content for adoption and it contains the most migration complexity (Docker topology diagram, multi-platform install steps).
- Marketing Features page in Phase 5 (not Phase 1) because it cross-links into docs content that does not exist until Phase 4-5. Building it before docs content creates broken links.

### Research Flags

**Needs research-phase during planning:** None — all patterns are well-documented with official sources. Research is complete.

**Phases with standard patterns (skip research-phase):**
- Phase 1 (Bootstrap): CF Pages monorepo, Starlight config, GitHub Actions — all fully documented.
- Phase 2 (Brand/Shell): Starlight CSS theming, `astro-og-canvas` — marketing site already uses this pattern.
- Phase 3 (API Reference): `starlight-openapi` config reference is complete and verified.
- Phase 4-5 (Content): MDX authoring with Starlight components — no research needed.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Starlight 0.38.4 + Astro 6 peer dep confirmed via GitHub releases and Context7. `starlight-openapi` 0.25.0 peer dep verified. All version compatibility confirmed. |
| Features | HIGH | Verified via Starlight official docs, Context7, and multiple live OSS docs site comparisons (Supabase, FastAPI, Cloudflare). MVP feature list is complete and scoped. |
| Architecture | HIGH | CF Pages monorepo pattern confirmed via official Cloudflare docs. Build isolation via path filters confirmed. `customCss` token bridge confirmed via Starlight official docs. All anti-patterns sourced. |
| Pitfalls | HIGH (most) / MEDIUM (OG caching at scale) | 11 pitfalls documented with concrete recovery costs. OG image caching at 200+ pages is MEDIUM confidence — performance benchmarks are inference-based, not empirical for this exact setup. |

**Overall confidence:** HIGH

### Gaps to Address

Two gaps require user decisions before requirements are written:

1. **`OPENAPI_URL` CI variable value** — The `fetch-openapi.ts` script reads `process.env.OPENAPI_URL`. This must point to a stable, reachable URL for the GeoLens production or staging API. Decision needed: which GeoLens instance URL should be used as the live fetch target in CI, or should the initial snapshot be committed manually and the CI fetch added post-launch?

2. **Features page scope on `getgeolens.com`** — Phase 5 includes completing deferred Phase 216 (Features page on the marketing site). The research does not define what content, screenshots, or component design that page requires. This may need a separate design pass before Phase 5 can be planned.

Three gaps are low-stakes and can be resolved during implementation:

3. **`llms-full.txt` generation approach** — Static file vs dynamic `src/pages/llms-full.txt.ts` endpoint. Static is sufficient for v15.0 but requires manual updates. Decide at Phase 2.

4. **`oasdiff` CI integration scope** — The backend CI job that auto-PRs snapshot updates requires touching the geolens monorepo CI (separate repo). Decide whether this is in v15.0 scope or deferred.

5. **Demo site link in docs** — The user guide should link to `demo.getgeolens.com` for live exploration. Confirm the demo subdomain is live and stable before adding the link in Phase 5.

## Open Questions for User Sign-Off Before Requirements

1. **What URL does the CI `fetch-openapi.ts` script target?** Options: (a) manual initial commit only, CI fetch disabled until a staging URL is available; (b) `https://demo.getgeolens.com/api/openapi.json` if the demo instance is stable; (c) a dedicated staging/preview URL. This affects Phase 3 scope.

2. **Is the `oasdiff` auto-PR job in scope for v15.0?** It requires changes to the geolens monorepo CI (separate repo). If yes, it belongs in Phase 3. If no, the snapshot update process is manual.

3. **What is the Features page design on `getgeolens.com`?** Phase 5 includes this. Is it a new full page, or a section added to an existing page? Does it need new screenshot assets?

4. **Is `demo.getgeolens.com` live and stable for docs links?** User guide pages should link to a live demo. If not stable, docs links should point to GitHub or omit the demo reference.

## Top Risks for User Acknowledgment Before Requirements

1. **CF Pages build contamination (HIGH probability)** — Without explicit path filter configuration in both the CF dashboard and GitHub Actions, every push triggers both builds. The docs build runs `fetch-openapi.ts` on every marketing push, creating an unnecessary live API dependency on marketing deployments. Mitigation: Phase 1 must configure path filters before any pushes to `main`. Verify with a test push.

2. **Design token drift post-launch (MEDIUM probability, HIGH visual impact)** — The `custom.css` OKLCH mapping is a manual copy. The next brand update will touch `src/styles/global.css` without triggering a docs update. The failure is invisible in CI — both sites build, but docs drift toward a different accent color. Mitigation: CI diff script enforcing matching primary hue values. Must be added in Phase 1, not retrofitted.

3. **Dual-canonical indexing recovery cost (LOW probability if handled immediately, HIGH cost if delayed)** — Google can take 2-3 months to deindex `github.com/geolens/blob/main/backend/docs/install.md` after it is replaced with a stub. The only mitigation is to replace the source files at the same time the docs site goes live. If this is delayed, the recovery window grows substantially.

4. **Satori OG image silent failure (HIGH probability if not addressed proactively)** — Marketing site OG templates use `oklch()`. If those are copy-pasted into docs OG templates, built images will be black/blank with no error raised. Mitigation: dedicated `og-colors.ts` constants file with hex/RGB equivalents, checked in Phase 2.

5. **Pagefind search noise at content completion (MEDIUM probability)** — A docs site with Docker Compose stanzas, curl examples, and API response bodies produces search results dominated by code fragments. This degrades the primary search-to-find-content UX. Mitigation: `data-pagefind-ignore` on all `<Code>` blocks established as a convention in Phase 2 and applied in all content phases.

## Sources

### Primary (HIGH confidence)
- `/withastro/starlight` (Context7) — configuration, customCss, Pagefind integration, component reference, Tailwind layer order
- https://github.com/withastro/starlight/releases — confirmed latest version 0.38.4, Astro 6 peer dep
- https://github.com/HiDeoo/starlight-openapi — version 0.25.0, remote/local schema support, peer deps
- https://starlight-openapi.vercel.app/configuration/ — configuration options confirmed
- https://developers.cloudflare.com/pages/configuration/monorepos/ — Build System V2 requirement, 5-project limit, Build Watch Paths
- https://starlight.astro.build/guides/css-and-tailwind/ — Tailwind 4 layer order, customCss, @astrojs/starlight-tailwind
- https://starlight.astro.build/reference/frontmatter/ — required `title` field confirmed
- https://docs.astro.build/en/reference/configuration-reference/ — `site` config canonical URL generation
- https://developers.cloudflare.com/pages/configuration/redirects/ — `_redirects` file format

### Secondary (MEDIUM confidence)
- https://hideoo.dev/notes/starlight-og-images/ — OG image pattern for Starlight (HiDeoo, Starlight maintainer)
- https://pagefind.app/docs/search-ui/ — Pagefind UI and keyboard shortcut behavior
- https://github.com/withastro/starlight/issues/2824 — `data-pagefind-ignore` and build-only constraint
- https://www.oasdiff.com/ — breaking change detection for OpenAPI snapshot CI job
- https://www.analyticsmania.com/post/subdomain-tracking-with-google-analytics-and-google-tag-manager/ — GA4 subdomain same-measurement-ID requirement

### Tertiary (LOW confidence)
- https://ainoya.dev/posts/astro-ogp-build-cache/ — Satori build-time OG image caching (performance estimate at 200+ pages is inference-based)
- https://github.com/withastro/starlight/discussions/957 — versioning retrofit pain (community discussion, not official docs)

---
*Research completed: 2026-04-25*
*Ready for roadmap: yes*
