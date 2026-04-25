# Pitfalls Research

**Domain:** Astro Starlight docs site added to existing Astro marketing-site repo (getgeolens-com), with shared design tokens, multi-project Cloudflare Pages, auto-generated OpenAPI reference, Pagefind search, and markdown migration from geolens monorepo
**Researched:** 2026-04-25
**Confidence:** HIGH (Starlight/Astro/Cloudflare via Context7 and official docs), MEDIUM (Pagefind indexing quality, versioning retrofits), LOW (OG image caching strategy at large scale)

---

## Critical Pitfalls

### Pitfall 1: Astro/Starlight Version Lock Mismatch Breaks Builds Silently

**What goes wrong:**
Starlight pins a `peerDependency` on a specific Astro major version. The marketing site is already on Astro 6. If `npm install` resolves Starlight to a version that still requires Astro 5 (or vice versa), the build silently degrades or fails with cryptic content-collection errors. Astro 6 removed the legacy content collections backwards-compat shim that 5.x provided automatically, so any plugin that relied on it without a flag will break.

**Why it happens:**
The marketing site's `package.json` already has `astro` pinned; adding `@astrojs/starlight` without checking its peer range pulls in a mismatched integration. Community Starlight plugins (e.g. sidebar-extended, openapi renderers) often lag one major version behind the Starlight core, compounding the problem.

**How to avoid:**
- Before scaffolding, run `npm info @astrojs/starlight peerDependencies` and confirm `astro >= 5.x` includes 6.x.
- Pin `@astrojs/starlight` to the exact version verified compatible with Astro 6. Use `overrides` in `package.json` only as a last resort.
- After install, run `npx astro check` before committing anything — it surfaces peer-version mismatches immediately.
- Any community plugin for the OpenAPI reference must be audited against Starlight's current version before adoption; prefer Scalar's official Astro integration (`@scalar/astro`) which tracks Astro releases closely.

**Warning signs:**
- `npm install` emits peer-dependency warnings for `astro`.
- `astro build` throws `content collection schema validation failed` with no content changes.
- Social config or `head` frontmatter `content` property errors on first build (a known Starlight migration breakage).

**Phase to address:**
Phase 1 (Bootstrap) — validate version matrix before writing any content.

---

### Pitfall 2: Design Token Drift Between Marketing Site and Docs Site

**What goes wrong:**
`getgeolens-com/src/styles/global.css` is already a manual copy of `geolens/frontend/src/index.css`. Adding Starlight means a *third* consumer of the same OKLCH token set — Starlight's theming uses its own CSS custom properties (`--sl-color-accent`, `--sl-color-accent-low`, etc.) that must be mapped by hand to the GeoLens blue palette. When the marketing site tokens are updated (e.g. a hue shift, a new surface level), the Starlight mapping file is almost never updated in the same commit. The failure mode is invisible in CI: both sites build fine, but the docs site silently drifts toward a different brand identity.

**Why it happens:**
There is no automated cross-check between `global.css`, Starlight's `customCss` file, and the upstream `index.css`. Manual copy-paste is the entire sync mechanism. Developers working on the marketing site have no reason to open the Starlight config.

