---
phase: 224-brand-shell-search
plan: 05
subsystem: ui
tags: [starlight, astro, shell, layout, css, playwright, gap-closure]

# Dependency graph
requires:
  - phase: 224-brand-shell-search
    provides: "Plan 224-04 wired DocsHeader.astro as the components.Header override with absolute-positioned back-link; this plan closes the SHELL-05 layout collision discovered in re-verification"
provides:
  - "DocsHeader.astro reserves horizontal space inside Starlight's <Default /> .title-wrapper via padding-inline-start so the back-link no longer overlaps the SiteTitle"
  - "verify-shell-layout.mjs Playwright runtime probe asserting non-overlap at 1280×800 and 360×800 in both light and dark modes"
  - "verify-build.sh source-side grep guard preventing accidental deletion of the SHELL-05 reservation rule"
affects: [phase-224-verification-rerun, phase-225-api-content, phase-226-quickstart-content, phase-227-user-admin-content]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Source-side build-time greps for component-internal CSS invariants (Vite hashes/minifies output unpredictably; source-side grep is stable)"
    - "Runtime layout probes via Playwright Chromium against `npm run preview` for non-overlap assertions that static analysis cannot prove"
    - "CSS variable + :global() selector pattern for layering padding overrides onto a third-party component's wrapper element from inside an Astro <style> block"

key-files:
  created:
    - "getgeolens.com/docs/scripts/verify-shell-layout.mjs"
  modified:
    - "getgeolens.com/docs/src/components/DocsHeader.astro"
    - "getgeolens.com/docs/scripts/verify-build.sh"

key-decisions:
  - "Sized --back-link-reserved-space at 10rem (160px) — clears back-link.right (~146.8px) with ~13.2px headroom rather than back-link.width (122.8px), which would have re-introduced ~2.8px overlap"
  - "Source-side grep in verify-build.sh (not dist-side) — Vite minification is unstable across upgrades; same lesson as Plan 04 BRAND-01 fix"
  - "Playwright probe is runtime-only, not wired into docs-ci.yml — preview-server lifecycle complicates CI; manual local gate is sufficient for a layout invariant"

patterns-established:
  - "Layered padding override: rather than fight Starlight's `padding: 0.25rem; margin: -0.25rem` shorthand on .title-wrapper, use the longhand `padding-inline-start` from a :global() selector — the longhand wins on cascade without disturbing the other three sides"
  - "Bounding-rect non-overlap assertion: rectsIntersect(a, b) with EPSILON=0.5 to absorb subpixel font-rendering variation between modes/viewports"

requirements-completed: [SHELL-05]

# Metrics
duration: ~12min
completed: 2026-04-25
---

# Phase 224 Plan 05: SHELL-05 Layout Collision Fix Summary

**Reserved 10rem of left padding inside Starlight's wrapped header `.title-wrapper` so the absolutely-positioned `← getgeolens.com` back-link no longer overlaps the `GeoLens Docs` site-title — verified non-overlap at runtime across desktop/mobile and light/dark via Playwright Chromium.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-25T23:20:00Z (approx)
- **Completed:** 2026-04-25T23:32:56Z
- **Tasks:** 3
- **Files modified:** 3 (1 modified, 1 created, 1 modified)

## Accomplishments

- DocsHeader.astro now declares `:root { --back-link-reserved-space: 10rem }` and applies it via `:global(.header > .title-wrapper) { padding-inline-start: var(--back-link-reserved-space) }`, eliminating the SHELL-05 overlap discovered in re-verification
- Created `docs/scripts/verify-shell-layout.mjs` — a Playwright runtime probe that drives Chromium against `npm run preview` and asserts non-overlap of the back-link and site-title bounding rects across 4 (viewport × mode) combinations
- Extended `docs/scripts/verify-build.sh` with two source-side grep assertions guarding the SHELL-05 reservation rule against accidental deletion

## SHELL-05 Runtime Verification

The mandatory runtime probe `node scripts/verify-shell-layout.mjs` was executed against `npm run preview` and produced the following PASS lines verbatim:

```
PASS [desktop 1280x800 light]: back-link.right=146.8 ; site-title.left=180.0
PASS [desktop 1280x800 dark]: back-link.right=146.8 ; site-title.left=180.0
PASS [mobile 360x800 light]: back-link.right=138.8 ; site-title.left=172.0
PASS [mobile 360x800 dark]: back-link.right=138.8 ; site-title.left=172.0
All shell-layout assertions passed.
```

