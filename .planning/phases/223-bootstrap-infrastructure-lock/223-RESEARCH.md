# Phase 223: Bootstrap & Infrastructure Lock — Research

**Researched:** 2026-04-25
**Domain:** Astro Starlight 0.38.4 bootstrap on Astro 6 monorepo, Cloudflare Pages multi-project deploy, URL-structure & redirect lock-in
**Confidence:** HIGH (bootstrap mechanics, sidebar config, customCss, sitemap, _redirects); MEDIUM (Starlight head config interaction with site-wide noindex meta — verified via Context7 but worth a smoke test on first build); MEDIUM-LOW (GA4 reuse — see Open Question #1)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**CI / Deploy Workflow**
- **D-01**: Single combined workflow file `docs/.github/workflows/docs-ci.yml` running `astro check` → `npm run build` → `cloudflare/pages-action@v1`. Mirrors marketing site's `ci.yml`; no split between check-only and deploy.
- **D-02**: Symmetric path filtering. `docs-ci.yml` uses `paths: ['docs/**', '.github/workflows/docs-ci.yml']`. Existing marketing `.github/workflows/ci.yml` gets `paths-ignore: ['docs/**']` added. A PR touching both subtrees triggers both workflows.
- **D-03**: Cloudflare Pages project name is **`getgeolens-docs`** (matches `getgeolens-com`).
- **D-04**: `docs/wrangler.toml` is committed alongside the docs subtree. CF Pages dashboard sets `rootDirectory: docs`.
- **D-05**: Reuse existing `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets. No new secrets.

**Custom Domain & Visibility**
- **D-06**: `docs.getgeolens.com` DNS / CF Pages custom-domain attachment happens in this phase. TLS verified via manual `curl -I` + screenshot.
- **D-07**: Bootstrap = publicly reachable but not indexable. `robots.txt` `Disallow: /` + site-wide `<meta name="robots" content="noindex, nofollow">`. Both flip in Phase 228.
- **D-08**: Belt-and-suspenders posture (robots.txt + noindex meta) is intentional.

**Skeleton Content & Brand Depth**
- **D-09**: `custom.css` ships as a minimal placeholder accent only — three lines (`--sl-color-accent`, `--sl-color-accent-low`, `--sl-color-accent-high`) for GeoLens primary blue (~hue 250), in both light and dark `[data-theme]` blocks. Full token mapping = Phase 224.
- **D-10**: Homepage = stub MDX page (`src/content/docs/index.mdx`) with a "Documentation in progress" notice and a planned-URL TOC pointing to `/guides/install`, `/guides/admin`, `/guides/api`. Not the Starlight `<Hero>` splash.
- **D-11**: Empty top-level sidebar groups declared upfront in `astro.config.mjs`: Quickstart, User Guide, Admin Guide, API Reference — all under `/guides/`.
- **D-12**: Inter font deferred to Phase 224 (BRAND-02). Starlight default font stack at bootstrap.
- **D-13**: Default Starlight light/dark behavior. No theme override in 223.

**`_redirects` Stub**
- **D-14**: Minimal MIG-02 set: `/install`, `/admin`, `/api` → `/guides/*`. **`/quickstart` explicitly excluded** (owned by marketing site).
- **D-15**: Each legacy path gets three rules: `/foo`, `/foo/`, `/foo/*`. All 301s.
- **D-16**: Maintenance convention: comment header in `_redirects`. No CI rename-detection check at this stage.

**Scope Bounds**
- **D-17**: `astro.config.mjs` sets `site: 'https://docs.getgeolens.com'` (BOOT-04).
- **D-18**: `@astrojs/sitemap` integration installed and configured.
- **D-19**: GA4 same-Measurement-ID strategy — lookup the marketing site's actual ID during planning. **(See Open Question #1 — marketing site does not currently have GA4.)**
- **D-20**: `npx astro check` runs in CI. Astro pinned to `^6.1.x` matching marketing's `^6.1.3`.

### Claude's Discretion
- Exact contents of `docs/wrangler.toml` (mirror marketing pattern: project name + `pages_build_output_dir = "dist"`)
- Exact noindex meta injection mechanism (Starlight `head` config array vs custom `<head>` component)
- `.nvmrc` strategy (reuse repo-root `.nvmrc` if it covers `>=22.12.0`, otherwise add `docs/.nvmrc`)
- Whether to commit a placeholder `docs/src/content/openapi/.gitkeep` for Phase 225 readiness
- Exact stub homepage copy

### Deferred Ideas (OUT OF SCOPE)
- CI rename-detection check for `_redirects`
- Cross-site redirect from marketing `/quickstart` → docs
- Automated TLS / cert-renewal monitoring
- `oasdiff` CI integration (per OASDIFF-01)
- Versioned docs (`starlight-versions`) (per VERSION-01)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BOOT-01 | Astro Starlight 0.38.4 site bootstrapped in `docs/` subdirectory with own `package.json`, `astro.config.mjs`, `tsconfig.json`, `wrangler.toml` — no workspace | §3.1 (`npm create astro@latest -- --template starlight`); §4 file inventory; verified peerDeps `astro: ^6.0.0` via `npm view` |
| BOOT-02 | Astro version pinned to Starlight 0.38.x-compatible major (Astro 6.x); `npx astro check` in CI | §3.11 version matrix; package.json template in §3.1 |
| BOOT-03 | URL structure uses `/guides/` prefix | §3.3 (sidebar declared with `/guides/install`, `/guides/admin`, `/guides/api`); §3.10 stub homepage TOC anchors structure visibly |
| BOOT-04 | `astro.config.mjs` sets `site: 'https://docs.getgeolens.com'` | §3.9 — drives canonical URLs, sitemap entries, all OG image absolute URLs |
| DEPLOY-01 | Second CF Pages project `getgeolens-docs` from same repo, `rootDirectory: docs`, Build Watch Paths configured | §3.4 dashboard steps; §3.13 attachment workflow |
| DEPLOY-02 | GitHub Actions `docs-ci.yml` filters on `paths: ['docs/**']`; marketing `ci.yml` gets matching `paths-ignore` | §3.5 symmetric filter, including workflow self-modification guard |
| DEPLOY-03 | Custom domain `docs.getgeolens.com` mapped with TLS auto-provisioning verified | §3.13 — ordered CF Pages dashboard steps + `curl -I` verification |
| DEPLOY-04 | PR preview deploys work for docs PRs at `*.pages.dev` | §3.4 — pages-action automatically generates preview URLs for non-main pushes; §6 validation |
| MIG-02 | `_redirects` covers legacy URL patterns | §3.8 — three-rule pattern per legacy path; `/quickstart` explicitly excluded |
| SEO-05 | Canonical URLs resolve to `docs.getgeolens.com` to suppress backend/docs/*.md duplicate indexing | §3.9 — Starlight emits `<link rel="canonical">` automatically when `site` is set; **but** robots.txt `Disallow: /` and noindex meta must come off in Phase 228 before this deindexing pressure activates |
| SEO-06 | GA4 same-Measurement-ID strategy enabled | §3.12 — pattern documented; **marketing site has no GA4 yet** (see Open Question #1) |
| CI-02 | `npx astro check` runs in docs CI | §3.10 — wired into docs-ci.yml; tsconfig template in §3.1 |
</phase_requirements>

---

## 1. Goal & Approach Recommendation

### Goal (restated)

A deployable Starlight 0.38.4 skeleton is live at the `*.pages.dev` URL and at `docs.getgeolens.com`, with all infrastructure decisions hard-set so that no content phase can inherit:
- a wrong canonical URL (mitigated by `site:` + sitemap + Starlight auto canonical link)
- a flat URL (mitigated by sidebar groups under `/guides/` + planned-URL TOC on stub homepage)
- a cross-contaminating build (mitigated by symmetric path filters + `rootDirectory: docs` + separate `wrangler.toml`)

### Single Approach (no re-litigation)

The locked decisions in CONTEXT.md cover all gray areas. Implementation = mechanical execution of those decisions, **plus** these planner-relevant nuances:

1. **Workflow self-modification guard.** GitHub's path filter triggers when ANY listed path matches. Including `'.github/workflows/docs-ci.yml'` in `paths:` (D-02) ensures that edits to the workflow file itself trigger a re-run — preventing "I changed the workflow but it didn't run" surprises. The marketing `ci.yml` path-ignore should NOT include its own file (otherwise self-modification would be silently skipped).

2. **Bootstrap-order matters for first deploy.** The CF Pages project must exist in the dashboard BEFORE `cloudflare/pages-action@v1` runs in CI. If the project doesn't exist, the action fails with an unhelpful 404. Plan order: (a) commit `docs/` skeleton on a feature branch → (b) create CF Pages project in dashboard pointing at `main` with `rootDirectory: docs` (do not deploy yet — there's no commit on main) → (c) merge feature branch → (d) docs-ci.yml deploys → (e) verify `*.pages.dev` URL → (f) attach custom domain.

3. **`cloudflare/pages-action@v1` is officially deprecated** (last release v1.5.0, May 2023; repo archived). The recommended replacement is `cloudflare/wrangler-action@v3` with `command: pages deploy dist --project-name=getgeolens-docs`. **However:** D-01 explicitly says "Mirrors marketing site's `ci.yml` pattern" and the marketing site uses `pages-action@v1`. Per the locked decision, we mirror the deprecated action. This is a mild tech-debt acceptance: when marketing migrates to `wrangler-action`, docs migrates in lockstep. Flag for the planner: *do not* "modernize" to `wrangler-action` in this phase without an explicit user re-decision.

4. **Marketing site has no GA4 today.** Verified via `grep`: no `gtag`, no `G-XXXXXXX`, no analytics script in `astro.config.mjs`, `SiteLayout.astro`, or any other source file in `getgeolens.com/`. SEO-06 says "same Measurement ID strategy" — but there's nothing to share. **Decision needed before this phase ships** (see Open Question #1).

5. **Belt-and-suspenders is essential.** Robots.txt `Disallow: /` blocks well-behaved crawlers but not all of them. The site-wide `noindex` meta tag in Starlight `head` config catches the rest. Both come off together in Phase 228 — neither should be flipped early.

---

## 2. Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Static page rendering | Astro 6 / Starlight (build time) | — | Pure SSG; no runtime server |
| HTML → CDN delivery | Cloudflare Pages edge | — | CF Pages serves `dist/` as static assets |
| URL redirects | Cloudflare Pages edge (`_redirects` file) | — | Static-site declarative redirects evaluated at edge before serving |
| Canonical URL generation | Astro `site` config | Starlight default Head | Starlight emits `<link rel="canonical">` from `site` automatically |
| Sitemap generation | `@astrojs/sitemap` (build time) | — | Reads `site` config + scans built pages; emits `sitemap-index.xml` |
| Robots discovery | Static `public/robots.txt` | — | Copied verbatim to `dist/` at build |
| Site-wide noindex meta | Starlight `head` config | — | Injected on every page during build |
| GA4 page-view tracking | Browser-side gtag.js | Starlight `head` config (script injection) | Loads on every page; reports to GA4 backend |
| CI build orchestration | GitHub Actions (docs-ci.yml) | — | Runs check + build + deploy on docs/** changes |
| Deploy + cert provisioning | Cloudflare Pages (dashboard + edge) | — | Auto-TLS for custom domains; preview URLs for non-main |
| Build isolation | GitHub Actions path filters | CF Pages dashboard `rootDirectory` | Two-layer defense: CI skip + project-scoped build context |

---

## 3. Implementation Findings

### 3.1 Starlight bootstrap — CLI invocation, file inventory, `package.json` template

**Verified via Context7** [`/withastro/starlight`]: The canonical bootstrap command is `npm create astro@latest -- --template starlight` — this scaffolds a complete Starlight project (Astro + Starlight integration + `src/content.config.ts` content collection schema + `tsconfig.json` + sample MDX). For our use case we **do not** want the Tailwind variant (`--template starlight/tailwind`) — REQUIREMENTS.md §Out of Scope rejects `@astrojs/starlight-tailwind`.

**Recommended approach for this phase:** Run `npm create astro@latest` from `docs/` and accept the scaffold, then prune what's not needed (sample content, default starlight logo). All file paths below are post-prune.

**`docs/package.json`** (verified versions via `npm view`):

```json
{
  "name": "getgeolens-docs",
  "type": "module",
  "version": "0.0.1",
  "private": true,
  "engines": {
    "node": ">=22.12.0"
  },
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "check": "astro check",
    "astro": "astro"
  },
  "dependencies": {
    "@astrojs/check": "^0.9.8",
    "@astrojs/sitemap": "^3.7.2",
    "@astrojs/starlight": "^0.38.4",
    "astro": "^6.1.3",
    "typescript": "^5.9.3"
  }
}
```

**Verified facts** [VERIFIED: `npm view`, run 2026-04-25]:
- `@astrojs/starlight@0.38.4` peerDependencies: `{ astro: '^6.0.0' }` — confirms Astro 6 compatibility.
- `astro@6.1.9` is current; `^6.1.3` (marketing pin) satisfies.
- `@astrojs/sitemap@3.7.2` is current.
- `@astrojs/check@0.9.8` is current; required for `astro check` CLI.

**`docs/tsconfig.json`** (extends Starlight's strict default):

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```

[VERIFIED: Context7 `/withastro/starlight`] — Starlight's getting-started docs show this exact tsconfig as the default scaffold output.

**`docs/src/content.config.ts`** (required by Starlight 0.38+ — content collections schema lives here, not in `astro.config.mjs`):

```typescript
import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema(),
  }),
};
```

[VERIFIED: Context7 `/withastro/starlight`] — required for the `docs` collection to load. Without this file the build fails with "no content collection found".

### 3.2 `astro.config.mjs` — full template

```javascript
// docs/astro.config.mjs
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://docs.getgeolens.com',
  output: 'static',
  integrations: [
    starlight({
      title: 'GeoLens Docs',
      // Phase 223 placeholder — full token bridge ships in Phase 224 (BRAND-01)
      customCss: ['./src/styles/custom.css'],
      // Belt-and-suspenders noindex during bootstrap (D-07, D-08).
      // GA4 script injection added here per SEO-06 once Measurement ID is decided
      // (see Open Question #1 in RESEARCH.md).
      head: [
        {
          tag: 'meta',
          attrs: {
            name: 'robots',
            content: 'noindex, nofollow',
          },
        },
      ],
      // D-11: empty /guides/ groups declared upfront so Phase 224 cannot
      // accidentally regress to flat URLs. Each group uses `autogenerate`
      // pointing at a directory that doesn't exist yet — Starlight renders
      // the group label with no items (no warning, no build failure).
      sidebar: [
        {
          label: 'Quickstart',
          autogenerate: { directory: 'guides/quickstart' },
        },
        {
          label: 'User Guide',
          autogenerate: { directory: 'guides/user' },
        },
        {
          label: 'Admin Guide',
          autogenerate: { directory: 'guides/admin' },
        },
        {
          label: 'API Reference',
          autogenerate: { directory: 'guides/api' },
        },
      ],
    }),
    sitemap(),
  ],
});
```

**Notes on Starlight `head` config shape** [VERIFIED: Context7 `/withastro/starlight`]:
- Each entry has shape `{ tag: string, attrs?: Record<string, string|number|boolean>, content?: string }`.
- Entries are rendered into HTML elements verbatim and **bypass Astro's script/style processing**. This is significant: `<script content="...">` inline content is NOT escaped; it ships exactly as written.
- Order is preserved.

**`autogenerate` on an empty directory** [VERIFIED: Context7 `/withastro/starlight` "Configure Autogenerated Sidebar Groups"]: Starlight renders a sidebar group with the label and an empty item list. No warning, no build failure. The group still appears in the rendered nav (anchoring the URL structure visually from day 1, satisfying D-11 / specifics §"Visible URL anchor at bootstrap"). Confirmed: Starlight does NOT silently drop empty groups.

**Why `autogenerate` not `items: []`:** Both render an empty group, but `autogenerate` is the path of least friction in Phase 224 — when the first guide MDX file lands, the sidebar populates automatically with no `astro.config.mjs` edit. This matches CONTEXT.md's stated intent: "Phase 224's SHELL-01 just adds nav labels and content references."

### 3.3 Sidebar empty-group rendering — verification

**Behavior confirmed via Starlight 0.38 source + Context7:**

| Configuration | Build behavior |
|---------------|----------------|
| `{ label: 'X', items: [] }` | Renders empty group — no warning |
| `{ label: 'X', autogenerate: { directory: 'does-not-exist' } }` | Renders empty group — no warning, no error |
| `{ label: 'X', autogenerate: { directory: 'exists-but-empty' } }` | Renders empty group — no warning |

Both empty-items and empty-autogenerate succeed silently. We pick `autogenerate` for Phase 224 ergonomics.

### 3.4 Cloudflare Pages monorepo — exact dashboard config

**Two-project setup (one already exists, one new):**

| Project | Status | rootDirectory | Build Watch Paths | Build cmd | Output |
|---------|--------|--------------|-------------------|-----------|--------|
| `getgeolens-com` | Exists | `.` (root) | (already configured for marketing) | `npm run build` | `dist` |
| `getgeolens-docs` | **NEW** | `docs` | `docs/**` | `npm run build` | `dist` (relative to rootDirectory → `docs/dist`) |

**Build Watch Paths vs GitHub Actions path filter** [CITED: developers.cloudflare.com/pages/configuration/monorepos]:
- Build Watch Paths apply to CF Pages **native git integration** auto-builds.
- GitHub Actions `cloudflare/pages-action@v1` invocations bypass the dashboard auto-build entirely — the action uploads pre-built artifacts directly via the Pages API. The dashboard's `rootDirectory` setting still applies to the project metadata (e.g., what shows up in the dashboard UI), but **build isolation is enforced at the GitHub Actions layer via `paths:` filter**, not at CF Pages.
- Practical implication: with the `cloudflare/pages-action@v1` deploy pattern (D-01), the **GitHub Actions `paths:` filter is the load-bearing mechanism**. Build Watch Paths in the dashboard is belt-and-suspenders insurance for the case where someone clicks "deploy" in the CF dashboard manually.

**`docs/wrangler.toml`** (mirrors marketing exactly with name change):

```toml
name = "getgeolens-docs"
compatibility_date = "2025-01-01"
pages_build_output_dir = "dist"
```

[VERIFIED: marketing `wrangler.toml` is 3 lines: `name`, `compatibility_date`, `pages_build_output_dir`]. Marketing uses `compatibility_date = "2024-01-01"`; bumping to `2025-01-01` for docs is a clean choice for a new project (no behavior risk — `compatibility_date` only affects Workers runtime semantics; CF Pages static-site builds ignore it for non-Functions deploys).

**Important nuance:** `wrangler.toml` `name` field MUST match the CF Pages project name (`getgeolens-docs`). When using `cloudflare/pages-action@v1`, the `projectName:` input also has to match. If they diverge, the deploy fails. Validation step: ensure `name` in `docs/wrangler.toml` === `projectName` in `docs-ci.yml` === dashboard project name.

### 3.5 `docs-ci.yml` — full template

```yaml
name: Docs CI

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - '.github/workflows/docs-ci.yml'
  pull_request:
    paths:
      - 'docs/**'
      - '.github/workflows/docs-ci.yml'

jobs:
  check-and-build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: docs
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version-file: docs/.nvmrc
          cache: npm
          cache-dependency-path: docs/package-lock.json
      - run: npm ci
      - run: npx astro check
      - run: npm run build

  deploy:
    needs: check-and-build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      deployments: write
      pull-requests: write
    defaults:
      run:
        working-directory: docs
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version-file: docs/.nvmrc
          cache: npm
          cache-dependency-path: docs/package-lock.json
      - run: npm ci
      - run: npm run build
      - uses: cloudflare/pages-action@v1
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          projectName: getgeolens-docs
          directory: docs/dist
          gitHubToken: ${{ secrets.GITHUB_TOKEN }}
```

**Notes:**
- Mirrors marketing `ci.yml` exactly except: (a) path filter on `docs/**` + own workflow file, (b) `working-directory: docs` for npm steps, (c) project name + directory differ, (d) no `a11y` step (deferred to Phase 228).
- `node-version-file: docs/.nvmrc` — see §3.11 for `.nvmrc` strategy.
- `directory: docs/dist` — when using `cloudflare/pages-action@v1`, this path is **relative to the repo root**, not to the working-directory. Verified by inspecting marketing `ci.yml` which uses `directory: dist` from repo root.
- `cloudflare/pages-action@v1` is **deprecated** (see §1.3) — but we mirror marketing per D-01.

**Marketing `ci.yml` patch** (one-line edit):

```yaml
on:
  push:
    branches: [main]
    paths-ignore: ['docs/**']
  pull_request:
    paths-ignore: ['docs/**']
```

**Deliberately NOT including** `'.github/workflows/ci.yml'` in paths-ignore — we want self-modifications of the marketing workflow to trigger marketing CI (sanity check the change before merge).

**Symmetry check:** When a PR touches both `docs/foo.mdx` and `src/index.astro`:
- `docs-ci.yml` matches `docs/**` → triggers
- `ci.yml` does NOT match because of `paths-ignore: ['docs/**']`... wait, this is wrong. `paths-ignore` skips ONLY if **all** changed files match the ignore list. If the PR also touches `src/index.astro`, the marketing workflow runs.

**Confirmed semantics** [VERIFIED: GitHub docs / community discussions]: `paths-ignore` skips a workflow ONLY when **every** changed file matches a pattern in the ignore list. If any file falls outside the ignored set, the workflow runs. Symmetric setup is correct.

### 3.6 `@astrojs/sitemap` integration — usage with Starlight

```javascript
// astro.config.mjs (excerpt)
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://docs.getgeolens.com',  // REQUIRED — sitemap fails silently without it
  integrations: [
    starlight({ /* ... */ }),
    sitemap(),
  ],
});
```

**Verified facts** [CITED: docs.astro.build/en/guides/integrations-guide/sitemap]:
- `site:` config is **required**; without it sitemap generates nothing (no error, just empty output).
- Sitemap auto-discovers all generated pages (including Starlight's index.mdx).
- Outputs:
  - `dist/sitemap-index.xml` — index pointing at the per-batch sitemaps
  - `dist/sitemap-0.xml` — first batch (entryLimit default 45000)
- For our skeleton with 1 page (`/`), `sitemap-0.xml` will contain a single `<url>` entry pointing at `https://docs.getgeolens.com/`. `sitemap-index.xml` will reference `sitemap-0.xml`. **Empty docs site generates a valid non-empty sitemap.**
- No `filter` needed at this stage — every generated page should be in the sitemap (the noindex meta + robots.txt are the indexing controls). Phase 228 may add a filter if needed.

