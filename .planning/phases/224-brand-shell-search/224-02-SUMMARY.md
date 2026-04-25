---
phase: 224
plan: "02"
subsystem: docs-ci
tags: [brand, shell, search, ci, scripts]
dependency_graph:
  requires: []
  provides: [BRAND-04-gate, SHELL-04-prerequisite, phase-224-build-assertions]
  affects: [getgeolens.com/docs/scripts/check-token-sync.sh, getgeolens.com/docs/scripts/verify-build.sh, getgeolens.com/.github/workflows/docs-ci.yml]
tech_stack:
  added: []
  patterns: [bash-shebang-set-euo-pipefail, grep-or-exit-idiom, yaml-github-actions]
key_files:
  created:
    - getgeolens.com/docs/scripts/check-token-sync.sh
  modified:
    - getgeolens.com/docs/scripts/verify-build.sh
    - getgeolens.com/.github/workflows/docs-ci.yml
decisions:
  - "[D-06] check-token-sync.sh asserts OKLCH stops 50–900 (not 950) between marketing global.css and docs custom.css using tr -s ' ' normalization"
  - "[D-07/D-34] token-sync step inserted between npm ci and wrangler guard in check-and-build job — fails fast before astro check"
  - "[Pivot #2] fetch-depth: 0 added to BOTH jobs' checkout steps for SHELL-04 lastUpdated per-file timestamp resolution"
metrics:
  duration_minutes: 2
  completed_date: "2026-04-25"
  tasks_completed: 3
  files_changed: 3
---

# Phase 224 Plan 02: CI Gating Layer Summary

BRAND-04 token-drift enforcement script, extended Phase 224 build-artifact gates in verify-build.sh, and docs-ci.yml wired with full git history checkout and token-sync step.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author scripts/check-token-sync.sh (BRAND-04) | 771acf0 | getgeolens.com/docs/scripts/check-token-sync.sh |
| 2 | Extend scripts/verify-build.sh with Phase 224 assertions | a39cbea | getgeolens.com/docs/scripts/verify-build.sh |
| 3 | Wire check-token-sync into docs-ci.yml + add fetch-depth: 0 | b46564f | getgeolens.com/.github/workflows/docs-ci.yml |

## What Was Built

**check-token-sync.sh (new, executable):** Reads `getgeolens.com/src/styles/global.css` and `getgeolens.com/docs/src/styles/custom.css`, greps OKLCH triplets for each of the 10 primary stops (50–900), normalizes whitespace via `tr -s ' '`, and fails with a diff if any stop drifts. Stop 950 intentionally excluded (docs-only extrapolated per D-02). Header documents BRAND-04 enforcement and references Phase 227 for prose-side maintenance convention (D-08).

**verify-build.sh (extended):** 11 new Phase 224 assertion blocks inserted before the final `echo "All build-artifact assertions passed."`. All 6 Phase 223 assertions preserved unchanged. New blocks cover:
- BRAND-01: OKLCH hue 250 in built CSS
- BRAND-02: no Google Fonts CDN refs; Inter Variable bundled in dist/_astro/
- SHELL-01: four sidebar group labels in dist/index.html
- SHELL-02: editLink GitHub URL; breadcrumb nav on /guides/quickstart/
- SHELL-03: 404.html existence, heading, footer link, four category card hrefs
- SHELL-04: `<time datetime="20XX">` on /guides/quickstart/ (depends on fetch-depth: 0)
- SHELL-05: docs back-link href in dist/index.html
- SEARCH-01: pagefind.js + pagefind-entry.json emitted
- SEARCH-02 smoke: EC plugin file + postprocessRenderedBlock hook + data-pagefind-weight property
- SEO-04: dist/llms.txt with four /guides/ URLs

**docs-ci.yml (patched):**
- Both `actions/checkout@v4` steps upgraded to `fetch-depth: 0` (Pivot #2 — SHELL-04 lastUpdated)
- New "Check token sync (BRAND-04 drift detection)" step inserted in check-and-build between `npm ci` and the wrangler guard, matching D-34 ordering
- Deploy job does not re-run token-sync (already gated via `needs: check-and-build`)

## Deviations from Plan

None — plan executed exactly as written.

## Notes on CI Behavior

The token-sync step will fail in CI until Plan 01 has shipped the expanded custom.css (this is the intended gate). The verify-build.sh Phase 224 assertions will fail until Plans 03 and 04 ship the placeholder index.mdx files, llms.txt, EC plugin, shell components, and astro.config wiring. End-to-end verification of this plan happens at phase-level after Wave 2 completes.

## Known Stubs

None — this plan ships scripts and CI config only, no UI or data stubs.

## Self-Check: PASSED

- getgeolens.com/docs/scripts/check-token-sync.sh: EXISTS (771acf0)
- getgeolens.com/docs/scripts/verify-build.sh: MODIFIED (a39cbea)
- getgeolens.com/.github/workflows/docs-ci.yml: MODIFIED (b46564f)
- All commits verified in getgeolens.com repo git log
