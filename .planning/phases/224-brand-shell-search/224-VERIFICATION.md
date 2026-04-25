---
phase: 224-brand-shell-search
verified: 2026-04-25T23:45:00Z
re_verified: 2026-04-26T00:30:00Z
status: passed
score: 13/13 must-haves verified (12 prior + 1 SHELL-05 closed); 2 prior human items confirmed via Playwright
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 12/13
  gaps_closed:
    - "SHELL-05-layout-collision — DocsHeader.astro back-link no longer overlaps SiteTitle in any (viewport × mode) combination"
  gaps_remaining: []
  regressions: []
  scope_audit:
    files_modified_by_closure: 3
    expected_files_modified: 3
    custom_css_touched: false
    astro_config_touched: false
    nav_astro_touched: false
    other_phase_224_artifacts_touched: false
human_verification:
  - test: "Open docs site in browser at localhost (npm run preview in getgeolens.com/docs/). Verify accent color is blue (hue ~250), NOT Starlight's default purple, in both light and dark modes. Confirm link text and body text pass WCAG AA contrast."
    expected: "Blue accent visible on sidebar active states, links, focus rings, and button backgrounds in both modes. No purple visible. Contrast ratios >= 4.5:1 for normal text, >= 3:1 for large text."
    result: passed
    evidence: "Playwright probe (light + dark): --sl-color-accent = oklch(.46 .16 250) light / oklch(.7 .16 250) dark; active sidebar bg = oklch(0.46 0.16 250), text = white (~5.83:1 ratio, AA pass). Body text contrast 11.71:1 (AAA). Hue 250 throughout — no purple. Inter Variable loaded (7 weights). Screenshots: brand-light-mode.png, brand-dark-mode.png."
  - test: "Open docs site in browser. Press Ctrl+K (or Cmd+K on macOS). Verify Pagefind search dialog opens. Type a word that appears in the placeholder pages (e.g. 'quickstart'). Verify results are returned. Press Escape — verify dialog closes."
    expected: "Dialog opens on Ctrl+K/Cmd+K, returns at least one result for 'quickstart', closes on Escape."
    result: passed
    evidence: "Playwright probe: Cmd+K opened <dialog open>, focused .pagefind-ui__search-input. Typing 'quickstart' returned 2 results ('Quickstart (coming soon)', 'GeoLens Documentation'). Escape closed the dialog (dialog.open = false)."
gaps: []
---

# Phase 224: Brand, Shell & Search Verification Report

**Phase Goal:** The docs site looks and feels like a GeoLens property — primary blue accent (not Starlight default purple), Inter font, dark/light parity with the marketing site — and all shell navigation (sidebar, prev/next, breadcrumbs, 404, last-updated, edit links, search, cross-site nav) works correctly before any content is written.

**Initially Verified:** 2026-04-25T23:45:00Z
**Re-verified (post-gap-closure):** 2026-04-26T00:30:00Z
**Status:** passed
**Re-verification:** Yes — after Plan 224-05 closed SHELL-05-layout-collision
**Sibling repo inspected:** `/Users/ishiland/Code/getgeolens.com/`

---

## Re-Verification Summary (Plan 224-05 Closure)

### Gap Closed: SHELL-05-layout-collision

**Original problem:** DocsHeader.astro's back-link and Starlight's SiteTitle both rendered at x=24, causing visual overlap in both light and dark modes.

**Fix shipped (3 commits in `getgeolens.com` repo, all on `main`):**

| Commit | Type | Scope |
|--------|------|-------|
| `ee04f41` | fix | `docs/src/components/DocsHeader.astro` — added `:root { --back-link-reserved-space: 10rem }` and `:global(.header > .title-wrapper) { padding-inline-start: var(--back-link-reserved-space) }` |
| `eea9d04` | test | `docs/scripts/verify-shell-layout.mjs` — Playwright runtime non-overlap probe (130 lines) |
| `9e75b63` | chore | `docs/scripts/verify-build.sh` — 2 source-side grep assertions guarding the SHELL-05 reservation |

