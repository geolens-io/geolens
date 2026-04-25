# Phase 224: Brand, Shell & Search - Context

**Gathered:** 2026-04-25
**Status:** Ready for planning
**Discussion mode:** User chose "best-practice defaults across all gray areas" — every decision below is Claude's reasoned default rather than a user-stated preference. Surface anything controversial in PLAN-CHECK or as a checkpoint during execution.

<domain>
## Phase Boundary

Make the docs site look and feel like a GeoLens property — full OKLCH primary-blue token bridge, Inter font, dark/light parity — and ship every shell-navigation feature (sidebar labels, prev/next, breadcrumbs, edit-this-page, last-updated, custom 404, Pagefind search with Cmd+K shortcut, cross-site nav links, llms.txt) BEFORE any content phase begins. Scope is brand + shell + search infrastructure only — no Quickstart/Install/User/Admin/API content (those are phases 225-227).

</domain>

<carryover_from_phase_223>
## Locked from Phase 223 (do not re-decide)

- **D-09 (refined):** `docs/src/styles/custom.css` ships only a 3-line accent placeholder in 223 — phase 224 expands this to the full 50–950 mapping per BRAND-01.
- **D-11:** Sidebar groups (Quickstart, User Guide, Admin Guide, API Reference) declared upfront in 223's `astro.config.mjs` with `/guides/` autogenerate paths. SHELL-01 is essentially shipped — phase 224 adds nav labels and `lastUpdated: true`, nothing structural.
- **D-12:** Inter font deferred to this phase. BRAND-02 owns `@fontsource-variable/inter` install + `--sl-font` wiring.
- **D-13:** Default theme = system preference (Starlight default). BRAND-03 verifies dark/light parity in this phase.
- **D-17:** `site: 'https://docs.getgeolens.com'` is locked — canonical URL anchor. Do not change.
- **D-19:** GA4 deferred to phase 228. Not in scope here.
- **Phase 223 verify-build.sh** is the load-bearing build-artifact gate. Phase 224 adds new assertions (drift check); do NOT remove or weaken existing assertions.
- **Marketing site primary blue source of truth:** `/Users/ishiland/Code/getgeolens.com/src/styles/global.css` `:root` block, OKLCH at hue 250, 10 stops (50–900). The comment block in that file flags WCAG AA: primary-700 (`oklch(0.46 0.16 250)`) is the minimum for body-text-on-white. Primary-500/600 are decorative-only.
- **GitHub repo for edit-this-page links:** `geolens-io/getgeolens.com`. Edit URL pattern: `https://github.com/geolens-io/getgeolens.com/edit/main/docs/src/content/docs/{slug}.mdx`.
- **Cross-repo topology:** Both marketing site and docs subtree live in the same `getgeolens.com` repo. BRAND-04's drift check is therefore an in-repo bash script — no cross-repo coordination needed.

</carryover_from_phase_223>

<decisions>
## Implementation Decisions

