---
phase: 224-brand-shell-search
verified: 2026-04-25T23:45:00Z
re_verified: 2026-04-26T00:05:00Z
status: gaps_found
score: 12/13 must-haves verified, 2 human items confirmed via Playwright, 1 new gap found
overrides_applied: 0
human_verification:
  - test: "Open docs site in browser at localhost (npm run preview in getgeolens.com/docs/). Verify accent color is blue (hue ~250), NOT Starlight's default purple, in both light and dark modes. Confirm link text and body text pass WCAG AA contrast."
    expected: "Blue accent visible on sidebar active states, links, focus rings, and button backgrounds in both modes. No purple visible. Contrast ratios >= 4.5:1 for normal text, >= 3:1 for large text."
    result: passed
    evidence: "Playwright probe (light + dark): --sl-color-accent = oklch(.46 .16 250) light / oklch(.7 .16 250) dark; active sidebar bg = oklch(0.46 0.16 250), text = white (~5.83:1 ratio, AA pass). Body text contrast 11.71:1 (AAA). Hue 250 throughout — no purple. Inter Variable loaded (7 weights). Screenshots: brand-light-mode.png, brand-dark-mode.png."
  - test: "Open docs site in browser. Press Ctrl+K (or Cmd+K on macOS). Verify Pagefind search dialog opens. Type a word that appears in the placeholder pages (e.g. 'quickstart'). Verify results are returned. Press Escape — verify dialog closes."
    expected: "Dialog opens on Ctrl+K/Cmd+K, returns at least one result for 'quickstart', closes on Escape."
    result: passed
    evidence: "Playwright probe: Cmd+K opened <dialog open>, focused .pagefind-ui__search-input. Typing 'quickstart' returned 2 results ('Quickstart (coming soon)', 'GeoLens Documentation'). Escape closed the dialog (dialog.open = false)."
gaps:
  - id: SHELL-05-layout-collision
    severity: medium
    plan: 224-04
    file: getgeolens.com/docs/src/components/DocsHeader.astro
    problem: "DocsHeader.astro renders the back-link as the first child of <header>, but Starlight's default header (rendered via the component slot) also positions itself starting at x=24 — same coordinate as the back-link. Result: 'GeoLens Docs' site title and '← getgeolens.com' back-link visually overlap in both light and dark modes."
    evidence: "Bounding rects via Playwright: back-link {x:24, y:0, w:122.8, h:63}, site-title {x:24, y:10.5, w:167.6, h:42} — overlap=true. Visible in brand-light-mode.png and brand-dark-mode.png."
    fix_hint: "Wrap the slot in a flex/grid container that reserves space for the back-link, OR move the back-link inside an absolutely-positioned wrapper that does not collide with the slot bounding box. Plan 04 SUMMARY mentions DocsHeader 'wraps Starlight's default Header.astro' but the wrapper does not displace the inner site-title."
---

# Phase 224: Brand, Shell & Search Verification Report

**Phase Goal:** The docs site looks and feels like a GeoLens property — primary blue accent (not Starlight default purple), Inter font, dark/light parity with the marketing site — and all shell navigation (sidebar, prev/next, breadcrumbs, 404, last-updated, edit links, search, cross-site nav) works correctly before any content is written.

**Verified:** 2026-04-25T23:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification
**Sibling repo inspected:** `/Users/ishiland/Code/getgeolens.com/`

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                             | Status       | Evidence                                                                                                         |
|----|---------------------------------------------------------------------------------------------------|--------------|------------------------------------------------------------------------------------------------------------------|
| 1  | Docs site accent color uses hue ~250 blue (not Starlight purple) in both modes                   | ? UNCERTAIN  | custom.css: `--primary-700: oklch(0.46 0.16 250)` (light), `--primary-400: oklch(0.70 0.16 250)` (dark). Token values confirmed. Rendered appearance and WCAG AA pass require human visual check.                   |
| 2  | Ctrl+K / Cmd+K opens Pagefind search dialog; returns relevant results; code blocks de-ranked     | ? UNCERTAIN  | dist/pagefind/pagefind.js + pagefind-entry.json exist. EC plugin registered in astro.config.mjs. Runtime dialog behavior requires browser probe.                                                                   |
| 3  | Every page shows "Last updated" timestamp, "Edit this page" GitHub link, and prev/next nav       | ✓ VERIFIED   | `lastUpdated: true` in astro.config.mjs; `editLink.baseUrl: 'https://github.com/geolens-io/getgeolens.com/edit/main/docs/'`; `pagination: true`. Build output: `<time datetime="2026-04-25T22:34:22.000Z">` in dist/guides/quickstart/index.html. Edit URL pattern confirmed in built HTML.          |
| 4  | Marketing site header has "Docs" link; docs site header has "Back to getgeolens.com" link        | ✓ VERIFIED   | Nav.astro line 90: `href="https://docs.getgeolens.com"` with `rel="noopener"` (NOT noreferrer), no target=_blank, positioned after Quickstart (line 79 < line 90). DocsHeader.astro: `href="https://getgeolens.com"` with `rel="noopener"`, absolute positioning. `verify-build.sh` SHELL-05 assertion passes.  |
| 5  | CI token-drift check fails if custom.css primary hue diverges from marketing global.css          | ✓ VERIFIED   | check-token-sync.sh: executable, STOPS=(50..900), skips 950, uses tr -s for normalization, exits 1 on drift. Wired in docs-ci.yml line 31 between npm ci (line 29) and astro check (line 34). `bash scripts/check-token-sync.sh` exits 0 against current files.                                           |