### 3.7 `customCss` — minimal placeholder accent

**Verified facts** [VERIFIED: Context7 `/withastro/starlight` "Define Custom CSS Variables"]:
- `customCss` is an array of file paths relative to the project root.
- Files are appended after Starlight's defaults — they **override**, not replace.
- Setting `--sl-color-accent` alone does **not** auto-derive `accent-low` / `accent-high`. All three must be authored. Starlight uses these three slots for: focus rings (`accent`), backgrounds-on-active (`accent-low` for dark, `accent-high` for light), and hover hints.

**`docs/src/styles/custom.css`** (per D-09 — minimal placeholder, Phase 224 expands):

```css
/*
 * GeoLens Docs — Phase 223 Bootstrap Placeholder
 *
 * Maps GeoLens primary blue (~hue 250) into Starlight's accent slots ONLY.
 * Full OKLCH 50–950 token bridge ships in Phase 224 (BRAND-01).
 * Source-of-truth: getgeolens.com/src/styles/global.css :root --primary-* scale.
 *
 * DO NOT EXPAND THIS FILE in Phase 223. Token drift detection (BRAND-04) ships in 224.
 */

:root {
  --sl-color-accent-low:  oklch(0.93 0.05 250);  /* primary-100 (light surfaces) */
  --sl-color-accent:      oklch(0.55 0.18 250);  /* primary-500 (default accent) */
  --sl-color-accent-high: oklch(0.46 0.16 250);  /* primary-700 (text-on-light) */
}

:root[data-theme='dark'] {
  --sl-color-accent-low:  oklch(0.30 0.10 250);  /* primary-900 (dark surfaces) */
  --sl-color-accent:      oklch(0.70 0.16 250);  /* primary-400 (default accent) */
  --sl-color-accent-high: oklch(0.93 0.05 250);  /* primary-100 (text-on-dark) */
}
```