**How to avoid:**
- Create a single shared file: `packages/tokens/tokens.css` (or `src/shared/tokens.css` since this isn't a true monorepo). Both the marketing root `astro.config.mjs` and the docs `astro.config.mjs` import it via `customCss`.
- If a shared file is too complex, add a CI script that extracts the 10 core OKLCH values from `global.css` and diffs them against the Starlight `customCss` file. Fail CI on any delta.
- Document which `--sl-*` variables map to which GeoLens tokens in a comment block at the top of the Starlight custom CSS file — makes drift visible on code review.
- The Starlight `--sl-color-accent` maps to GeoLens primary blue (hue ~250); confirm this at bootstrap and lock it as an ADR.

**Warning signs:**
- Marketing site and docs site headers have noticeably different button or link colors.
- Dark mode in docs differs from marketing dark mode.
- A brand update PR touches `global.css` but not the Starlight custom CSS file.

**Phase to address:**
Phase 1 (Bootstrap) — establish the shared token strategy. Phase 2 (Brand) — verify light/dark parity. Add a CI lint check in Phase 1 that survives all future phases.

---

### Pitfall 3: Cloudflare Pages Build Triggers Contaminate Both Projects

**What goes wrong:**
Two Pages projects share the same repo (`getgeolens-com`). By default, *every* push to main triggers builds for *both* projects regardless of which files changed. A marketing copy change rebuilds the full Starlight docs (including Pagefind indexing and OpenAPI fetching); a docs content PR rebuilds the marketing site. Build minutes are wasted, and — more critically — if the OpenAPI fetch step uses a live URL, a marketing-only push can accidentally capture a stale or broken schema.

A subtler variant: both projects use Astro's default output directory `dist/`. Cloudflare Pages `rootDirectory` tells it where to run the build command, but if it is misconfigured (left blank or set to repo root instead of the respective subpath), both projects attempt to serve from the same `dist/` output path, producing one site's files overwriting the other's in the Cloudflare edge cache during concurrent deployments.

**Why it happens:**
Cloudflare Pages monorepo support requires explicit `rootDirectory` per project and explicit build watch paths. The default "watch everything" is the path of least resistance when first connecting a repo.

**How to avoid:**
- Create two separate Pages projects in the Cloudflare dashboard: `getgeolens-com` (root: `./`) and `geolens-docs` (root: `./docs` or whichever subdirectory Starlight lives in).
- Set build watch paths: marketing project watches `src/**,public/**,astro.config.mjs`; docs project watches `docs/**,docs/astro.config.mjs`.
- Verify `rootDirectory` in the Cloudflare project settings UI matches the directory containing that project's `astro.config.mjs` — not the repo root.
- Both projects must have distinct output directories. For Starlight, set `outDir: 'dist'` within its own `rootDirectory`, keeping paths isolated.
- Use Build System V2 (required for monorepo path filtering to work).

**Warning signs:**
- Marketing deploys take 3-4 minutes instead of under 1 minute (Pagefind indexing running unnecessarily).
- Cloudflare dashboard shows both projects deploying on every push.
- A docs deploy produces a URL that serves marketing site HTML.

**Phase to address:**
Phase 1 (Bootstrap) — configure both projects and watch paths before connecting CI.

---

### Pitfall 4: OpenAPI Schema Drift — Docs Silently Describe a Dead API

**What goes wrong:**
The docs build fetches `openapi.json` at build time. If the fetch target is a running dev/staging FastAPI instance, the schema varies by environment. If a snapshot is committed to the repo, it goes stale whenever FastAPI endpoints change without a corresponding docs PR. Either way, the rendered API reference on `docs.getgeolens.com` can describe endpoints, request bodies, or response shapes that no longer exist in the shipped product. Auth patterns (JWT Bearer vs API key) are particularly prone to missing examples because FastAPI's auto-generated schema often omits security scheme examples without explicit `SecurityScheme` declarations.

A second failure mode: WebSocket or SSE endpoints (not present in GeoLens currently, but relevant if streaming is added) cannot be represented in OpenAPI 3.0 — they will simply be absent from the rendered reference with no warning.

**Why it happens:**
OpenAPI build-time fetches couple the docs build to API availability. Committed snapshots require a discipline of "update snapshot on every backend change" that teams forget. FastAPI's `openapi()` generator does not include security examples by default.

**How to avoid:**
- Commit an `openapi.json` snapshot to the docs repo (or a `docs/` subdir of `getgeolens-com`). This gives reproducible builds.
- Add a CI job in the `geolens` backend repo that fetches `/api/openapi.json` after tests pass and opens a PR to `getgeolens-com` updating the snapshot if it differs. Use `oasdiff` to include a breaking-change report in the PR body.
- Explicitly add `SecurityScheme` for both `BearerAuth` and `APIKeyAuth` in the FastAPI app (`app.openapi_components`), and add `responses` examples for the 3-4 most common endpoints before shipping v15.0.
- Document the WebSocket/SSE gap explicitly in the API reference intro page — "Streaming endpoints are not listed here; see [link]."

**Warning signs:**
- API reference page shows endpoints that 404 in the running app.
- Auth section shows no security scheme or example token format.
- Backend receives breaking-change PRs without a corresponding docs-snapshot update.

**Phase to address:**
Phase 3 (API Reference) — establish snapshot commit + CI diff job. Phase 1 (Bootstrap) — decide snapshot vs live-fetch before any content is written.

---

### Pitfall 5: Pagefind Indexes Code Blocks as First-Class Content, Polluting Search Results

**What goes wrong:**
Pagefind indexes the full text of every rendered HTML element by default. In a technical docs site, code blocks containing YAML, Docker Compose stanzas, API responses, and shell commands produce dozens of near-identical search result entries like "POSTGRES_PASSWORD image postgres:16 restart unless-stopped" — content that has no navigational value. Users searching for "install" get swamped with low-signal code fragment hits before finding the actual installation guide prose.

A related issue: Pagefind runs only at build time. During development (`astro dev`), search is completely non-functional. This masks indexing quality problems until a full build runs — which on Cloudflare Pages may be the first time a developer notices a broken index.

**Why it happens:**
Starlight ships Pagefind with zero required configuration ("No configuration is required to enable search"). This default is fine for prose-heavy docs but degrades for technical docs with large code blocks. Developers don't notice until content volume grows.

**How to avoid:**
- Wrap all `<Code>` / `<CodeBlock>` regions with `data-pagefind-ignore` in a Starlight component override, or configure `pagefind.indexWeight` to downrank code content.
- Audit search quality at the end of Phase 4 (Content Migration) by running `astro build` locally and testing 10 representative queries. Don't wait for CI.
- Add a `pagefind: false` frontmatter flag on any auto-generated reference pages (e.g. OpenAPI summary page) where full indexing is noise.
- Run `astro build && npx astro preview` locally before pushing content milestones, because Pagefind only works in preview/production mode.

**Warning signs:**
- Search for "install" returns code snippet fragments as top results.
- Pagefind index file (`pagefind/pagefind-index.json`) is unexpectedly large (>5MB for a <50 page site).
- Search returns 0 results in development — expected, but easy to mistake for a real bug.

**Phase to address:**
Phase 2 (Content Structure) — establish code block exclusion conventions. Phase 4 (Content Migration) — audit index quality with a build run.

---

### Pitfall 6: Legacy Markdown Migration Breaks Image Paths and Cross-References

**What goes wrong:**
`geolens/backend/docs/install.md` and `admin.md` are written for GitHub rendering: images are relative paths (`../screenshots/install.png`) or absolute GitHub URLs (`https://github.com/geolens/.../raw/main/...`); cross-references use GitHub anchor syntax (`[see admin guide](admin.md#configuration)`); code fences use GitHub-flavored fencing without explicit language IDs. When these files are copied into Starlight, all three break:

1. Relative image paths are wrong relative to Starlight's `src/content/docs/` structure.
2. GitHub raw image URLs embed a branch name (`main`) that will resolve to the wrong commit after a rename or reorg.
3. Cross-references with `.md` extensions and GitHub anchor IDs don't resolve in Astro content collections — Starlight expects root-relative paths without `.md`.
4. Code fences without language IDs (```` ``` ````) produce unstyled blocks in Expressive Code, which expects explicit language hints.

Additionally, the `title` and `description` frontmatter fields are Starlight-required but absent from the legacy docs. A missing `title` causes the build to fail.

**Why it happens:**
The source files were written for one rendering target (GitHub) and are being transplanted to another (Starlight/Astro). Nobody does a pass on migration mechanics before copying files.

**How to avoid:**
- Before copying any file, run a checklist migration script (or manual grep) against each `.md` file:
  - All images: move to `src/assets/docs/` and use Astro's `import` or `src` path syntax.
  - All cross-references: replace `.md` extension with no extension, validate against Starlight's file tree.
  - All code fences: add language ID where absent.
  - All frontmatter: add `title` (required) and `description` (strongly recommended for SEO).
- Remove the source files from `geolens/backend/docs/` (or add a stub redirecting to `docs.getgeolens.com`) immediately after migration to prevent the dual-canonical problem (see Pitfall 7).
- Run `npx astro check` after migration — it validates content collection frontmatter against the schema.

**Warning signs:**
- Broken image placeholders on first preview build.
- `Astro check` fails with "title is required" on migrated pages.
- Internal links 404 after deploy.
- Code blocks render as plain text without syntax highlighting.

**Phase to address:**
Phase 4 (Content Migration) — use checklist above as the migration gate criteria.

---

### Pitfall 7: Dual-Canonical Indexing — GitHub Markdown and docs.getgeolens.com Both Indexed by Google

**What goes wrong:**
`geolens/backend/docs/install.md` rendered by GitHub (`github.com/geolens/.../docs/install.md`) will be indexed by Google for months after `docs.getgeolens.com/install` goes live. Search results show both. GitHub's rendered markdown has no `<link rel="canonical">` control — Google decides on its own which URL is canonical. This splits PageRank and creates confusion for users who land on stale GitHub docs.

A second SEO issue: if Starlight's `site` config is not set to `https://docs.getgeolens.com` before the first deploy, Starlight generates relative canonical tags and the sitemap omits absolute URLs. The sitemap submitted to Google Search Console will be invalid.

**Why it happens:**
The source markdown files in the monorepo remain reachable on GitHub after migration. `site` config is frequently left as a placeholder during development.

**How to avoid:**
- Set `site: 'https://docs.getgeolens.com'` in the Starlight `astro.config.mjs` at bootstrap (Phase 1), before any content exists — this ensures every subsequent build generates correct canonical tags and sitemap entries.
- After migration, replace `docs/install.md` and `docs/admin.md` in the geolens repo with stub files that contain a single line: "Documentation has moved to https://docs.getgeolens.com/install". GitHub renders this, and any Google bot that followed the old URL gets a human-readable redirect signal.
- Submit the `docs.getgeolens.com/sitemap-index.xml` to Google Search Console immediately on launch.
- Do not add a `robots.txt` `Disallow` to the geolens repo docs — that hides the stub pages and leaves stale content indexable.

**Warning signs:**
- Google Search Console shows both `github.com/.../docs/install.md` and `docs.getgeolens.com/install` indexed for the same query.
- Sitemap entries show relative URLs instead of absolute.
- `canonical` meta tag in page source shows a relative path.

**Phase to address:**
Phase 1 (Bootstrap) — set `site` config. Phase 4 (Content Migration) — replace legacy source files with stubs.

---

### Pitfall 8: Versioning Retrofit is Extremely Painful After Launch

**What goes wrong:**
v15.0 ships single-version docs. When GeoLens 2.0 changes the admin RBAC model or renames the settings API, someone will want to preserve the 1.x docs. At that point, retrofitting versioning into Starlight means: choosing a strategy (folder-per-version, branch-per-version, or separate subpath deployment), restructuring all URL slugs (`/install` becomes `/v1/install` or `/latest/install`), rewriting all internal cross-references, and invalidating all external links that were shared or indexed by Google.

Folder-based versioning (the Docusaurus pattern) works ergonomically with Astro content collections but produces massive duplication and no automated merge for shared content. Branch-based versioning is "a much more painful site to manage" per the Starlight community discussion. Neither is built into Starlight natively as of v15.0.

**Why it happens:**
Single-version is the right call for launch. The trap is making URL structure decisions in v15.0 that *assume* single-version forever: no `/latest/` prefix, no `version` frontmatter, no redirect infrastructure.

**How to avoid:**
- Use a URL structure that accommodates a future version prefix without a breaking rename: `docs.getgeolens.com/guides/install` (not `docs.getgeolens.com/install`). A future version would become `docs.getgeolens.com/v2/guides/install` with a redirect from the root to `latest`.
- Add a `version: '1.x'` frontmatter field to every doc at migration time. It costs nothing now, enables future filtering, and makes the "add versioning" PR trivially diff-able.
- Add a `_redirects` file stub in `public/` at Phase 1 with a comment: "Add redirects here when docs are renamed." This establishes the pattern before the first rename happens.

**Warning signs:**
- URL structure is flat (`/install`, `/admin`) with no grouping prefix.
- No version field in frontmatter.
- No redirect mechanism exists when content is renamed in Phase 4.

**Phase to address:**
Phase 1 (Bootstrap) — URL structure decision. Phase 4 (Content Migration) — add `version` frontmatter and establish `_redirects` baseline.

---

### Pitfall 9: OG Image Satori Build Cost Grows Quadratically as Docs Scale

**What goes wrong:**
Generating per-page OG images with Satori + Resvg adds 100–300ms per page. For a 50-page v15.0 docs site this is 5–15 seconds of additional build time — acceptable. When the docs site reaches 150–200 pages across guides, admin, user, and API reference sections, build time bloats to 30–60 seconds for OG images alone. Resvg can also saturate CPU during parallel image generation, causing Cloudflare Pages' free-tier build VMs to OOM or timeout.

A separate issue: Satori supports only a CSS subset. `oklch()` color functions are not supported in Satori — GeoLens brand colors must be converted to `rgb()` or hex for OG templates. If the marketing site's OG templates use OKLCH natively and are copy-pasted into the docs config, they will silently fall back to black or produce garbled output.

**Why it happens:**
OG image generation is often added late ("it's just a template"), and the scale impact is not obvious until the site has grown. OKLCH conversion is a one-time gotcha that only surfaces at render time.

**How to avoid:**
- Convert all OKLCH brand colors to hex/RGB in the Satori OG template at authoring time. Do not use `oklch()` in Satori contexts.
- Use build-time caching for OG images (hash the frontmatter title + description; skip regeneration if hash matches). The `astro-satori` package supports this pattern.
- If build time for OG images exceeds 20 seconds at any point, switch to runtime generation (an Astro API endpoint returning PNG) — this avoids build overhead entirely for a docs site where OG images are only fetched on social share.
- Start with a shared OG template that uses the page title and a static GeoLens logo — do not invest in per-section custom artwork before the volume problem is understood.

**Warning signs:**
- Cloudflare Pages build logs show `Generating OG image...` lines consuming >25% of total build time.
- OG preview tools show black/blank images for docs pages.
- Build fails with memory errors on the Pages free tier.

**Phase to address:**
Phase 2 (Brand/Design) — establish Satori template with OKLCH-to-hex conversion and caching from the start.

---

### Pitfall 10: Cross-Domain Analytics — docs→app Conversion Is Invisible Without Setup

**What goes wrong:**
GA4 handles subdomains of the same domain automatically if the same measurement ID is used. However, `getgeolens.com` and `docs.getgeolens.com` are subdomains — this is *not* cross-domain, it is subdomain. GA4 will track them in the same session automatically provided the same Measurement ID and `gtag` install are used on both. The trap is installing GA4 only on the marketing site (`getgeolens.com`) and forgetting the docs site, or using a different Measurement ID for docs (creating two separate properties). When someone reads the install guide and then signs up or visits the demo, the session breaks and the conversion is invisible.

A subtler problem: if the docs site eventually gains a "Request Demo" CTA linking to `getgeolens.com/demo`, GA4 will attribute that conversion to "direct" traffic unless the session is actively stitched. This requires the same data stream, not just the same property.

**How to avoid:**
- Use the same GA4 Measurement ID and the same web data stream for both `getgeolens.com` and `docs.getgeolens.com`.
- Confirm both use the same `gtag('config', 'G-XXXXXX')` call — not separate property IDs.
- At Phase 1 (Bootstrap), copy the `<Analytics />` component or `<script>` tag from the marketing site verbatim into the Starlight `head` config.
- Define a GA4 conversion event for "docs→app" (e.g. a click on any "Get Started" or "Request Demo" link from a docs page) at launch, not retroactively.

**Warning signs:**
- GA4 Realtime shows zero active users on `docs.getgeolens.com` when the site has traffic.
- "Docs" appears as a separate Source in acquisition reports rather than as a session continuation.
- Conversion report shows 0% conversion from docs referral source.

**Phase to address:**
Phase 1 (Bootstrap) — install analytics with correct Measurement ID. Verify in GA4 Realtime before any content publish.

---

### Pitfall 11: 404 Handling — Link Rot from External Sources After Docs Rename

**What goes wrong:**
The docs site launches with URL slugs derived from the legacy markdown filenames (e.g. `/guides/install`, `/guides/admin`). As the docs evolve, pages get reorganized: `admin` becomes `admin/overview`, `install` becomes `quickstart`. Every external link (GitHub issues, Stack Overflow answers, blog posts, old Google Search Console index) that referenced the old URL produces a 404 with no recovery path. Because Cloudflare Pages serves a static site, there is no server-side 301 redirect logic — redirects must be declared in a `_redirects` file in the output root, and this file must be manually maintained.

A compounding issue: Astro/Starlight generates a custom `404.astro` page. If it is not customized to include the site navigation, users who land on a 404 see a dead end with no path to find what they were looking for.

**How to avoid:**
- Maintain a `public/_redirects` file from day one. Format: `[old-path] [new-path] 301`. Add an entry *in the same commit* as any page rename or deletion.
- Add a CI check (simple grep or a link-checker script) that scans the `_redirects` file for entries pointing to paths that no longer exist in `src/content/docs/`. This prevents stale redirect chains.
- Customize the `404.astro` (Starlight override) to include the site search box and top navigation — gives users a recovery path.
- Export a `sitemap.xml` and submit to Google Search Console at launch; use the "Remove URL" tool proactively for any pages that are deleted (not just renamed).

**Warning signs:**
- A PR renames a doc file with no corresponding `_redirects` entry.
- `404.astro` is the Starlight default stub (no search, no nav).
- GSC shows a spike in crawl errors after a content reorganization PR.

**Phase to address:**
Phase 1 (Bootstrap) — create `public/_redirects` stub. Phase 4 (Content Migration) — establish the "redirect-on-rename" discipline as a PR checklist item.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Copy `global.css` tokens into Starlight `customCss` manually | Fast bootstrap | Silent drift every time marketing tokens update; docs brand diverges | Never — use shared file or CI diff check from day one |
| Commit `openapi.json` snapshot once, never update | Reproducible first build | API reference describes dead endpoints within weeks of first backend change | Only acceptable if a CI job auto-PRs snapshot updates |
| Use `astro dev` to check docs search | Fast iteration | Pagefind does not run in dev mode; search bugs only visible in production builds | Never — always run `astro build && astro preview` for search validation |
| Flat URL structure (`/install`, `/admin`) | Clean URLs now | Versioning retrofit requires renaming every URL, breaking all external links | Never — add a path prefix (`/guides/`) from the start |
| Skip `_redirects` file until first rename happens | Nothing to do | First rename produces permanent link rot; discipline never gets established | Never — create stub file at bootstrap |
| Per-section OG templates with OKLCH colors | Brand consistency | Satori does not support `oklch()`, images render as black | Never — convert to hex/RGB in Satori templates at authoring time |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Cloudflare Pages (two projects, one repo) | Leave `rootDirectory` blank (defaults to repo root); both projects build from same directory | Explicitly set `rootDirectory` to each project's subpath in the CF dashboard; verify with a test deploy |
| Cloudflare Pages (build watch paths) | Default "watch everything" triggers both project builds on every push | Configure `include` paths per project (marketing: `src/**`, docs: `docs/**`) |
| Pagefind + Starlight code blocks | No exclusion configured; code content pollutes search results | Add `data-pagefind-ignore` to `<Code>` component overrides; audit index after every content phase |
| OpenAPI snapshot + FastAPI | Fetch live schema at build time from a staging URL that may be down | Commit snapshot to repo; add CI job in backend repo to auto-PR snapshot updates via `oasdiff` diff |
| Satori OG images + OKLCH tokens | Copy marketing site OKLCH values directly into OG template | Convert all OKLCH to hex/RGB for Satori; maintain a separate `og-colors.ts` constants file |
| GA4 analytics (subdomain) | Different Measurement ID for docs vs marketing | Use identical `G-XXXXXX` ID and same web data stream; confirm in GA4 Realtime on first deploy |
| GitHub legacy docs (canonical) | Leave `docs/install.md` in geolens repo after migration | Replace with stub files pointing to docs.getgeolens.com; submit sitemap to GSC immediately |
| Astro `site` config | Leave as `http://localhost:4321` or omit during development | Set `site: 'https://docs.getgeolens.com'` in `astro.config.mjs` at bootstrap before any build |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Satori OG image generation (no caching) | Build time >2 min on CF Pages free tier | Cache by content hash; switch to runtime PNG endpoint if >20s | ~80+ docs pages |
| Pagefind index too large (code blocks indexed) | Index download >1MB; slow search UI | `data-pagefind-ignore` on all code blocks | ~30+ pages with large code examples |
| OpenAPI reference page rendering all endpoints inline | Single page with 80+ operations generates huge HTML; Pagefind indexes all of it | Add `pagefind: false` to the API reference page; use tabbed/collapsible sections | Any size — happens on first ship |
| CF Pages build triggered for both projects on every push | Double build minutes; flaky schema fetch timing | Build watch path filtering per project | Day one without configuration |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Embedding real API keys in OpenAPI examples in docs | Keys scraped by crawlers, committed to public repo | Use placeholder format (`YOUR_API_KEY`, `gl_live_xxxx`) in all examples; never paste a real key |
| Docs build fetches live `openapi.json` from `api.getgeolens.com` | Production API becomes a build dependency; outage blocks docs deploy | Use committed snapshot; live fetch only in a scheduled CI update job, not in the deploy build |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Starlight default 404 page (no search, no nav) | Users who follow a broken link have no recovery path | Override `404.astro` to include site search and top nav |
| API reference page with no auth examples | Developers can't figure out how to authenticate; support burden | Add explicit `curl` examples with `Authorization: Bearer <token>` and `?api_key=<key>` to the intro section |
| Docs search returns code fragments as top results | Developers searching for "install postgres" see YAML snippets before the install guide prose | Exclude code blocks from Pagefind index at content authoring time |
| No "back to docs" link from 404 | Users stuck after renaming | Customize 404 page |
| Custom Starlight components without keyboard nav | Breaks WCAG AA parity with marketing site (which passed audit) | Any custom component must be audited with axe-core; tab order and focus management must be explicitly tested |

---

## "Looks Done But Isn't" Checklist

- [ ] **Starlight bootstrap:** `site` config set to `https://docs.getgeolens.com` — verify canonical tags in built HTML, not dev server
- [ ] **Design tokens:** Starlight `customCss` uses same OKLCH primary hue as `global.css` — verify both files show same hue value (should be ~250, blue, not emerald)
- [ ] **Cloudflare Pages projects:** Both projects have explicit `rootDirectory` set — verify by checking that a marketing-only change does NOT trigger the docs project build
- [ ] **Pagefind search:** Runs only after `astro build` — verify by running `astro build && astro preview` before any content phase PR is merged
- [ ] **OpenAPI snapshot:** `openapi.json` is committed to the repo and matches the current backend — verify by diffing against a fresh `GET /api/openapi.json` from the running app
- [ ] **Legacy markdown migration:** Every migrated file has `title` frontmatter, no `.md` cross-references, no `github.com/raw` image URLs — verify with `npx astro check`
- [ ] **_redirects file:** Exists in `public/` with at least a comment stub — verify file is present in the repo before Phase 4
- [ ] **GA4 analytics:** Docs site uses same Measurement ID as marketing site — verify in GA4 Realtime (should show combined session on cross-domain navigation)
- [ ] **Satori OG template:** No `oklch()` values in template — verify by checking built `.png` files are not black/blank
- [ ] **GitHub legacy docs:** `docs/install.md` and `docs/admin.md` in geolens repo replaced with migration stubs — verify GitHub renders stub text, not original content

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Version/peer mismatch discovered post-bootstrap | LOW | Pin specific Starlight version, run `npm install`, `npx astro check` |
| Design token drift discovered post-launch | MEDIUM | Create shared token file, update both config files, deploy both projects, do visual regression pass |
| CF Pages output directory conflict | LOW | Correct `rootDirectory` in CF dashboard, trigger manual redeploy |
| OpenAPI schema drift discovered | MEDIUM | Fetch fresh snapshot, commit, redeploy docs; add CI enforcement before next backend change |
| Pagefind code-block noise | LOW | Add `data-pagefind-ignore`, rebuild, redeploy |
| Dual canonical (GitHub + docs.getgeolens.com indexed) | HIGH (months to resolve) | Replace source files in geolens repo immediately; submit new sitemap; use Google Search Console "Request Indexing" on canonical URLs; may take 2-3 months for Google to deindex GitHub versions |
| URL structure rename after launch | HIGH | Write all redirects in `_redirects`, redeploy, submit URL removals to GSC, update all external links if known |
| OG images blank (OKLCH in Satori) | LOW | Replace OKLCH with hex in Satori template, rebuild |
| Versioning retrofit after flat URL launch | HIGH | Choose strategy (folder-prefix), rename all slugs, write redirects for every renamed page, rebuild Pagefind index |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Astro/Starlight version mismatch | Phase 1 (Bootstrap) | `npm ls @astrojs/starlight astro` shows compatible versions; `npx astro check` passes |
| Design token drift | Phase 1 (Bootstrap) + Phase 2 (Brand) | CI diff script passes; visual comparison of primary button color on both sites |
| CF Pages build contamination | Phase 1 (Bootstrap) | Marketing-only push triggers only marketing build in CF dashboard |
| OpenAPI schema drift | Phase 1 (Bootstrap, snapshot decision) + Phase 3 (API Reference) | Committed `openapi.json` diff matches live API; CI backend job configured |
| Pagefind code-block noise | Phase 2 (Content Structure) + Phase 4 (Migration) | Build + preview search for "postgres" returns prose results before YAML snippets |
| Markdown migration breakage | Phase 4 (Content Migration) | `npx astro check` passes; all internal links return 200 in local preview |
| Dual canonical indexing | Phase 1 (`site` config) + Phase 4 (stubs) | Built HTML shows correct `<link rel="canonical">`; GSC sitemap accepted |
| Versioning retrofit trap | Phase 1 (URL structure decision) | URL structure uses `/guides/` prefix; `version` frontmatter field added to schema |
| OG image Satori/OKLCH issue | Phase 2 (Brand/Design) | Built OG images are visually correct (not black); verified with og:debugger tool |
| Cross-domain analytics gap | Phase 1 (Bootstrap) | GA4 Realtime shows sessions on docs subdomain with same property |
| 404 link rot | Phase 1 (`_redirects` stub) + Phase 4 (rename discipline) | `public/_redirects` exists; CI check confirms no rename without redirect entry |

---

## Sources

- Starlight CSS custom properties and `customCss` configuration: https://starlight.astro.build/guides/css-and-tailwind/ (via Context7 `/withastro/starlight`)
- Starlight Pagefind configuration options: https://starlight.astro.build/guides/site-search/
- Pagefind `data-pagefind-ignore` and build-only constraint: https://github.com/withastro/starlight/issues/2824
- Cloudflare Pages monorepo documentation (root directory, build watch paths, 5-project limit): https://developers.cloudflare.com/pages/configuration/monorepos/
- Cloudflare Pages build caching: https://developers.cloudflare.com/pages/configuration/build-caching/
- Astro 6 content collections legacy compat removal: https://docs.astro.build/en/guides/upgrade-to/v6/
- Starlight Astro 6 support commit: https://github.com/withastro/starlight/commit/0d2e7ed74a604b028fcab0c81b4c35c0c9365343
- Starlight changelog: https://starlight-changelog.netlify.app/
- oasdiff breaking change detection: https://www.oasdiff.com/
- Scalar Astro OpenAPI integration: https://scalar.com/products/api-references/integrations/astro
- Satori build-time OG image cost and caching: https://ainoya.dev/posts/astro-ogp-build-cache/ and https://jilles.me/og-images-astro-build-vs-runtime/
- GA4 subdomain tracking (same measurement ID requirement): https://www.analyticsmania.com/post/subdomain-tracking-with-google-analytics-and-google-tag-manager/
- Starlight versioning community discussion (branch vs folder pain): https://github.com/withastro/starlight/discussions/957
- Cloudflare Pages `_redirects` for static sites: https://developers.cloudflare.com/pages/configuration/redirects/
- Astro Starlight frontmatter reference (required `title` field): https://starlight.astro.build/reference/frontmatter/
- Astro `site` config and canonical URL generation: https://docs.astro.build/en/reference/configuration-reference/

---
*Pitfalls research for: Astro Starlight docs site (docs.getgeolens.com) added to existing getgeolens-com Astro 6 marketing repo*
*Researched: 2026-04-25*