**Score:** 3/5 truths fully verified; 2/5 deferred to human (color rendering, keyboard shortcut runtime behavior).

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `docs/src/styles/custom.css` | ✓ VERIFIED | Full token bridge: --primary-50..950 OKLCH at hue 250 (verbatim marketing mirror), Inter Variable font import, 3 --sl-color-accent-* slots in :root (light) and :root[data-theme='dark'] (dark), --sl-color-accent aliased to --primary-700 |
| `docs/package.json` | ✓ VERIFIED | `"@fontsource-variable/inter": "^5.2.8"` confirmed |
| `docs/scripts/check-token-sync.sh` | ✓ VERIFIED | Executable, bash -n clean, STOPS 50–900, BRAND-04 header, tr -s normalization |
| `docs/scripts/verify-build.sh` | ✓ VERIFIED | All 6 Phase-223 assertions preserved + 11 Phase-224 assertions added. All pass against current dist/. |
| `.github/workflows/docs-ci.yml` | ✓ VERIFIED | Both actions/checkout@v4 have fetch-depth: 0; check-token-sync step present between npm ci and wrangler guard; valid YAML |
| `docs/plugins/ec-pagefind-weight.mjs` | ✓ VERIFIED | exports pluginPagefindWeight, uses definePlugin + postprocessRenderedBlock hook, sets 'data-pagefind-weight' = '0.1' |
| `docs/public/llms.txt` | ✓ VERIFIED | H1 "GeoLens Documentation", blockquote description, H2 Guides with 4 canonical /guides/ URLs |
| `docs/src/content/docs/guides/quickstart/index.mdx` | ✓ VERIFIED | title: "Quickstart (coming soon)", no pagefind: false |
| `docs/src/content/docs/guides/user/index.mdx` | ✓ VERIFIED | title: "User Guide (coming soon)", no pagefind: false |
| `docs/src/content/docs/guides/admin/index.mdx` | ✓ VERIFIED | title: "Admin Guide (coming soon)", no pagefind: false |
| `docs/src/content/docs/guides/api/index.mdx` | ✓ VERIFIED | title: "API Reference (coming soon)", no pagefind: false |
| `src/components/layout/Nav.astro` | ✓ VERIFIED | Docs link at line 90 (after Quickstart at line 79), href="https://docs.getgeolens.com", rel="noopener" only (noreferrer is on the separate GitHub icon anchor, not on the Docs link), no target=_blank |
| `docs/src/components/Breadcrumbs.astro` | ✓ VERIFIED | PageTitle override, aria-label="breadcrumb", aria-current="page" on leaf, imports from @astrojs/starlight/components/PageTitle.astro, showBreadcrumbs gate at >=2 segments |
| `docs/src/components/DocsHeader.astro` | ✓ VERIFIED | Header override, href="https://getgeolens.com", rel="noopener", position: absolute (NOT display:contents), imports Header.astro, no duplicate Cmd+K listener |
| `docs/src/pages/404.astro` | ✓ VERIFIED | template:'splash', prev/next/editUrl/lastUpdated/pagefind all false, Search component, 4 category cards (/guides/quickstart/user/admin/api), footer link to getgeolens.com, --primary-700 for brand mark, no hardcoded #hex or rgb() |
| `docs/astro.config.mjs` | ✓ VERIFIED | editLink.baseUrl with trailing slash and /docs/ segment; pagination: true; lastUpdated: true; expressiveCode.plugins: [pluginPagefindWeight()]; components: { Header, PageTitle }; all Phase-223 settings preserved |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| astro.config.mjs | Breadcrumbs.astro + DocsHeader.astro | `components: { PageTitle: ..., Header: ... }` | ✓ WIRED | Both paths confirmed in astro.config.mjs lines 30–33 |
| astro.config.mjs | ec-pagefind-weight.mjs | `import { pluginPagefindWeight }` + expressiveCode.plugins | ✓ WIRED | Import at line 5; registered at line 26 |
| Breadcrumbs.astro | @astrojs/starlight/components/PageTitle.astro | `import Default from '...'` | ✓ WIRED | Line 5 of Breadcrumbs.astro |
| DocsHeader.astro | @astrojs/starlight/components/Header.astro | `import Default from '...'` | ✓ WIRED | Line 13 of DocsHeader.astro |
| 404.astro | virtual:starlight/components/Search | `import Search from 'virtual:starlight/components/Search'` | ✓ WIRED | Line 10 of 404.astro; env.d.ts resolves TS declaration |
| docs-ci.yml | check-token-sync.sh | `bash scripts/check-token-sync.sh` step | ✓ WIRED | Line 31, between npm ci (29) and wrangler guard (32) |
| docs-ci.yml (both jobs) | full git history | `fetch-depth: 0` | ✓ WIRED | Lines 23 and 52 |
| marketing Nav.astro | docs.getgeolens.com | `href="https://docs.getgeolens.com"` anchor | ✓ WIRED | Lines 89–98 of Nav.astro |
| custom.css | marketing global.css palette | verbatim OKLCH triplets 50–900 at hue 250 | ✓ WIRED | check-token-sync.sh exits 0 confirming byte-identical values for all 10 stops |