**Files touched:** Exactly the 3 expected files. `custom.css`, `astro.config.mjs`, `Nav.astro`, `Breadcrumbs.astro`, `404.astro`, `docs-ci.yml`, `check-token-sync.sh`, `ec-pagefind-weight.mjs` — all untouched.

### Closure Evidence (from 224-05-SUMMARY.md, captured verbatim)

The mandatory runtime probe `node scripts/verify-shell-layout.mjs` against `npm run preview` produced:

```
PASS [desktop 1280x800 light]: back-link.right=146.8 ; site-title.left=180.0
PASS [desktop 1280x800 dark]:  back-link.right=146.8 ; site-title.left=180.0
PASS [mobile  360x800 light]:  back-link.right=138.8 ; site-title.left=172.0
PASS [mobile  360x800 dark]:   back-link.right=138.8 ; site-title.left=172.0
All shell-layout assertions passed.
```

**Bounding-rect proof of non-overlap:**

| Viewport × Mode | back-link.right | site-title.left | Gap | Overlap |
|---|---|---|---|---|
| desktop 1280×800 light | 146.8 | 180.0 | 33.2px | NO |
| desktop 1280×800 dark  | 146.8 | 180.0 | 33.2px | NO |
| mobile  360×800  light | 138.8 | 172.0 | 33.2px | NO |
| mobile  360×800  dark  | 138.8 | 172.0 | 33.2px | NO |

Pre-fix baseline (from initial VERIFICATION): both rects shared `x=24`. Post-fix: site-title starts at `x=180` desktop / `x=172` mobile. The 33.2px gap exceeds the 8px target by ~4×. Format of the 4 PASS lines matches the script's `console.log` template at `verify-shell-layout.mjs:81` exactly (`.toFixed(1)` precision confirmed).

### Locked Decisions: NEGATIVE-VERIFIED Preserved

Comment-stripped grep on the post-fix `DocsHeader.astro` (using a Python regex pass that strips both `/* … */` and `//` comments) found **zero actual CSS rules or JS handlers** matching the prohibited patterns. All "FOUND" hits in raw-text grep came from rationale comments documenting what was intentionally avoided.

| Decision | Pattern | Status | Evidence |
|---|---|---|---|
| D-25 absolute positioning | `display:\s*contents` | ✓ PRESERVED | 0 actual CSS rules; 1 mention in `//` rationale comment (line 7-8) |
| D-25 absolute positioning | `grid-column` | ✓ PRESERVED | 0 actual CSS rules; 1 mention in `//` rationale comment (line 7-8) |
| D-26 noopener-only | `noreferrer` | ✓ PRESERVED | 0 occurrences anywhere in the file |
| D-26 visible domain text | `@media[^{]*\{[^}]*\.back-link-label` | ✓ PRESERVED | 0 media queries collapse the label |
| D-29 no Cmd+K listener | `addEventListener\(['"]keydown` | ✓ PRESERVED | 0 listeners; `<script is:inline>` is documentation-only |
| D-30 no '/' shortcut | `key\s*===\s*['"]/['"]` | ✓ PRESERVED | 0 bindings |
| BRAND-04 token bridge | custom.css edits | ✓ PRESERVED | `git diff --name-only ee04f41~1 9e75b63` confirms custom.css NOT in changeset; `bash scripts/check-token-sync.sh` exits 0 |

### Regression Spot-Checks on Prior-Verified Truths

| Check | Result |
|---|---|
| `bash scripts/check-token-sync.sh` (BRAND-04) | ✓ "All 10 --primary-* stops in sync between marketing and docs." (exit 0) |
| `bash scripts/verify-build.sh` (all 17 prior + 2 new SHELL-05 source greps) | ✓ "All build-artifact assertions passed." (exit 0) |
| `npx astro check` (frontend type/schema) | ✓ "0 errors, 0 warnings, 0 hints" across 9 files |
| `node --check scripts/verify-shell-layout.mjs` | ✓ Parse OK |
| Playwright probe executable bit | ✓ `-rwxr-xr-x` |
| Sibling-repo commit hashes (ee04f41, eea9d04, 9e75b63) | ✓ All present on `main` |

**Conclusion:** Zero regressions across the 12 originally-verified must-haves. The single gap (SHELL-05-layout-collision) is closed with both static-source and runtime-bounding-rect evidence.