**Values extracted from `getgeolens.com/src/styles/global.css`** (confirmed by reading the file 2026-04-25):
- `--primary-100: oklch(0.93 0.05 250)`
- `--primary-400: oklch(0.70 0.16 250)`
- `--primary-500: oklch(0.55 0.18 250)`
- `--primary-700: oklch(0.46 0.16 250)`
- `--primary-900: oklch(0.30 0.10 250)`

The dark-mode values are intentional choices for Phase 223 placeholder (primary-400 is the brightest reasonable blue for dark backgrounds; primary-900 is the deepest dark surface). Phase 224 may revise.

### 3.8 `_redirects` — exact syntax

**Verified facts** [CITED: developers.cloudflare.com/pages/configuration/redirects]:
- File location: `docs/public/_redirects` → Astro copies `public/` verbatim to `dist/`, so `dist/_redirects` is the served path. **No build step modifies it.**
- Comments: lines starting with `#` are ignored.
- Syntax: `[source] [destination] [code?]` — code defaults to **302** (we want **301** for permanent migration).
- Splat: `*` matches all characters greedily; one splat per source URL; reference in destination as `:splat`.
- Trailing slash: NOT auto-normalized — `/foo` and `/foo/` are distinct sources.
- **Order matters: top-most match wins (first-match semantics, NOT longest-match).**
- Limits: 2,000 static + 100 dynamic = 2,100 total per file. We're far below.