### Data-Flow Trace (Level 4)

Not applicable — this phase delivers static site configuration, CSS tokens, and shell components. There is no dynamic data source (no API calls, no database reads). The only "data" is build-time: git commit timestamps flowing into `<time datetime>` via Starlight's lastUpdated mechanism. This is verified: `<time datetime="2026-04-25T22:34:22.000Z">` present in dist/guides/quickstart/index.html.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Token-drift script exits 0 against current custom.css | `bash scripts/check-token-sync.sh` | "All 10 --primary-* stops in sync between marketing and docs." | ✓ PASS |
| All 17 build-artifact assertions pass | `bash scripts/verify-build.sh` | "All build-artifact assertions passed." | ✓ PASS |
| lastUpdated <time datetime> in built quickstart page | grep in dist/guides/quickstart/index.html | `<time datetime="2026-04-25T22:34:22.000Z">` | ✓ PASS |
| Breadcrumb nav in built quickstart page | grep in dist/guides/quickstart/index.html | `aria-label="breadcrumb"` found | ✓ PASS |
| Docs back-link in built homepage | grep in dist/index.html | `href="https://getgeolens.com"` found | ✓ PASS |
| Pagefind files in dist/ | ls check | pagefind.js + pagefind-entry.json both present | ✓ PASS |
| Cmd+K opens search dialog | browser probe | DEFERRED — requires running browser | ? SKIP |
| Blue accent renders correctly in both modes | visual inspection | DEFERRED — requires running browser | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| BRAND-01 | 224-01, 224-02 | OKLCH primary blue accent in custom.css Starlight slots | ✓ SATISFIED | custom.css: full 11-stop palette + 3 slot mappings; verify-build.sh BRAND-01 passes |
| BRAND-02 | 224-01, 224-02 | Inter Variable font via @fontsource-variable/inter | ✓ SATISFIED | package.json ^5.2.8; @import in custom.css; --sl-font set; no Google CDN refs in dist/ |
| BRAND-03 | 224-01, 224-04 | Dark + light mode GeoLens blue, WCAG AA contrast | ? NEEDS HUMAN | Token values correct (hue 250 in both modes). Visual pass and contrast ratios require browser |
| BRAND-04 | 224-02 | CI script fails on token drift between global.css and custom.css | ✓ SATISFIED | check-token-sync.sh exists, executable, asserts stops 50–900, wired in docs-ci.yml |
| SHELL-01 | 224-03, 224-04 | Sidebar groups: Quickstart, User Guide, Admin Guide, API Reference | ✓ SATISFIED | astro.config.mjs sidebar autogenerate blocks; 4 placeholder index.mdx files; verify-build.sh SHELL-01 passes |
| SHELL-02 | 224-04 | Prev/next, breadcrumbs, edit-this-page link per page | ✓ SATISFIED | pagination: true; Breadcrumbs.astro wired as PageTitle override; editLink.baseUrl set; all confirmed in dist/ |
| SHELL-03 | 224-04 | Custom 404 with search + category links | ✓ SATISFIED | 404.astro exists with Search, 4 cards, footer link; dist/404.html passes all verify-build.sh assertions |
| SHELL-04 | 224-02, 224-04 | lastUpdated: true + fetch-depth: 0 in CI | ✓ SATISFIED | lastUpdated: true in config; fetch-depth: 0 on both CI jobs; <time datetime> in dist/guides/quickstart/index.html |
| SHELL-05 | 224-03, 224-04 | Cross-site nav: marketing "Docs" link + docs "Back to getgeolens.com" link | ✓ SATISFIED | Nav.astro Docs link confirmed; DocsHeader.astro back-link confirmed; both verified in built dist/ |
| SEARCH-01 | 224-04 | Pagefind built in, no external service | ✓ SATISFIED | dist/pagefind/pagefind.js + pagefind-entry.json present; verify-build.sh SEARCH-01 passes |
| SEARCH-02 | 224-03, 224-04 | Code blocks de-prioritized in Pagefind via data-pagefind-weight | ✓ SATISFIED | ec-pagefind-weight.mjs registered in expressiveCode.plugins; postprocessRenderedBlock hook sets '0.1'; smoke assertion passes |
| SEARCH-03 | 224-04 | Keyboard shortcut opens search dialog | ? NEEDS HUMAN | Starlight 0.38.4 native Cmd+K binding confirmed by source inspection. Runtime dialog behavior requires browser probe. |
| SEO-04 | 224-03, 224-02 | llms.txt at site root with guide navigation | ✓ SATISFIED | docs/public/llms.txt with 4 canonical /guides/ URLs; dist/llms.txt confirmed by verify-build.sh |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| docs/src/content/docs/guides/quickstart/index.mdx | body | "coming soon" placeholder | ℹ Info | Intentional per D-35; content ships in Phase 226. Not a stub — page is search-indexable. |
| docs/src/content/docs/guides/user/index.mdx | body | "coming soon" placeholder | ℹ Info | Intentional per D-35; content ships in Phase 227. |
| docs/src/content/docs/guides/admin/index.mdx | body | "coming soon" placeholder | ℹ Info | Intentional per D-35; content ships in Phase 227. |
| docs/src/content/docs/guides/api/index.mdx | body | "coming soon" placeholder | ℹ Info | Intentional per D-35; content ships in Phase 225. |