---

## Goal Achievement (Final, Post-Closure)

### Observable Truths

| #  | Truth                                                                                             | Status       | Evidence                                                                                                         |
|----|---------------------------------------------------------------------------------------------------|--------------|------------------------------------------------------------------------------------------------------------------|
| 1  | Docs site accent color uses hue ~250 blue (not Starlight purple) in both modes                   | ✓ VERIFIED   | Token values `--primary-700: oklch(0.46 0.16 250)` (light) / `--primary-400: oklch(0.70 0.16 250)` (dark) confirmed in custom.css. **Runtime confirmed via Playwright** (initial verification): no purple visible, AA contrast on links/text. |
| 2  | Ctrl+K / Cmd+K opens Pagefind search dialog; returns relevant results; code blocks de-ranked     | ✓ VERIFIED   | dist/pagefind/pagefind.js + pagefind-entry.json present. EC plugin registered. **Runtime confirmed via Playwright** (initial verification): Cmd+K opened dialog, "quickstart" returned 2 results, Escape closed dialog. |
| 3  | Every page shows "Last updated" timestamp, "Edit this page" GitHub link, and prev/next nav       | ✓ VERIFIED   | `lastUpdated: true` + `editLink.baseUrl: 'https://github.com/geolens-io/getgeolens.com/edit/main/docs/'` + `pagination: true` in astro.config.mjs. `<time datetime="2026-04-25T22:34:22.000Z">` in dist/guides/quickstart/index.html. |
| 4  | Marketing site header has "Docs" link; docs site header has "Back to getgeolens.com" link        | ✓ VERIFIED   | Nav.astro line 90: `href="https://docs.getgeolens.com"` rel="noopener". DocsHeader.astro: `href="https://getgeolens.com"` rel="noopener". **AND back-link no longer overlaps SiteTitle (SHELL-05 closed via Plan 224-05).** |
| 5  | CI token-drift check fails if custom.css primary hue diverges from marketing global.css          | ✓ VERIFIED   | check-token-sync.sh exits 0 against current files; wired in docs-ci.yml line 31. |

**Score:** 5/5 truths verified (3 originally green + 2 closed via human Playwright probe + 1 visual non-overlap proven via Playwright bounding-rect math).

### Required Artifacts

All 15 artifacts from initial verification remain ✓ VERIFIED. The 3 modified by Plan 224-05 (`DocsHeader.astro`, `verify-build.sh`, plus newly-created `verify-shell-layout.mjs`) re-verified:

| Artifact | Status | Details |
|----------|--------|---------|
| `docs/src/components/DocsHeader.astro` | ✓ VERIFIED | Now contains the SHELL-05 reservation rule. All locked decisions (D-25/D-26/D-29/D-30) negative-verified preserved. |
| `docs/scripts/verify-build.sh` | ✓ VERIFIED | Extended with 2 SHELL-05 source-side greps. Still ends with `All build-artifact assertions passed.` Exits 0. Includes BSD-grep `-e` workaround. |
| `docs/scripts/verify-shell-layout.mjs` | ✓ VERIFIED (NEW) | Playwright runtime probe; executable; parses cleanly; covers 4 (viewport × mode) combinations. Manual local gate, intentionally not wired to CI. |
| All 12 other Phase 224 artifacts | ✓ VERIFIED (no change) | See initial verification 2026-04-25T23:45:00Z. |

### Key Link Verification

All 9 key links from initial verification remain ✓ WIRED. Plan 224-05 added one new key link:

| From | To | Via | Status |
|------|----|-----|--------|
| `DocsHeader.astro <style>` | Starlight default Header's `.title-wrapper` | `:global(.header > .title-wrapper) { padding-inline-start: var(--back-link-reserved-space) }` | ✓ WIRED |
| `verify-build.sh` SHELL-05 reservation grep | `DocsHeader.astro` source | `grep -qF -e '--back-link-reserved-space'` | ✓ WIRED (and exits 0) |
| `verify-shell-layout.mjs` | Locally-running Astro preview | `page.goto('http://localhost:4321/')` + `getBoundingClientRect()` | ✓ WIRED (4/4 PASS at runtime) |