**Bounding-rect interpretation:**

| Viewport × Mode | back-link.right (px) | site-title.left (px) | Gap (px) | Overlap? |
|-----------------|----------------------|----------------------|----------|----------|
| desktop 1280×800 light | 146.8 | 180.0 | 33.2 | NO |
| desktop 1280×800 dark  | 146.8 | 180.0 | 33.2 | NO |
| mobile  360×800  light | 138.8 | 172.0 | 33.2 | NO |
| mobile  360×800  dark  | 138.8 | 172.0 | 33.2 | NO |

The 33.2px gap exceeds the 8px target gap by ~4×, providing ample headroom for future copy changes ("getgeolens.com" → e.g., "← Back to getgeolens.com") without regressing.

The mobile back-link.right of 138.8 (vs desktop 146.8) reflects an 8px shrink in the rendered label width at 360px viewport — well within the 10rem reservation.

The pre-fix failing baseline from `224-VERIFICATION.md` was: `back-link {x:24, y:0, w:122.8, h:63}` overlapping `site-title {x:24, y:10.5, w:167.6, h:42}` (both starting at x=24). After fix: site-title starts at x=180 (desktop) / x=172 (mobile), confirming the padding-inline-start reservation flows correctly through Starlight's grid.

## Task Commits

Each task was committed atomically into `/Users/ishiland/Code/getgeolens.com` (sibling repo):

1. **Task 1: Patch DocsHeader.astro** — `ee04f41` (fix)
2. **Task 2: Author Playwright runtime probe** — `eea9d04` (test)
3. **Task 3: Add SHELL-05 source greps to verify-build.sh** — `9e75b63` (chore)

## Files Created/Modified

**Created:**
- `getgeolens.com/docs/scripts/verify-shell-layout.mjs` — Playwright runtime non-overlap probe (130 lines)

**Modified:**
- `getgeolens.com/docs/src/components/DocsHeader.astro` — Added :root CSS var + :global() padding-inline-start rule on .title-wrapper, with detailed sizing-math rationale comment block. Frontmatter, anchor markup, and `<script is:inline>` block preserved byte-identical.
- `getgeolens.com/docs/scripts/verify-build.sh` — Added two source-side grep assertions guarding the SHELL-05 reservation. All 17 prior Phase-223/224 assertions preserved unchanged.

## Decisions Made

- **10rem (not 9rem) for the reservation:** 9rem (144px) would leave SiteTitle.left=144 colliding with back-link.right=146.8 by 2.8px. 10rem (160px) provides 13.2px headroom over the rendered back-link.right.
- **Source-side grep in verify-build.sh:** Vite/cssnano minification of CSS variable names and selector whitespace is unstable across upgrades. The same lesson applied in Plan 04 (BRAND-01 OKLCH minification handling).
- **Runtime probe is local-only, not in CI:** Wiring `npm run preview` into docs-ci.yml requires server lifecycle management. The probe is a developer-runnable gate; the build-time grep is the CI guard against accidental deletion.

## Decisions Preserved (Negative Verification)

All locked Phase 224 decisions were verified preserved via negative grep on the post-fix DocsHeader.astro source:

- **D-25 (absolute positioning strategy):** No actual `display: contents` rule exists; no `grid-column` rule exists. (Both strings appear only in rationale comments documenting what was intentionally avoided — see Deviations §1.)
- **D-26 (rel="noopener" only):** `noreferrer` not present anywhere in the file; `.back-link-label` is not collapsed by any media query.
- **D-29 (no duplicate Cmd+K listener):** No `addEventListener('keydown', …)` exists in the file.
- **D-30 (no '/' shortcut):** No `key === '/'` binding exists.
- **BRAND-04 (token-sync drift gate):** `bash scripts/check-token-sync.sh` exits 0 — custom.css was not touched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's Task 1 verify-gate regex was over-broad**