No blocker anti-patterns found. Placeholder pages are intentional and search-indexable. No hardcoded colors, no empty handlers, no stub components.

### Human Verification Required

#### 1. BRAND-03 — Blue accent visual verification and WCAG AA contrast

**Test:** Run `npm run preview` in `/Users/ishiland/Code/getgeolens.com/docs/`. Open the preview URL in a browser. Navigate to any guide page. Toggle between light and dark modes using the theme switcher. Compare the accent color to the marketing site (`getgeolens.com` — open in a second tab for reference).

**Expected:** Accent color is blue (~hue 250, similar to the marketing site's primary blue on buttons and links) in BOTH modes. No purple visible. Run a contrast checker (e.g. browser devtools) on link text to confirm >= 4.5:1 contrast ratio on body background.

**Why human:** CSS custom properties (OKLCH) resolve at render time. Static inspection confirms the token values are correct (hue 250, --primary-700 for light mode, --primary-400 for dark mode) but rendered appearance and contrast ratios against Starlight's actual background colors can only be confirmed visually in a browser.

#### 2. SEARCH-03 — Keyboard shortcut opens Pagefind search dialog

**Test:** With the preview server running, navigate to any docs page. Press `Ctrl+K` (Windows/Linux) or `Cmd+K` (macOS). Verify the Pagefind search dialog opens. Type "quickstart" and verify results appear. Press `Escape` — verify the dialog closes and focus returns to the trigger.

**Expected:** Dialog opens on Ctrl+K/Cmd+K; returns at least one result for "quickstart"; closes cleanly on Escape.

**Why human:** Runtime JavaScript keyboard event behavior requires a running browser. Static inspection confirms Starlight 0.38.4's native binding exists at Search.astro:118-124 and that no duplicate listener was added. Whether the binding works end-to-end with our DocsHeader override in place must be verified in a real browser.

### Gaps Summary

No programmatically verifiable gaps found. The phase goal is substantively achieved:

- The token bridge is complete with verbatim OKLCH hue-250 values mirrored from marketing
- All shell affordances (breadcrumbs, edit links, last-updated, prev/next, 404, back-link, cross-site nav) are wired and confirmed in the built dist/
- The BRAND-04 CI drift gate is functional and wired into the correct CI step order
- All 17 verify-build.sh assertions pass (6 Phase-223 + 11 Phase-224)
- check-token-sync.sh exits 0 with correct token sync

The two human_needed items are runtime browser behaviors (color rendering accuracy and keyboard shortcut functionality) that cannot be verified from static file inspection alone. They do not represent implementation gaps — the code is correct — but they require a human to confirm the end-to-end browser experience before the phase is considered fully closed.

---

_Verified: 2026-04-25T23:45:00Z_
_Verifier: Claude (gsd-verifier)_