### Token Bridge (BRAND-01)
- **D-01:** Map only `--sl-color-accent-*` stops (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950) per BRAND-01's literal language. Do NOT remap Starlight's surface/gray/text tokens — Starlight's dark-mode tuning is non-trivial and any change risks breaking parity. Out of scope per BRAND-01 anyway.
- **D-02:** Reconcile the 10-stop marketing scale with Starlight's 11-stop scale by extrapolating `--sl-color-accent-950: oklch(0.22 0.07 250)` (continues the lightness/chroma trend from 800→900). The 950 stop is used by Starlight only for darkest-mode hover states — pure aesthetic, not load-bearing.
- **D-03:** Alias `--sl-color-accent` (Starlight's body-link color, defaults to accent-600) to `--primary-700` (`oklch(0.46 0.16 250)`) for WCAG AA insurance. Marketing's own comment block locks 700 as the body-text-on-white minimum — applying the same constraint to docs link text avoids contrast regressions.
- **D-04:** Map both light and dark mode in `[data-theme="light"]` and `[data-theme="dark"]` blocks. Light mode uses the marketing values directly. Dark mode mirrors them (Starlight uses the same accent scale in both modes; the surface tokens differ).
- **D-05:** Do NOT install `@astrojs/starlight-tailwind` (BRAND-01 explicit prohibition; also rejected in REQUIREMENTS.md Out of Scope).

### Token Drift Detection (BRAND-04)
- **D-06:** Ship `docs/scripts/check-token-sync.sh` — bash script that:
  - Reads `getgeolens.com/src/styles/global.css` and `getgeolens.com/docs/src/styles/custom.css`
  - For each primary stop (50, 100, ..., 900), greps the OKLCH triplet from each file
  - Normalizes whitespace and decimal precision (e.g., `0.55` ≡ `0.550`)
  - Asserts the triplets match between files
  - Skips stop 950 (extrapolated, no marketing source)
  - Exits 1 with a clear diff message on mismatch
- **D-07:** Wire `check-token-sync.sh` into `docs-ci.yml` as a step BETWEEN `astro check` and `npm run build`. Failing this script fails the build (and therefore the deploy). Same load-bearing posture as `verify-build.sh`.
- **D-08:** Document in `docs/scripts/check-token-sync.sh` header comment: this script is the runtime enforcement of BRAND-04. Phase 227 (CONTRIBUTING.md update) will document the maintenance convention prose-side.

### Inter Font (BRAND-02)
- **D-09:** Install `@fontsource-variable/inter` (matches marketing pin). Apply via `--sl-font: 'Inter Variable', ui-sans-serif, system-ui, sans-serif;` in `custom.css`. No fallback chain divergence from marketing.
- **D-10:** Self-host the variable font file (no Google Fonts CDN). Matches marketing's posture and respects user privacy.

### Dark/Light Parity (BRAND-03)
- **D-11:** No theme-override JS or FOUC script — Starlight's default `data-theme` switching with system-preference auto-detect is sufficient.
- **D-12:** Verification deliverable: a screenshot pair (light + dark) of the homepage and one sidebar page (Quickstart placeholder), captured during phase verification, attached to phase summary. Confirms WCAG AA contrast pass on body and link text in both modes.

### Sidebar Labels (SHELL-01)
- **D-13:** Add user-facing `label` properties to the sidebar groups already declared in `astro.config.mjs`. Group labels: `Quickstart`, `User Guide`, `Admin Guide`, `API Reference`. Items inside autogenerate from `src/content/docs/guides/{quickstart,user,admin,api}/` directories.
- **D-14:** `lastUpdated: true` and `pagination: true` (if not already enabled by Starlight default) — set at the Starlight integration level, applies to all pages.
- **D-15:** No collapse/expand defaults change — Starlight's defaults work.

### Prev/Next, Breadcrumbs, Edit-This-Page (SHELL-02)
- **D-16:** Prev/next nav: Starlight default (`pagination: true`).
- **D-17:** Breadcrumbs: Starlight does NOT ship breadcrumbs by default; SHELL-02 requires them. Implement via a custom `<Breadcrumbs.astro>` component injected into Starlight's `PageFrame` or `PageSidebar` slot via the `components` override config. Render based on the page's URL path segments.
- **D-18:** Edit-this-page: enable Starlight's `editLink.baseUrl: 'https://github.com/geolens-io/getgeolens.com/edit/main/docs/'`. Starlight auto-appends the file slug.

### Last Updated (SHELL-04)
- **D-19:** `lastUpdated: true` (already set per D-14). Source: git history. Works in CF Pages because the build environment has git access (CF clones the repo).
- **D-20:** No frontmatter override fallback — git history is the single source.

### Custom 404 (SHELL-03)
- **D-21:** Custom `docs/src/pages/404.astro` (Astro page, NOT Starlight content collection — Starlight doesn't auto-generate a 404 with the required affordances).
- **D-22:** 404 page contents:
  - Brand-colored "404" mark using `--sl-color-accent` (primary-700)
  - Heading: "Page not found"
  - Short copy: "The page you're looking for might have moved to a different section."
  - Pagefind search input (reuse Starlight's `<Search />` component if accessible, otherwise mount Pagefind UI directly)
  - 4 category cards linking to: `/guides/quickstart`, `/guides/user`, `/guides/admin`, `/guides/api`
  - Footer link: "Or head back to getgeolens.com" → `https://getgeolens.com`
- **D-23:** No SEO metadata changes — the page-wide noindex from phase 223 stays in effect (until phase 228 flips it).

### Cross-Site Navigation (SHELL-05)
- **D-24:** Marketing-side: add `<a href="https://docs.getgeolens.com">Docs</a>` to `getgeolens.com/src/components/layout/Nav.astro` AFTER the "Quickstart" entry. Use the same `nav-link`/`nav-link-active` styling. No active state (different subdomain).
- **D-25:** Docs-side: add a `← getgeolens.com` link in the LEFT cluster of the Starlight header, near the logo. Implement via Starlight's `components.Header` override pointing to a custom `<DocsHeader.astro>` that wraps Starlight's default Header and prepends the back-link. The arrow + lowercase domain matches the Cloudflare/Vercel/Stripe pattern for docs-subdomain children.
- **D-26:** No external-link icon on either link — both domains share brand identity and the URL change is sufficient affordance. Both links use `rel="noopener"` defensively (industry hygiene, not security-critical here).

### Pagefind Search (SEARCH-01, SEARCH-02, SEARCH-03)
- **D-27:** Pagefind ships built-in with Starlight — SEARCH-01 is satisfied by enabling `pagefind: true` in the Starlight config (default) and ensuring the build emits `dist/pagefind/`.
- **D-28:** Code-block ranking: use `data-pagefind-weight="0.1"` on rendered `<pre>` blocks (NOT `data-pagefind-ignore`). Code stays findable but prose ranks above it. Implement via a Starlight Code component override OR an Astro rehype plugin that adds the attribute at build time. This matches Stripe Docs / Vercel Docs / Cloudflare Docs convention — avoids the trap of code-only pages disappearing from search.
- **D-29:** Keyboard shortcut: support BOTH `/` (Starlight default, do NOT override) AND `Cmd+K`/`Ctrl+K` (additive). Cmd+K is the universal docs/app convention (GitHub, Linear, Stripe, Vercel). Implement via a small client-side `keydown` listener in a custom Header that triggers Starlight's existing search dialog API.
- **D-30:** Do not override `/` (it must remain free for "type-to-search" inside any input field, including the search dialog itself).

### llms.txt (SEO-04)
- **D-31:** Ship a stub `docs/public/llms.txt` in this phase with: site title, canonical URL, brief description, and the four sidebar group URLs. Full structured outline (per-page summaries) lands incrementally as phases 226-227 add content. Phase 228 will revisit for a final polish before launch.
- **D-32:** llms.txt format: per the [llms.txt spec](https://llmstxt.org/) — a markdown document at the site root that describes the site's structure for AI tools. Minimal viable shape:
  ```
  # GeoLens Documentation

  > Documentation for the GeoLens self-hosted GIS data catalog.

  ## Guides
  - [Quickstart](https://docs.getgeolens.com/guides/quickstart): ...
  - [User Guide](https://docs.getgeolens.com/guides/user): ...
  - [Admin Guide](https://docs.getgeolens.com/guides/admin): ...
  - [API Reference](https://docs.getgeolens.com/guides/api): ...
  ```
- **D-33:** Add a verify-build.sh assertion: `dist/llms.txt` exists and contains the four `/guides/` URLs.

### CI Wiring
- **D-34:** Order of CI steps in updated `docs-ci.yml`:
  1. checkout
  2. node setup (from .nvmrc)
  3. `cd docs && npm ci`
  4. `bash scripts/check-token-sync.sh` (BRAND-04 — fails fast before the longer build)
  5. `npx astro check` (CI-02, unchanged)
  6. `npm run build` (unchanged)
  7. `bash scripts/verify-build.sh` (unchanged + new llms.txt assertion)
  8. `cloudflare/pages-action@v1` deploy (unchanged)
  Phase 223's existing wrangler-name guard step stays where it is.

### Scope Bounds (in this phase)
- **D-35:** No content additions — Quickstart prose is phase 226, User/Admin guides are phase 227, API reference is phase 225. The `/guides/{quickstart,user,admin,api}/` directories may have empty `index.mdx` placeholders this phase to make sidebar autogenerate work, but no real content.
- **D-36:** No marketing-site changes beyond the single `Nav.astro` patch (SHELL-05). The marketing /features page (which is the marketing half of deferred phase 216) is phase 228 scope, not 224.
- **D-37:** No OG image pipeline — that's phase 228 (SEO-02).

### Out of Scope for Phase 224 (deferred)
- Marketing /features page → Phase 228
- Per-page OG images → Phase 228 (SEO-02)
- Sitemap submission to Google Search Console → Phase 228 (SEO-03)
- Robots.txt / noindex flip → Phase 228 (SEO-03)
- GA4 install on either site → Phase 228 (SEO-06)
- A11Y audit + Lighthouse CI → Phase 228
- llms.txt full content → Phase 228 (this phase ships the stub only)
- API reference content → Phase 225 (API-01..05)
- Quickstart/Install content → Phase 226 (QUICK-01..04)
- User guide / Admin guide content → Phase 227 (USER-*, ADMIN-*)
- CF Pages deploy verification (DEPLOY-01..04) → still deferred from Phase 223

### Claude's Discretion
- Exact `<Breadcrumbs.astro>` markup (semantic `<nav aria-label="breadcrumb">` with ordered list, separator character, current-page handling)
- Exact Code-component override mechanism for `data-pagefind-weight="0.1"` (Starlight components override vs rehype plugin — researcher will recommend based on Starlight 0.38.4 patterns)
- Exact 404 page CSS (must use design tokens — no hardcoded colors)
- Exact Cmd+K hook implementation (Starlight's search-dialog API surface — researcher will document)
- Whether to extract token values to a shared JSON manifest both files import (premature; current global.css → custom.css copy is fine for two consumers)
- Inter font weight subset (assume 400, 500, 600, 700 — common subset; full variable axis is fine if size budget permits)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Specs
- `.planning/REQUIREMENTS.md` §Brand & Theming (BRAND-01..04), §Site Shell & Navigation (SHELL-01..05), §Search (SEARCH-01..03), §SEO (SEO-04) — locked acceptance criteria for this phase
- `.planning/PROJECT.md` §Current Milestone (v15.0) — milestone context
- `.planning/ROADMAP.md` §Phase 224 — goal, depends-on, success criteria

### Phase 223 Outputs (this phase builds on)
- `.planning/phases/223-bootstrap-infrastructure-lock/223-CONTEXT.md` — D-01..D-20 locked decisions, especially D-09, D-11, D-12, D-13
- `.planning/phases/223-bootstrap-infrastructure-lock/223-01-SUMMARY.md` — what shipped: scaffold, sidebar groups, robots.txt, _redirects, verify-build.sh
- `.planning/phases/223-bootstrap-infrastructure-lock/223-02-SUMMARY.md` — what shipped: docs-ci.yml, marketing ci.yml paths-ignore patch
- `.planning/phases/223-bootstrap-infrastructure-lock/223-VERIFICATION.md` — file-side verified, deploy deferred

### Implementation Repo Reference Files (parity targets)
The docs site lives in the sibling repo `/Users/ishiland/Code/getgeolens.com`. This phase modifies these files:

**Modify in this phase:**
- `getgeolens.com/docs/src/styles/custom.css` — expand from 3-line placeholder to full 50–950 token bridge + Inter font registration
- `getgeolens.com/docs/astro.config.mjs` — add `editLink`, `pagination`, `lastUpdated`, sidebar labels, components override for Header + Breadcrumbs + Code
- `getgeolens.com/docs/package.json` — add `@fontsource-variable/inter` dependency
- `getgeolens.com/.github/workflows/docs-ci.yml` — wire `check-token-sync.sh` step
- `getgeolens.com/docs/scripts/verify-build.sh` — add llms.txt assertion
- `getgeolens.com/src/components/layout/Nav.astro` — add "Docs" link (SHELL-05 marketing side)

**Create in this phase:**
- `getgeolens.com/docs/scripts/check-token-sync.sh` — BRAND-04 drift detection
- `getgeolens.com/docs/src/components/Breadcrumbs.astro` — SHELL-02 breadcrumbs
- `getgeolens.com/docs/src/components/DocsHeader.astro` — SHELL-05 docs-side back-link + Cmd+K shortcut hook
- `getgeolens.com/docs/src/pages/404.astro` — SHELL-03 custom 404
- `getgeolens.com/docs/public/llms.txt` — SEO-04 stub
- `getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx` (placeholder for sidebar autogenerate)
- `getgeolens.com/docs/src/content/docs/guides/user/index.mdx` (placeholder)
- `getgeolens.com/docs/src/content/docs/guides/admin/index.mdx` (placeholder)
- `getgeolens.com/docs/src/content/docs/guides/api/index.mdx` (placeholder)

**Read for parity (do NOT modify):**
- `getgeolens.com/src/styles/global.css` — token source of truth (10 OKLCH stops at hue 250)
- `getgeolens.com/package.json` — Inter pin reference (`@fontsource-variable/inter` version)

### External Documentation (research targets)
- Starlight 0.38.4 docs: https://starlight.astro.build/ — components override, editLink, sidebar config, search/Pagefind, head config
- Pagefind: https://pagefind.app/docs/weighting/ — `data-pagefind-weight` attribute spec
- llms.txt spec: https://llmstxt.org/ — format reference for SEO-04
- Starlight components override mechanism: https://starlight.astro.build/guides/overriding-components/

### Anti-Patterns / Out of Scope (do not introduce)
- `@astrojs/starlight-tailwind` plugin (D-05; explicitly rejected in BRAND-01 + REQUIREMENTS.md Out of Scope)
- npm/pnpm workspaces (rejected in REQUIREMENTS.md)
- Live `openapi.json` fetch at build (rejected; phase 225 commits a snapshot)
- Mintlify/Docusaurus/VitePress (rejected upstream)
- GA4 in this phase (D-19 of phase 223, deferred to 228)
- Robots.txt / noindex changes (locked until phase 228)
- Marketing /features page changes beyond the single Nav.astro patch
- Any token-bridge approach using JS at runtime (must be CSS-only)

</canonical_refs>

<deferred_ideas>
## Deferred Ideas (parking lot)

(None surfaced during discussion — user delegated all gray areas to best-practice defaults. If the planner or executor surfaces additional questions during research/implementation, capture them here on update.)

</deferred_ideas>