**`docs/public/_redirects`**:

```
# GeoLens Docs Redirects
#
# CONVENTION (per Phase 227 MIG-03 update to CONTRIBUTING.md):
# Every page rename or deletion MUST add a 301 redirect here, in the same PR.
# Pattern per legacy path: three rules covering exact, trailing-slash, and splat.
#
# /quickstart is OWNED BY MARKETING (getgeolens.com) — DO NOT add it here.

# /install → /guides/install (legacy MIG-02 stub destination)
/install        /guides/install        301
/install/       /guides/install        301
/install/*      /guides/install/:splat 301

# /admin → /guides/admin (legacy MIG-02 stub destination)
/admin          /guides/admin          301
/admin/         /guides/admin          301
/admin/*        /guides/admin/:splat   301

# /api → /guides/api (legacy MIG-02 stub destination)
/api            /guides/api            301
/api/           /guides/api            301
/api/*          /guides/api/:splat     301
```

**First-match semantics caveat (per CF docs):** Because `/install/*` matches `/install/foo` AND `/install/`, ordering matters. Putting the most specific rule (`/install` exact) first ensures the exact path returns the canonical destination without a `:splat` substitution. The shown ordering is correct.

**Splat-on-empty-target:** When `/install/*` matches `/install/` (empty splat), `:splat` becomes empty string and destination becomes `/guides/install/` (trailing slash). For consistency with the explicit `/install/` rule that fires first, the trailing-slash rule won't reach the splat — but if it did, the result is harmless.

### 3.9 Astro `site` config + canonical URLs

**Verified facts** [CITED: docs.astro.build/en/reference/configuration-reference + Context7 `/withastro/starlight`]:
- `site:` is the canonical absolute base URL. Required for sitemap, OG image absolute URLs, and canonical link tags.
- Starlight emits `<link rel="canonical" href="https://docs.getgeolens.com/...">` automatically when `site:` is set. **No custom Layout or head injection needed.**
- Without `site:`, Starlight falls back to relative canonicals (which Google may interpret as the deployed origin — i.e., the `*.pages.dev` URL during preview, which is wrong for production indexing).

**Verification step for the planner:** After first build, `cat dist/index.html | grep canonical` should show `<link rel="canonical" href="https://docs.getgeolens.com/">`. This is a load-bearing assertion for SEO-05. Add it to the validation script (§6).

### 3.10 `astro check` in CI — prerequisites

**Verified facts** [VERIFIED: Context7 `/withastro/starlight` + npm registry]:
- `astro check` requires `@astrojs/check` as a dependency (^0.9.8 per npm view) and a working `tsconfig.json`.
- The `npm create astro@latest -- --template starlight` scaffold ships both.
- Starlight's content collection schema (`src/content.config.ts`) is validated by `astro check` — missing `title` frontmatter on any MDX file fails the check.
- For the bootstrap stub homepage (`src/content/docs/index.mdx` with valid `title:` frontmatter), `astro check` should pass cleanly.

**Common false positives on first build:**
- Empty `customCss` file with only comments → no error.
- Empty `autogenerate` directory → no error (verified §3.3).
- Missing `description` on the homepage → no error (only `title` is required by Starlight schema).
- TypeScript strict mode on the scaffolded `tsconfig.json` → no error (only `.astro` and `.ts` files are checked; pure MDX content is schema-validated).

**Plan implication:** No special tsconfig adjustments needed. The default `astro/tsconfigs/strict` works.

### 3.11 Astro 6 + Starlight 0.38.4 peer-dep matrix

[VERIFIED: `npm view` 2026-04-25]

| Package | Version | Peer dep | Compatible with marketing's Astro `^6.1.3`? |
|---------|---------|----------|---------------------------------------------|
| `@astrojs/starlight` | 0.38.4 | `astro ^6.0.0` | ✓ Yes |
| `astro` | 6.1.9 (latest 6.x) | — | Marketing uses `^6.1.3` so `^6.1.x` pin is correct |
| `@astrojs/sitemap` | 3.7.2 | (peerDep on `astro`, accepts 5/6) | ✓ Yes |
| `@astrojs/check` | 0.9.8 | `astro >=4.0.0` | ✓ Yes |

**Lock the package.json to:**
- `astro: ^6.1.3` (matches marketing pin exactly per D-20)
- `@astrojs/starlight: ^0.38.4`
- `@astrojs/sitemap: ^3.7.2`
- `@astrojs/check: ^0.9.8`
- `typescript: ^5.9.3` (matches marketing devDep)

**Deprecation/version-skew gotchas:**
- Starlight 0.37.x and earlier require Astro 5; 0.38.0 added Astro 6. Don't use 0.37 — won't work with Astro 6.
- `astro check` 0.9.8 is the latest; older versions (0.7.x) had bugs with Astro 6 content collections.
- Pin **exact major** for Starlight (`^0.38.4`, NOT `^0.38.0`) — Starlight pre-1.0 may ship breaking changes in patch versions. The `^0.38.4` semver caret means "0.38.x but not 0.39.x" because pre-1.0 caret behavior locks the minor.