### Behavioral Spot-Checks (re-run during re-verification)

| Behavior | Command | Result | Status |
|---|---|---|---|
| Token-drift gate (BRAND-04) | `bash scripts/check-token-sync.sh` | "All 10 --primary-* stops in sync between marketing and docs." | ✓ PASS |
| All 19 build-artifact assertions (17 prior + 2 new) | `bash scripts/verify-build.sh` | "All build-artifact assertions passed." | ✓ PASS |
| Type/schema integrity | `npx astro check` | "0 errors, 0 warnings, 0 hints" | ✓ PASS |
| Playwright probe parses | `node --check scripts/verify-shell-layout.mjs` | exit 0 | ✓ PASS |
| Playwright probe runtime (4 combinations) | `node scripts/verify-shell-layout.mjs` (executor-run) | 4 PASS lines + "All shell-layout assertions passed." | ✓ PASS (verbatim in 224-05-SUMMARY.md §SHELL-05 Runtime Verification) |

### Requirements Coverage (Final)

All Phase 224 requirements satisfied:

| Requirement | Status | Notes |
|---|---|---|
| BRAND-01 OKLCH primary blue | ✓ SATISFIED | Token bridge in custom.css; verify-build.sh BRAND-01 passes |
| BRAND-02 Inter Variable font | ✓ SATISFIED | @fontsource-variable/inter ^5.2.8; bundled in dist/_astro/ |
| BRAND-03 Dark + light WCAG AA | ✓ SATISFIED | Playwright-confirmed: hue 250 in both modes, AAA contrast on body text |
| BRAND-04 token-drift CI gate | ✓ SATISFIED | check-token-sync.sh wired in docs-ci.yml |
| SHELL-01 sidebar groups | ✓ SATISFIED | All 4 group labels in dist/index.html |
| SHELL-02 prev/next + breadcrumbs + edit-link | ✓ SATISFIED | All confirmed in dist/ |
| SHELL-03 custom 404 | ✓ SATISFIED | dist/404.html passes all assertions |
| SHELL-04 lastUpdated + fetch-depth | ✓ SATISFIED | `<time datetime>` rendered; fetch-depth: 0 on both CI jobs |
| SHELL-05 cross-site nav | ✓ SATISFIED | Both directions present in built HTML; **AND visual non-overlap proven via Playwright bounding-rect math (gap closed by Plan 224-05)** |
| SEARCH-01 Pagefind built-in | ✓ SATISFIED | dist/pagefind/ present |
| SEARCH-02 code de-prioritized | ✓ SATISFIED | EC plugin registered with `data-pagefind-weight: '0.1'` |
| SEARCH-03 keyboard shortcut | ✓ SATISFIED | Playwright-confirmed: Cmd+K opens, Esc closes |
| SEO-04 llms.txt | ✓ SATISFIED | All 4 canonical /guides/ URLs present |

### Anti-Patterns Found

No new anti-patterns introduced by Plan 224-05. The 4 "coming soon" placeholder pages from initial verification remain ℹ Info (intentional per D-35; content ships in Phases 225-227).

---

## Final Status

**Status:** `passed`
**Score:** 13/13 must-haves verified (12 prior + 1 SHELL-05 closed)
**Human verification:** Both prior items already confirmed via Playwright probe in initial verification. No new human gates required.
**Regressions from gap closure:** 0
**Phase goal achieved:** YES — all 5 ROADMAP success criteria for Phase 224 are now satisfied.

The docs site looks and feels like a GeoLens property:
- Primary blue accent at hue 250 in both modes (BRAND-01/02/03/04 all green)
- Inter Variable font self-hosted, no Google CDN
- Dark/light parity with marketing site
- All shell affordances wired and confirmed in dist/ AND visually correct at runtime (sidebar, prev/next, breadcrumbs, 404, last-updated, edit links, search, cross-site nav with non-overlapping back-link)

Phase 224 is ready for sign-off. Downstream content phases (225-227) are unblocked.

---

_Initial verification: 2026-04-25T23:45:00Z_
_Re-verified post-closure: 2026-04-26T00:30:00Z_
_Verifier: Claude (gsd-verifier)_