- **Found during:** Task 1 verification step
- **Issue:** The plan's verify command included `! grep -qE 'display:\s*contents'` and `! grep -qE 'grid-column'` as negative-grep gates. However, both Task 1's preserved-verbatim frontmatter comments (lines 7-8 of the file, pre-existing from Plan 04) AND the new rationale comment block (which the plan's action text mandates verbatim) explicitly contain the strings `display:contents` and `grid-column` to document what was intentionally NOT done. The over-broad regex therefore reported FAIL even though the file faithfully implements the plan and contains zero actual `display: contents` or `grid-column` CSS declarations.
- **Fix:** Re-ran the negative gates with comment-stripping (`awk` removes `/* ... */` blocks and `sed` removes `//` lines), then re-checked. With comments stripped, no actual CSS rule for either pattern exists. Documented this discrepancy here rather than altering the file (changing the rationale comments would lose the intent of documenting the prohibited patterns).
- **Files modified:** None (verification methodology refined; file content is correct per plan).
- **Verification:** Comment-stripped grep emits PASS for both `display:\s*contents` and `grid-column`. The plan's `:global()` selector and `--back-link-reserved-space` rules are present and correct.
- **Committed in:** N/A (verification-only; no code change needed)

**2. [Rule 1 - Bug] Plan's Task 3 grep snippet incompatible with BSD grep**

- **Found during:** Task 3 Step 2 — initial run of `bash scripts/verify-build.sh` after patch
- **Issue:** The plan's verbatim grep snippet was `grep -qF '--back-link-reserved-space' src/components/DocsHeader.astro`. BSD grep (macOS default) parses the `--back-link...` argument as an option flag and errors out with `unrecognized option`. GNU grep would have accepted it because the file argument follows.
- **Fix:** Changed both new grep lines to use `grep -qF -e '--back-link-reserved-space'` and `grep -qF -e ':global(.header > .title-wrapper)'`, where `-e` explicitly marks the next arg as a literal pattern. (Equivalent fix: `grep -qF -- '--back-link...'`.) Added a one-line comment in the script explaining the BSD-grep nuance.
- **Files modified:** `getgeolens.com/docs/scripts/verify-build.sh`
- **Verification:** Re-ran `bash scripts/verify-build.sh` after patch — exits 0; both new SHELL-05 source-side asserts emit no output (success) and `All build-artifact assertions passed.` is printed at the end.
- **Committed in:** `9e75b63` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs in the plan's verify-gate text, not in the implementation)
**Impact on plan:** Zero scope creep. Both deviations were verification-tooling bugs (regex over-broadness; BSD-grep option parsing). The implementation matches the plan's prescribed CSS verbatim.

## Issues Encountered

- The Astro build emitted a `[WARN] [build] Could not render /404 from route /404 as it conflicts with higher priority route /404.` This warning is pre-existing (present before this plan) and stems from the Plan 03 dual-source 404 setup (Astro page at `src/pages/404.astro` plus Starlight content collection). It does not affect this plan's scope and `dist/404.html` is generated correctly. Logged for future cleanup, not in this plan's surface.

## User Setup Required

None — no external service configuration, no env vars, no dashboard changes. Pure CSS layout fix on a static docs site.

## Next Phase Readiness

- **VERIFICATION.md re-verification:** Re-running `/gsd-verify-work` against Phase 224 should now resolve the `SHELL-05-layout-collision` gap and update `gaps_found` → `complete`. The 4 PASS lines above are sufficient evidence.
- **Phase 224 sign-off:** With SHELL-05 closed, the only remaining `human_needed` items in `224-VERIFICATION.md` (BRAND-03 visual contrast and SEARCH-03 keyboard shortcut) were already confirmed passing via Playwright probe in the `re_verified` pass — phase is complete.
- **No blockers** for downstream content phases (225-227).

## Self-Check: PASSED

Verified:
- `/Users/ishiland/Code/getgeolens.com/docs/src/components/DocsHeader.astro` — exists, contains `--back-link-reserved-space: 10rem`, contains `:global(.header > .title-wrapper)`, preserves `rel="noopener"` and `position: absolute`.
- `/Users/ishiland/Code/getgeolens.com/docs/scripts/verify-shell-layout.mjs` — exists, executable, parses cleanly (`node --check`), contains all required selectors.
- `/Users/ishiland/Code/getgeolens.com/docs/scripts/verify-build.sh` — exists, contains `SHELL-05 layout reservation`, exits 0 against the locally-built `dist/`.
- Commits `ee04f41`, `eea9d04`, `9e75b63` — all present in `getgeolens.com` git log on `main`.

---
*Phase: 224-brand-shell-search*
*Plan: 05*
*Completed: 2026-04-25*