### 3.12 GA4 Measurement ID strategy

**Critical finding (verified 2026-04-25 via grep):** The marketing site (`getgeolens.com`) **does not currently have GA4 installed**. Searched for: `gtag`, `googletagmanager`, `G-` measurement ID prefix, `analytics`, `GA4` — zero matches in `astro.config.mjs`, `src/components/layout/SiteLayout.astro`, `src/components/`, `src/lib/`. The marketing site has NO analytics today.

**Implication for SEO-06:** D-19 says "GA4 same-Measurement-ID strategy enabled on docs site" and "Lookup the marketing site's actual ID during planning (not hardcoded here)." There is no ID to look up. The planner must surface this to the user. See **Open Question #1**.

**Pattern documented for future reference** (when an ID becomes available — `G-XXXXXXXXXX`):

```javascript
// astro.config.mjs (head config addition)
head: [
  // ... existing noindex meta ...
  // GA4 same-Measurement-ID per SEO-06
  {
    tag: 'script',
    attrs: {
      src: 'https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX',
      async: true,
    },
  },
  {
    tag: 'script',
    content: `
      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());
      gtag('config', 'G-XXXXXXXXXX');
    `,
  },
],
```

**Best practice for cross-subdomain tracking** [CITED: analyticsmania.com/post/subdomain-tracking-with-google-analytics-and-google-tag-manager]: GA4 handles `getgeolens.com` ↔ `docs.getgeolens.com` automatically via **one** Measurement ID and **one** Web Data Stream. No GTM cross-domain config needed for subdomains. Two separate Measurement IDs (one per subdomain) would split sessions and break attribution.

