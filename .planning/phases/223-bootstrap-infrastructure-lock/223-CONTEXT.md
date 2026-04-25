# Phase 223: Bootstrap & Infrastructure Lock - Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a deployable Starlight skeleton at a `*.pages.dev` URL **and** at the custom `docs.getgeolens.com` domain, with all infrastructure decisions hard-set so no content phase can inherit a wrong canonical URL, a flat URL, or a cross-contaminating build. Scope is infrastructure scaffolding only — content (BRAND-01 full token mapping, sidebar labels, Inter font, install/admin guides) belongs to later phases.

</domain>

<decisions>
## Implementation Decisions

### CI / Deploy Workflow
- **D-01**: Single combined workflow file `docs/.github/workflows/docs-ci.yml` running `astro check` → `npm run build` → `cloudflare/pages-action@v1`. Mirrors marketing site's `ci.yml` pattern; no split between check-only and deploy.
- **D-02**: Symmetric path filtering. `docs-ci.yml` uses `paths: ['docs/**', '.github/workflows/docs-ci.yml']`. Existing marketing `.github/workflows/ci.yml` gets `paths-ignore: ['docs/**']` added. A PR touching both subtrees triggers both workflows.
- **D-03**: Cloudflare Pages project name is **`getgeolens-docs`** (matches the marketing project's `getgeolens-com` naming pattern).
- **D-04**: `docs/wrangler.toml` is committed alongside the docs subtree. CF Pages dashboard sets `rootDirectory: docs`; the project picks up `docs/wrangler.toml` from there. Configuration lives in-repo, not dashboard-only.
- **D-05**: Reuse existing `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` GitHub secrets (already used by marketing `ci.yml`). No new secrets.

### Custom Domain & Visibility
- **D-06**: `docs.getgeolens.com` DNS / CF Pages custom-domain attachment happens in **this phase** (per DEPLOY-03). TLS auto-provisioning verified via manual `curl -I https://docs.getgeolens.com` + screenshot in phase summary. No automated CI cert probe at this stage.
- **D-07**: During bootstrap, the site is publicly reachable but **not indexable**:
  - `docs/public/robots.txt` ships with `User-agent: *` / `Disallow: /`.
  - Site-wide `<meta name="robots" content="noindex, nofollow">` injected via Starlight `head` config.
  - Both flip in Phase 228 (SEO-03) when content is complete and the sitemap is submitted to Google Search Console.
- **D-08**: Belt-and-suspenders posture (robots.txt + noindex meta) is intentional — robots.txt blocks well-behaved crawlers, noindex catches Bingbot/others that occasionally index disallowed URLs as bare titles.

### Skeleton Content & Brand Depth
- **D-09**: `docs/src/styles/custom.css` ships in this phase as a **minimal placeholder accent only** — three lines mapping `--sl-color-accent`, `--sl-color-accent-low`, `--sl-color-accent-high` to GeoLens primary blue (~hue 250), in both light and dark `[data-theme]` blocks. The full Starlight 50–950 scale, surface tokens, and CI token-drift check are Phase 224's BRAND-01 / BRAND-04 scope.
- **D-10**: Homepage is a **stub MDX page** (`src/content/docs/index.mdx`) with: short "Documentation in progress" notice + a planned-URL TOC bullet list pointing to the `/guides/install`, `/guides/admin`, `/guides/api` paths. Not the Starlight `<Hero>` splash (Phase 224 reworks the landing page anyway). Anchors the URL structure decision visibly from day 1.
- **D-11**: Empty top-level **sidebar groups declared upfront** in `astro.config.mjs`: Quickstart, User Guide, Admin Guide, API Reference — all with `/guides/` prefix paths. Phase 224's SHELL-01 just adds nav labels and content references; cannot accidentally regress to flat URLs.
- **D-12**: **Inter font load deferred to Phase 224** (BRAND-02 owns `@fontsource-variable/inter`). Bootstrap uses Starlight's default font stack. Clean phase boundary.
- **D-13**: Default theme: leave Starlight's default light/dark behavior (system-preference auto). No explicit theme override in 223. Phase 224 verifies dark/light parity.

### `_redirects` Stub
- **D-14**: `docs/public/_redirects` ships with the **minimal MIG-02 set**: `/install`, `/admin`, `/api` redirected to their `/guides/` equivalents. `/quickstart` is **explicitly excluded** from the docs `_redirects` — it's owned by the marketing site (`HeroSection.astro`, `Nav.astro`, `QuickstartTeaser.astro` already link to it). Claiming it on docs would conflict.
- **D-15**: Each legacy path gets **three rules** to handle every variant: `/foo` → `/guides/foo`, `/foo/` → `/guides/foo`, `/foo/*` → `/guides/foo/:splat`. All 301s.
- **D-16**: Maintenance convention: `_redirects` opens with a comment block stating "every page rename adds a 301 here". Phase 227's MIG-03 update to `CONTRIBUTING.md` (geolens monorepo) documents the convention more formally. **No CI rename-detection check** at this stage — premature complexity for unproven need.

### Scope Bounds (in this phase)
- **D-17**: `astro.config.mjs` sets `site: 'https://docs.getgeolens.com'` (BOOT-04) — required for canonical URL resolution.
- **D-18**: `@astrojs/sitemap` integration installed and configured. Auto-generates `sitemap-index.xml`. Submission to Google Search Console deferred to Phase 228.
- **D-19**: ~~GA4 same-Measurement-ID strategy (SEO-06)~~ — **DEFERRED to Phase 228 (2026-04-25)**. Research confirmed marketing site has NO GA4 installed today (zero `gtag`/`G-`/`googletagmanager` hits in `getgeolens.com`). SEO-06 has no ID to mirror, and shipping analytics on a noindexed shell adds no value. ROADMAP.md updated: SEO-06 moved from Phase 223 to Phase 228 requirements (clusters with SEO-03 sitemap submission, robots.txt flip, noindex removal, and a marketing-side GA4 install).
- **D-20**: `npx astro check` runs in `docs-ci.yml` (CI-02). Astro version pinned to ^6.1.x in `docs/package.json` (BOOT-02), matching marketing's `^6.1.3` pin.

### Out of Scope for Phase 223 (deferred to later phases or out entirely)
- **GA4 Measurement ID injection (SEO-06)** → Phase 228. Deferred 2026-04-25 because the marketing site has no GA4 installed today; SEO-06 will be installed on BOTH sites in Phase 228 alongside the noindex flip and sitemap submission. ROADMAP.md updated.
- Full OKLCH 50–950 token mapping → Phase 224 (BRAND-01)
- Inter font installation → Phase 224 (BRAND-02)
- CI token-drift check between `global.css` ↔ `custom.css` → Phase 224 (BRAND-04)
- Sidebar labels / nav content / `lastUpdated` / edit-this-page links → Phase 224 (SHELL-01..05)
- Pagefind search configuration / shortcuts → Phase 224 (SEARCH-01..03)
- Custom 404 page → Phase 224 (SHELL-03)
- Cross-site nav links between marketing and docs → Phase 224 (SHELL-05)
- `llms.txt` → Phase 224 (SEO-04)
- OG image pipeline → Phase 228 (SEO-02)
- `openapi.json` snapshot, `starlight-openapi` plugin, fetch script → Phase 225 (API-01..05)
- Sitemap submission to GSC → Phase 228 (SEO-03)

### Claude's Discretion
- Exact contents of `docs/wrangler.toml` (mirror marketing pattern: project name + `pages_build_output_dir = "dist"`)
- Exact noindex meta injection mechanism (Starlight `head` config array vs custom `<head>` component)
- `.nvmrc` strategy: reuse repo-root `.nvmrc` if it covers `>=22.12.0`, otherwise add `docs/.nvmrc`
- Whether to commit a placeholder `docs/src/content/openapi/.gitkeep` for Phase 225 readiness (cosmetic)
- Exact stub homepage copy (research summary's "GeoLens v1.0 documentation — coming soon" tone is fine)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Specs
- `.planning/REQUIREMENTS.md` §Bootstrap & Infrastructure (BOOT-01..04), §Deploy & Hosting (DEPLOY-01..04), §SEO (SEO-05, SEO-06), §Migration (MIG-02), §CI (CI-02) — locked acceptance criteria for this phase
- `.planning/PROJECT.md` §Current Milestone (v15.0 Documentation Site) — milestone context and target features
- `.planning/ROADMAP.md` §Phase 223 — goal, depends-on, success criteria

### v15.0 Research Outputs
- `.planning/research/SUMMARY.md` — synthesized v15.0 research; Phase 1 (Bootstrap) section calls out the four "forever-wrong if skipped" decisions and the five Phase-1-actionable pitfalls
- `.planning/research/STACK.md` — Starlight 0.38.4, Astro 6 peer dep, `customCss` token bridge, CF Pages monorepo pattern, `starlight-openapi` 0.25.0 (for Phase 225 prep)
- `.planning/research/ARCHITECTURE.md` — `docs/` subdirectory as independent Astro project, file layout, multi-project CF Pages config, build isolation
- `.planning/research/PITFALLS.md` — CF Pages build contamination, design token drift, Satori OKLCH, Pagefind code-block index pollution, flat URL lock-out (all preventable in this phase)
- `.planning/research/FEATURES.md` — feature scope across the milestone (this phase delivers infrastructure for; not the features themselves)

### External-Repo Reference Files (parity targets)
The docs site lives in `getgeolens.com` (a separate repo at `/Users/ishiland/Code/getgeolens.com`). Plans must mirror these patterns:
- `getgeolens.com/astro.config.mjs` — current marketing config; reference for `site` + sitemap integration shape
- `getgeolens.com/wrangler.toml` — mirror project-level config style for `docs/wrangler.toml`
- `getgeolens.com/.github/workflows/ci.yml` — pattern for `docs-ci.yml` and the `paths-ignore` patch on this same file
- `getgeolens.com/src/styles/global.css` — source-of-truth OKLCH primary blue values to mirror in `docs/src/styles/custom.css` (only `--sl-color-accent` slots in this phase)
- `getgeolens.com/package.json` — Node `>=22.12.0` engine pin to match
- `getgeolens.com/src/components/home/HeroSection.astro`, `src/components/layout/Nav.astro` — confirm marketing owns `/quickstart` (do NOT add `/quickstart` redirect on docs)

### Anti-Patterns / Out of Scope (do not introduce)
- `.planning/REQUIREMENTS.md` §Out of Scope — Mintlify/Docusaurus/VitePress (rejected); `@astrojs/starlight-tailwind` plugin (rejected); npm/pnpm workspaces (rejected); live `openapi.json` fetch at build (rejected)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (from `getgeolens.com/` external repo)
- **`getgeolens.com/.github/workflows/ci.yml`** — full template for `docs-ci.yml`: same `actions/setup-node@v4` + `node-version-file: .nvmrc`, same `cloudflare/pages-action@v1` invocation. Copy structure, change `projectName` and `directory` and add path filter.
- **`getgeolens.com/wrangler.toml`** — 3-line file. Mirror exactly with project name change.
- **`getgeolens.com/astro.config.mjs`** — current sitemap integration pattern (`sitemap({ filter: (page) => !page.includes('/og/') })`). Docs config follows the same shape with `site: 'https://docs.getgeolens.com'`.
- **`getgeolens.com/src/styles/global.css`** — OKLCH primary scale already authored. Phase 223's minimal `custom.css` cherry-picks the `--primary-500` / `--primary-600` / `--primary-700` values for Starlight's `--sl-color-accent` slots only.

### Established Patterns
- Marketing CI uses a single workflow with sequential check → build → a11y → deploy. **Mirror in `docs-ci.yml`** (without a11y at Phase 223; A11Y-05/06/07 are Phase 228 scope).
- Cloudflare Pages action with API token + account ID secrets is the proven deploy primitive. **Reuse**.
- Astro `site` config drives canonical URLs and sitemap entries. **Set in this phase, never change after**.

### Integration Points
- New CF Pages project (`getgeolens-docs`) created in CF dashboard with `rootDirectory: docs`, then GitHub repo connected, Build Watch Paths set to `docs/**`.
- Existing marketing `ci.yml` requires a one-line edit: add `paths-ignore: ['docs/**']` to the `on.push` and `on.pull_request` triggers.
- `docs.getgeolens.com` DNS record auto-managed by CF Pages custom-domain attachment (the apex `getgeolens.com` is already on Cloudflare).

### Marketing-Site Routes That Affect Docs Decisions
- **`/quickstart` is owned by marketing**, not docs. `HeroSection.astro:23`, `QuickstartTeaser.astro:21`, `Nav.astro:9` all link to it. Docs `_redirects` MUST NOT claim `/quickstart` — would create a route conflict on cross-linking.

</code_context>

<specifics>
## Specific Ideas

- **Visible URL anchor at bootstrap**: stub homepage TOC and empty sidebar groups both reference the planned `/guides/install`, `/guides/admin`, `/guides/api` URL pattern. Anyone (human or future agent) opening the deploy sees the URL structure is locked, even if no content exists yet.
- **noindex insurance during bootstrap**: belt-and-suspenders (robots.txt + meta tag) is the explicit posture. Recovery from accidental indexing of a half-built site is high-cost; prevention is one config line.
- **Naming consistency**: `getgeolens-docs` mirrors `getgeolens-com`. Keeps both CF Pages projects discoverable as a pair in the dashboard.

</specifics>

<deferred>
## Deferred Ideas

- **CI rename-detection check** — would fail PR if a content path disappeared without a matching `_redirects` entry. Considered for `_redirects` maintenance; deferred. Comment-header convention is sufficient until proven otherwise.
- **Cross-site redirect** from marketing `/quickstart` → `docs.getgeolens.com/guides/install` once Phase 226 ships. Not Phase 223 scope; surface during Phase 226 planning if marketing's `/quickstart` page is to be deprecated rather than kept as a teaser.
- **Automated TLS / cert-renewal monitoring** — production reliability concern, not a launch concern. CF auto-renews; manual check at bootstrap is sufficient.
- **`oasdiff` CI integration** for OpenAPI snapshot drift detection — explicitly deferred per `.planning/REQUIREMENTS.md` §Future Requirements (OASDIFF-01).
- **Versioned docs** (`starlight-versions`) — explicitly deferred per `.planning/REQUIREMENTS.md` §Future Requirements (VERSION-01); the `/guides/` URL prefix in this phase is the structural prerequisite for retrofitting versioning later.

</deferred>

---

*Phase: 223-bootstrap-infrastructure-lock*
*Context gathered: 2026-04-25*