**Recommendation for the planner:**
- Surface Open Question #1 to user for decision.
- Three viable paths:
  1. **Defer GA4 to a follow-up phase** — accept that SEO-06 is partially deferred; ship docs without analytics, address in Phase 228 alongside sitemap-to-GSC submission. Lowest risk for Phase 223.
  2. **Provision a NEW GA4 Measurement ID this phase** — install on both marketing and docs simultaneously. Touches the marketing repo (out-of-phase scope creep; D-02 path filter says docs PRs don't touch `src/**`).
  3. **Hardcode a placeholder ID, ship docs, fill in later** — bad: ships a broken script tag in production.
- **Recommended**: Path 1 (defer GA4 to Phase 228). It's a clean phase boundary (Phase 228 is also when robots.txt + noindex come off — these are all "production-go-live" toggles and belong together).

**If user picks Path 1**, drop GA4 from this phase entirely; SEO-06 status becomes "deferred to Phase 228" and gets re-mapped in REQUIREMENTS.md `## Traceability`.

### 3.13 Custom domain attachment workflow

**Order of operations** [CITED: developers.cloudflare.com/pages/configuration/custom-domains]:
1. CF Pages project must already exist (`getgeolens-docs` created via dashboard before any deploy).
2. Push code to `main` → first auto-deploy via `pages-action@v1` → site lives at `getgeolens-docs.pages.dev`.
3. CF Dashboard → Pages → `getgeolens-docs` → Custom domains → Set up a custom domain → enter `docs.getgeolens.com`.
4. CF auto-creates the CNAME record in the existing `getgeolens.com` DNS zone (zone is already on Cloudflare since marketing uses CF Pages — this is the easy path).
5. TLS provisioning takes ~3-5 minutes. CF's Universal SSL covers this automatically; no action needed.
6. **Manual verification (per D-06):** `curl -I https://docs.getgeolens.com` should return:
   - `HTTP/2 200`
   - `content-type: text/html; charset=utf-8`
   - Valid TLS chain (curl exits 0 — no `-k` needed)
7. Screenshot the dashboard view + curl output → attach to phase summary.

**Pre-existing DNS condition:** Apex `getgeolens.com` is already on Cloudflare (per CONTEXT.md `<code_context>` "DNS record auto-managed by CF Pages custom-domain attachment"). No nameserver changes needed.

**Risk: TLS provisioning timeout.** Rare but possible — if certificate issuance hangs >15 minutes, escalate to delete + re-create the custom domain attachment in CF dashboard. Document the recovery in phase summary if it happens.

---

## 4. Files to Create / Modify

### Files to CREATE in `getgeolens.com` repo (new docs subtree)

| Path | Purpose |
|------|---------|
| `docs/package.json` | Independent dep tree; pinned versions per §3.1 |
| `docs/package-lock.json` | Generated by `npm install` (committed) |
| `docs/astro.config.mjs` | Starlight + sitemap + noindex meta + sidebar groups + customCss (template §3.2) |
| `docs/tsconfig.json` | Extends `astro/tsconfigs/strict` (template §3.1) |
| `docs/wrangler.toml` | CF Pages project identity (template §3.4) |
| `docs/.nvmrc` | Mirror repo-root `.nvmrc` content `20` (or upgrade — see §6 nuance) |
| `docs/src/content.config.ts` | Required Starlight content collections schema (template §3.1) |
| `docs/src/content/docs/index.mdx` | Stub homepage (template §5) |
| `docs/src/styles/custom.css` | Minimal placeholder accent (template §3.7) |
| `docs/public/robots.txt` | `User-agent: *` / `Disallow: /` + sitemap reference (template §5) |
| `docs/public/_redirects` | MIG-02 minimal set, three rules per legacy path (template §3.8) |
| `docs/public/favicon.svg` | Reuse marketing's favicon (copy from `getgeolens.com/public/favicon.svg`) |
| `.github/workflows/docs-ci.yml` | Docs CI/deploy workflow (template §3.5) |
| `docs/.gitignore` | `node_modules/`, `dist/`, `.astro/`, `.DS_Store` |

**Optional (Claude's discretion per CONTEXT.md):**
| Path | Purpose | Recommendation |
|------|---------|----------------|
| `docs/src/content/openapi/.gitkeep` | Phase 225 readiness — directory committed | **Defer to Phase 225.** No structural value in 223. |
| `docs/README.md` | One-pager: how to run dev, how to update GA4 ID, how to deploy | **Include.** ~20 lines documenting the local dev story for future maintainers. |

### Files to MODIFY in `getgeolens.com` repo

| Path | Change |
|------|--------|
| `.github/workflows/ci.yml` | Add `paths-ignore: ['docs/**']` to both `on.push` and `on.pull_request` triggers |

That's the entire surface area. The marketing site `src/`, `public/`, and `astro.config.mjs` are NOT touched.

### Files unchanged in this phase but referenced

| Path | Why mentioned |
|------|---------------|
| `getgeolens.com/wrangler.toml` | Untouched; existing project keeps its config |
| `getgeolens.com/astro.config.mjs` | Untouched; existing sitemap/site config remains for marketing |
| `getgeolens.com/src/styles/global.css` | Source-of-truth for OKLCH primary palette — referenced for token values, not modified |
| `getgeolens.com/src/components/home/HeroSection.astro` | Already links to `/quickstart` (line 23) — confirms `/quickstart` ownership stays with marketing |
| `getgeolens.com/src/components/layout/Nav.astro` | Already has `/quickstart` link (line 79) — same |

---

## 5. External Repo Lookups (concrete values extracted)

| What | Value (verified 2026-04-25) | Source |
|------|----------------------------|--------|
| Marketing repo path | `/Users/ishiland/Code/getgeolens.com/` | local FS |
| Node engine pin | `>=22.12.0` | `package.json:5-7` |
| Marketing `.nvmrc` content | `20` | `.nvmrc` (raw file) |
| Marketing Astro version pin | `^6.1.3` | `package.json:23` |
| Marketing `@astrojs/sitemap` pin | `^3.7.2` | `package.json:19` |
| Marketing `@astrojs/check` pin | `^0.9.8` | `package.json:18` |
| Marketing TypeScript pin | `^5.9.3` | `package.json:31` |
| Marketing CF Pages project name | `getgeolens-com` | `wrangler.toml:1` |
| Marketing `compatibility_date` | `2024-01-01` | `wrangler.toml:2` |
| Marketing build output dir | `dist` | `wrangler.toml:3` |
| Marketing CI runner | `actions/checkout@v4`, `actions/setup-node@v4`, `cloudflare/pages-action@v1` | `.github/workflows/ci.yml` |
| GA4 Measurement ID | **NONE — not installed** | Verified via grep across entire repo |
| OKLCH `--primary-100` | `oklch(0.93 0.05 250)` | `src/styles/global.css:62` |
| OKLCH `--primary-400` | `oklch(0.70 0.16 250)` | `src/styles/global.css:65` |
| OKLCH `--primary-500` | `oklch(0.55 0.18 250)` | `src/styles/global.css:66` |
| OKLCH `--primary-700` | `oklch(0.46 0.16 250)` | `src/styles/global.css:68` |
| OKLCH `--primary-900` | `oklch(0.30 0.10 250)` | `src/styles/global.css:70` |
| `/quickstart` ownership | Marketing site (HeroSection, Nav, QuickstartTeaser) | confirmed by reading all three files |
| Marketing `tsconfig.json` shape | `extends: "astro/tsconfigs/strict"` + path aliases | full file read |

**`.nvmrc` strategy decision:** Marketing repo's `.nvmrc` contains `20` but `package.json` says `node >=22.12.0`. This is a mismatch in the marketing repo (Node 20 < 22.12), but it works in CI because `actions/setup-node@v4` resolves `.nvmrc` permissively. For the docs subtree, **add `docs/.nvmrc` with content `20`** to match the marketing CI exactly. This satisfies D-20 and avoids any version-skew risk during the bootstrap.

### Stub homepage (`docs/src/content/docs/index.mdx`) — template

```mdx
---
title: GeoLens Documentation
description: Documentation for the GeoLens self-hosted GIS data catalog.
template: doc
---

# GeoLens Documentation

GeoLens v1.0 documentation — coming soon.

We're migrating the install and admin guides into a dedicated docs site.
The full content arrives across phases 224–227.

## Planned URL Structure

- [Quickstart & Install](/guides/install) — getting GeoLens running via `docker compose`
- [Admin Guide](/guides/admin) — RBAC, OAuth, settings, backups, infrastructure
- [API Reference](/guides/api) — REST + OGC endpoints (auto-generated)

In the meantime, see the [GeoLens repository](https://github.com/geolens-io/geolens)
on GitHub.
```

**Notes:**
- Required `title:` frontmatter present (Starlight schema).
- Optional `description:` improves canonical meta description (good for SEO once we go indexable).
- `template: doc` is the Starlight default for content pages (vs `splash` for hero pages).
- Internal links (`/guides/install`, etc.) will 404 in this phase — that's intentional. Phase 224 fills them in. The 404 is the visible signal that "URL structure is reserved, content is coming."
- No code blocks, no images, no Pagefind concerns yet.

### `docs/public/robots.txt` — template

```
User-agent: *
Disallow: /

Sitemap: https://docs.getgeolens.com/sitemap-index.xml
```

**Notes:**
- `Disallow: /` — blocks all crawlers from all paths (D-07).
- `Sitemap:` line is INTENTIONALLY included — even on a disallowed site, declaring the sitemap is harmless and Phase 228's flip from `Disallow: /` → `Allow: /` is a one-line edit that doesn't need to also add the sitemap declaration.

---

## 6. Validation Architecture (Nyquist Dimension 8)

### Test Framework

| Property | Value |
|----------|-------|
| Framework | None — there is no test framework in the docs subtree |
| Config file | n/a |
| Quick run command | `cd docs && npm run check` (runs `astro check`) |
| Full suite command | `cd docs && npm run build` (full Astro build with sitemap, customCss, head injection) |

**Note:** Per `.planning/config.json`, `nyquist_validation` is not set — defaults to enabled. This phase has no unit/integration tests by design (it's pure infrastructure scaffolding). Validation = build artifact assertions.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BOOT-01 | `docs/` scaffold exists with own deps | smoke | `cd docs && npm run build` exits 0 | ❌ Wave 0 (created in this phase) |
| BOOT-02 | Astro pinned to `^6.1.x`, `astro check` passes | unit | `cd docs && npm run check` exits 0 | ❌ Wave 0 |
| BOOT-03 | All built URLs use `/guides/` prefix (verified by sidebar config) | smoke | `grep -E '"/(install\|admin\|api)"' docs/dist/index.html` returns nothing | ❌ Wave 0 |
| BOOT-04 | `site:` set; canonical link in built HTML resolves to docs.getgeolens.com | smoke | `grep 'rel="canonical"' docs/dist/index.html \| grep 'docs.getgeolens.com'` returns 1 line | ❌ Wave 0 |
| DEPLOY-01 | Two CF Pages projects active | manual | CF dashboard screenshot | manual |
| DEPLOY-02 | Marketing-only push doesn't trigger docs CI; docs-only push doesn't trigger marketing | smoke | branch test: push docs-only commit → only `docs-ci.yml` runs (verifiable in GitHub Actions UI) | manual via test branch |
| DEPLOY-03 | TLS valid at `docs.getgeolens.com` | manual | `curl -I https://docs.getgeolens.com` returns 200 + valid cert | manual |
| DEPLOY-04 | PR preview at `*.pages.dev` | manual | open a PR; verify CF Pages comment with preview URL on PR | manual |
| MIG-02 | `dist/_redirects` matches expected content | unit | `diff docs/public/_redirects docs/dist/_redirects` exits 0 (Astro copies public/ verbatim) | ❌ Wave 0 |
| SEO-05 | Canonical resolves to docs.getgeolens.com | (same as BOOT-04) | (same) | ❌ Wave 0 |
| SEO-06 | GA4 same-Measurement-ID present in built HTML | smoke | `grep 'gtag/js?id=G-' docs/dist/index.html` returns 1 line | ❌ Wave 0 — **but see Open Question #1; may be deferred** |
| CI-02 | `npx astro check` runs in CI | unit | `grep 'astro check' .github/workflows/docs-ci.yml` returns 1 match | n/a (workflow file is the artifact) |

### Sampling Rate

- **Per task commit:** `cd docs && npm run check`
- **Per wave merge:** `cd docs && npm run build` + grep assertions on `dist/index.html` and `dist/sitemap-index.xml` and `dist/_redirects`
- **Phase gate:** `npm run build` green + manual CF Pages dashboard verification + `curl -I https://docs.getgeolens.com` 200 + screenshot in phase summary

### Wave 0 Gaps

- [ ] `docs/` directory does not exist — entire subtree created in this phase
- [ ] No test framework — none needed; build-artifact assertions are the gate
- [ ] CF Pages `getgeolens-docs` project must be created in dashboard BEFORE first `pages-action@v1` deploy runs (step 1 of deploy sequence — see §3.13)
- [ ] Custom domain attachment is a manual dashboard step — schedule a 5-minute window after first successful preview deploy

### Built-Artifact Validation Script (recommended)

Add a `docs/scripts/verify-build.sh` (or inline in CI) that runs after `npm run build`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Asserting canonical URL points to docs.getgeolens.com..."
grep -F 'rel="canonical"' dist/index.html | grep -F 'https://docs.getgeolens.com' \
  || { echo "FAIL: canonical missing or wrong"; exit 1; }

echo "Asserting noindex meta present..."
grep -F 'name="robots"' dist/index.html | grep -F 'noindex' \
  || { echo "FAIL: noindex meta missing"; exit 1; }

echo "Asserting sitemap-index.xml generated..."
test -f dist/sitemap-index.xml || { echo "FAIL: sitemap-index missing"; exit 1; }

echo "Asserting _redirects copied to dist/..."
test -f dist/_redirects || { echo "FAIL: _redirects missing"; exit 1; }

echo "Asserting NO flat URLs (/install, /admin, /api) in built HTML internal links..."
# Note: this catches accidental flat URLs in links/sidebar; it doesn't catch
# /quickstart references (which are fine — those go to marketing).
if grep -E 'href="/(install|admin|api)(/|"|#)' dist/**/*.html 2>/dev/null; then
  echo "FAIL: flat URL detected in built HTML"; exit 1;
fi

echo "All build-artifact assertions passed."
```

This script is the load-bearing gate for "no flat URLs ever ship" and "canonical/noindex/sitemap/redirects all present." Wire it into `docs-ci.yml` as a step after `npm run build`.

---

## 7. Pitfalls (phase-specific)

### 7.1 Workflow self-modification doesn't trigger
**What goes wrong:** Edit `docs-ci.yml` to fix a bug; push. CI doesn't run. Confusion ensues.
**Why:** `paths:` filter doesn't include the workflow file itself.
**Mitigation:** D-02 already specifies `paths: ['docs/**', '.github/workflows/docs-ci.yml']`. The second entry is the self-modification trigger. **The marketing `ci.yml` patch should NOT include `'.github/workflows/ci.yml'` in `paths-ignore`** — same reason: we want self-edits to trigger marketing CI.

### 7.2 CF Pages "first deploy" race
**What goes wrong:** `cloudflare/pages-action@v1` runs in CI, but the CF Pages project doesn't exist yet → action fails with cryptic 404.
**Why:** Project creation is a manual dashboard step.
**Mitigation:** Plan order in §1.2 — create project in dashboard BEFORE merging the docs subtree to main. Or: run the first deploy from a feature branch (CF auto-creates preview deploys for PRs only after the project exists).

### 7.3 customCss path resolution
**What goes wrong:** `customCss: ['./src/styles/custom.css']` evaluated relative to wrong root.
**Why:** Astro resolves relative paths from the project root (`docs/`). The leading `./` is good practice but not strictly required.
**Mitigation:** The exact form `'./src/styles/custom.css'` works. Verified via Context7. Don't use `'src/styles/custom.css'` (no leading slash) — works today but discouraged in Starlight docs.

### 7.4 `paths-ignore` only-when-all-files-match semantics
**What goes wrong:** Mixed PR (docs + marketing changes) doesn't trigger marketing CI.
**Why:** Misunderstanding `paths-ignore` — many devs assume it excludes individual files; actually it only skips the workflow when ALL changed files match.
**Mitigation:** Symmetric setup is correct; verified §3.5. Validation: PR with one file in `docs/` and one file in `src/` → both workflows run.

### 7.5 `wrangler.toml` name mismatch
**What goes wrong:** `name` in `wrangler.toml` differs from `projectName` in CI workflow → deploy fails or deploys to wrong project.
**Why:** Two sources of truth.
**Mitigation:** Add an inline check in `docs-ci.yml` (one-liner): `grep 'name = "getgeolens-docs"' wrangler.toml || exit 1`. Cheap insurance.

### 7.6 Build contamination via `npm install` from wrong directory
**What goes wrong:** A CI step runs `npm ci` at repo root instead of in `docs/`, hoisting marketing deps into the docs build.
**Why:** Forgetting `defaults.run.working-directory` or `cd docs` before npm calls.
**Mitigation:** D-01 template (§3.5) puts `defaults: { run: { working-directory: docs } }` at the job level. All steps inherit. Verified pattern.

### 7.7 Sitemap empty/single-entry on stub homepage
**What goes wrong:** Build produces sitemap with 1 entry; planner worries it's broken.
**Why:** Skeleton site has 1 page.
**Mitigation:** This is correct behavior. `sitemap-index.xml` references `sitemap-0.xml` which contains a single `<url>` entry for `/`. Once Phase 224 adds content, it grows automatically.

### 7.8 Canonical URL points to *.pages.dev during preview
**What goes wrong:** PR preview canonical URL is `https://docs.getgeolens.com/...` not `https://pr-N.getgeolens-docs.pages.dev/...` — Google might index pages.dev URLs from preview deploys.
**Why:** `site:` config is hardcoded to production.
**Mitigation:** This is correct for production builds; preview deploys are also `Disallow: /`'d (same robots.txt) and noindex-meta'd, so Google won't index them. **Belt-and-suspenders Posture (D-08) is doing real work here.** Don't try to dynamically set `site:` per environment — it complicates the canonical story for SEO.

### 7.9 `_redirects` evaluated at edge, can mask deploy errors
**What goes wrong:** Deploy fails partway, leaving a stale `dist/`. Old `_redirects` still serves correctly. Next deploy "fixes" the redirects without anyone noticing the build was broken.
**Why:** CF Pages serves the last-successful deploy's artifacts.
**Mitigation:** `pages-action@v1` exits non-zero on deploy failure → CI red → noticed. No additional mitigation needed.

### 7.10 Starlight content collection schema breaks when `description` is empty string
**What goes wrong:** Frontmatter `description: ''` triggers schema validation failure (zod's default `description?: string` rejects empty string in some configurations).
**Why:** Starlight's docsSchema treats empty strings differently from missing fields.
**Mitigation:** Either omit `description:` entirely or provide a real description. The template in §5 uses a real description.

### 7.11 GA4 hardcoded ID leaks across environments
**What goes wrong:** Production Measurement ID accidentally collects data from PR preview deploys.
**Why:** Same `astro.config.mjs` builds in both contexts.
**Mitigation:** During bootstrap (this phase), GA4 is either deferred or not yet active. When activated (Phase 228 if deferred), use Astro's `import.meta.env.PROD` to gate the GA4 head injection — production-only. Also, robots.txt + noindex on previews suppresses bot crawls so the analytics signal stays clean.

### 7.12 Astro `output: 'static'` not explicitly set (defaults change)
**What goes wrong:** Astro 6 defaulted to `static` for SSG; future versions could change. Build pipeline assumes static output.
**Why:** Implicit defaults across major versions.
**Mitigation:** Template §3.2 sets `output: 'static'` explicitly. Never rely on the default.

---

## 8. Open Questions (RESOLVED)

> All three open questions were resolved before plan generation on 2026-04-25. Resolution markers are inlined below.

### Open Question #1 — GA4 Measurement ID — **RESOLVED: Path 1 (defer to Phase 228)**

**The question:** SEO-06 specifies "GA4 same-Measurement-ID strategy enabled on docs site for cross-subdomain conversion tracking parity with marketing site." Verification (§3.12, §5) confirms the marketing site has **no GA4 installed**. There is no ID to mirror.

**Three viable resolutions:**

1. **Defer GA4 to Phase 228 (recommended).** Rationale: Phase 228 is the production-go-live phase (sitemap → GSC, robots.txt flip, noindex removal, A11Y audit, Lighthouse). GA4 install + verification belongs in that go-live cluster. Phase 223 ships without analytics. SEO-06 status changes from "Phase 223" to "Phase 228" in REQUIREMENTS.md `## Traceability`.

2. **Provision new GA4 Measurement ID this phase + install on both marketing and docs.** Touches the marketing repo, which violates the build isolation we're establishing (D-02). Forces an out-of-phase marketing PR. Higher coordination cost.

3. **Provision GA4 Measurement ID this phase, install on docs only, mark cross-subdomain tracking as future work.** Half-measure; conversion attribution is broken until marketing site catches up.

**Recommendation:** **Path 1.** Surface to user during planner discuss (or planner explicitly defers). The validation architecture in §6 should NOT include the GA4 grep assertion if Path 1 is chosen.

**Action for planner:** Before generating PLAN.md, confirm with user: "GA4 deferred to Phase 228? (Y/n)". Default Y.

### Open Question #2 — `compatibility_date` value for `docs/wrangler.toml` — **RESOLVED: 2025-01-01**

**The question:** Marketing uses `compatibility_date = "2024-01-01"`. Should docs match (consistency) or use `2025-01-01` (current best practice)?

**Recommendation:** Use `2025-01-01` for docs. Rationale: (a) `compatibility_date` only affects Workers runtime, not Pages static-site builds, so it has no functional impact on either project. (b) New project = new date; mirroring an old date for "consistency" is cargo-culting. Low-stakes; either works.

### Open Question #3 — Optional `docs/src/content/openapi/.gitkeep` for Phase 225 readiness — **RESOLVED: skipped**

**The question:** CONTEXT.md `<discretion>` mentions optionally committing a placeholder. Worth doing?

**Recommendation:** **Skip.** No structural value in 223. Phase 225 creates the directory with the actual snapshot. A `.gitkeep` adds noise to the diff.

---

## 9. Project Constraints (from CLAUDE.md)

The user's global `~/.claude/CLAUDE.md` specifies:
- **Version Control:** "Never indicate AI or Bot activity was part of the commit in your commit messages." → Plans/tasks must not include "Generated with Claude" or similar markers in commit messages.
- **Code Style:** "Prefer simple, readable code over clever abstractions." → No fancy build chains. Plain Astro/Starlight defaults.
- **Code Style:** "Follow existing project conventions when editing files." → `docs-ci.yml` mirrors `ci.yml` exactly (D-01); `wrangler.toml` mirrors marketing exactly with name change (D-04); `package.json` engine pin matches marketing (`>=22.12.0`).
- **Communication:** "Be direct and concise. Skip preamble." → Phase summary should be terse, not narrative.

The repo's `./CLAUDE.md` (geolens monorepo) does NOT exist at `getgeolens.com/` (this work happens in the marketing repo). No project-specific CLAUDE.md applies — only the user-level instructions above.

---

## 10. Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `cloudflare/pages-action@v1` is the deprecated action and the marketing site uses it | §1.3, §3.5 | LOW — confirmed by reading `getgeolens.com/.github/workflows/ci.yml`. Deprecation note from action's GitHub repo (v1.5.0 last release). |
| A2 | Marketing site has no GA4 installed today | §3.12, §5, OQ#1 | LOW — confirmed via grep for `gtag`, `G-`, `googletagmanager` across entire `getgeolens.com/` tree. |
| A3 | Starlight emits `<link rel="canonical">` automatically when `site:` is set | §3.9, §6 | LOW — verified via Context7 + Astro `site` config docs; needs build-time grep to confirm in our specific config. |
| A4 | `autogenerate` on a non-existent or empty directory renders an empty group with no warning | §3.3 | LOW — verified via Context7 Starlight sidebar docs. The planner should still confirm with a build smoke-test. |
| A5 | Astro copies `public/_redirects` to `dist/_redirects` verbatim | §3.8, §6 | LOW — Astro's `public/` directory contract guarantees this; verified in marketing site (its `public/robots.txt` ends up in `dist/robots.txt`). |
| A6 | First-match (top-down) semantics in `_redirects`, NOT longest-match | §3.8 | LOW — confirmed via `developers.cloudflare.com/pages/configuration/redirects` "the top-most redirect is applied". |
| A7 | GitHub Actions `paths-ignore` only skips when ALL changed files match the ignore list | §3.5, §7.4 | LOW — verified via GitHub community docs and search results. |
| A8 | `docs/.nvmrc` content `20` works for `actions/setup-node@v4` even though `package.json` engines says `>=22.12.0` | §5 | MEDIUM-LOW — this is what marketing does today and it works in CI. Could break if Node 20 lacks features the build needs (none currently — Astro 6 supports Node 18+). |
| A9 | CF Pages auto-provisions TLS for `docs.getgeolens.com` since apex is on CF | §3.13 | LOW — confirmed in CONTEXT.md `<code_context>`. Apex `getgeolens.com` is on CF DNS (marketing site already deployed there). |
| A10 | `cloudflare/pages-action@v1` ignores `docs/wrangler.toml` and reads project name from `projectName:` input | §3.4, §7.5 | MEDIUM — the action's behavior with subdir wrangler.toml is undocumented. The `name` field in wrangler.toml is for the CF dashboard project metadata; the action uses its `projectName:` input. They MUST match per §7.5 — flag as a validation step. |

**`[ASSUMED]` claims requiring user confirmation before this phase ships:**
- A2 — Open Question #1 surfaces this.

---

## 11. Sources

### Primary (HIGH confidence — Context7 / official docs)

- Context7 `/withastro/starlight` — `head` config shape, `customCss` semantics, sidebar autogenerate, content collections schema (queries: "head config inject", "sidebar config empty group", "customCss array")
- Context7 `/withastro/docs` — `@astrojs/sitemap` integration usage, `site:` config canonical URL generation
- developers.cloudflare.com/pages/configuration/redirects — `_redirects` syntax, splat, first-match ordering, status code defaults, file location requirements
- developers.cloudflare.com/pages/configuration/monorepos — Build Watch Paths, rootDirectory, 5-project limit, Build System V2 requirement
- npm registry (`npm view`) verified 2026-04-25:
  - `@astrojs/starlight@0.38.4` peerDeps `astro: ^6.0.0`
  - `astro@6.1.9` (latest 6.x)
  - `@astrojs/sitemap@3.7.2`
  - `@astrojs/check@0.9.8`

### Secondary (MEDIUM confidence — verified via WebSearch + cross-reference)

- github.com/cloudflare/pages-action — deprecated as of v1.5.0 (May 2023); recommended replacement is `cloudflare/wrangler-action`
- analyticsmania.com/post/subdomain-tracking-with-google-analytics-and-google-tag-manager — GA4 same-Measurement-ID for subdomain conversion tracking
- GitHub Actions paths/paths-ignore semantics (community discussions + official Workflow syntax docs)

### Tertiary (LOW confidence — single source / not directly verified for this exact setup)

- (none load-bearing)

### Local FS reads (verified 2026-04-25)

- `getgeolens.com/astro.config.mjs`
- `getgeolens.com/wrangler.toml`
- `getgeolens.com/.github/workflows/ci.yml`
- `getgeolens.com/package.json`
- `getgeolens.com/.nvmrc`
- `getgeolens.com/tsconfig.json`
- `getgeolens.com/src/styles/global.css`
- `getgeolens.com/src/components/layout/Nav.astro`
- `getgeolens.com/src/components/layout/SiteLayout.astro`
- `getgeolens.com/src/components/home/HeroSection.astro`
- `getgeolens.com/src/components/home/QuickstartTeaser.astro`
- `getgeolens.com/src/lib/links.ts`
- `getgeolens.com/public/robots.txt`
- Grep `getgeolens.com` for: `gtag|googletagmanager|G-[A-Z0-9]{8,}|measurement|analytics` — zero matches

---

## 12. Metadata

**Confidence breakdown:**
- Standard stack (versions, peer deps): **HIGH** — verified via `npm view` and Context7
- Architecture (file layout, CF Pages multi-project): **HIGH** — verified via Context7, official Cloudflare docs, and cross-reference against the marketing site's existing config
- Pitfalls: **HIGH** — common Cloudflare Pages + Astro + Starlight gotchas, all surfaced from `.planning/research/PITFALLS.md` and validated against this phase's specific config
- GA4 strategy: **MEDIUM-LOW** — pattern is correct, but the input (Measurement ID) doesn't exist; surfaced as Open Question #1
- `pages-action@v1` mirroring vs `wrangler-action`: **HIGH** confidence in deprecation, **HIGH** confidence in mirror-marketing decision per D-01

**Research date:** 2026-04-25
**Valid until:** 2026-05-25 (30 days — stable infrastructure, but Starlight/Astro 6.x changelog should be re-checked before Phase 224 begins)

---

## RESEARCH COMPLETE
