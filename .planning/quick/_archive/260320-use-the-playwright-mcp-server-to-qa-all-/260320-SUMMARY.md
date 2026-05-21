---
phase: 260320
plan: 01
subsystem: ux-qa
tags: [playwright, qa, ui-ux, detail-pages]

requires:
  - phase: v12.1-detail-pages
    provides: routable vector, raster, VRT, and collection detail surfaces
provides:
  - Comprehensive findings doc for record-detail UI/UX gaps
  - Screenshot evidence for all four detail variants on desktop and mobile
  - Concrete QA target list selected from the live Search UI
affects: [detail-pages, collection-detail, milestone-planning]

tech-stack:
  added: []
  patterns: [playwright-mcp browser audit, evidence-backed findings]

key-files:
  created:
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/qa-targets.json
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/FINDINGS.md
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vector-desktop.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vector-mobile.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/raster-desktop.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/raster-mobile.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vrt-desktop.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vrt-mobile.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/collection-desktop.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/collection-mobile.png
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/logs/console-vrt.log
  modified:
    - .planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/260320-PLAN.md

key-decisions:
  - "Use live Search UI filters to choose one representative target per record type instead of hardcoding IDs."
  - "Treat collection detail as a separate `/collections/:id` surface rather than forcing it through `/datasets/:id`."

requirements-completed: [QA-TARGETS, QA-FINDINGS, QA-EVIDENCE]

duration: 15min
completed: 2026-03-19
---

# Phase 260320: Record Detail QA Summary

Used the Playwright MCP browser against the running local stack to audit the four record-detail surfaces: vector, raster, VRT, and collection. The task produced a milestone-ready findings list, a concrete target manifest, desktop/mobile screenshots for each surface, and console evidence for the loudest failure mode.

## Accomplishments

- Selected one real target per surface from the live Search UI and recorded them in `qa-targets.json`
- Captured desktop and mobile screenshots for vector, raster, VRT, and collection detail pages
- Wrote `FINDINGS.md` with prioritized issues, evidence links, suggested fixes, easy wins, and milestone workstreams
- Corrected the plan during the checker loop so collection detail was audited on its actual `/collections/:id` route

## Main Findings

1. `P0`: VRT detail preview fails with repeated tile `500`s and leaves the hero in a broken state
2. `P1`: Mobile dataset-detail headers do not collapse cleanly; titles and inline actions compete for space
3. `P2`: Raster overview hero underuses available space and reads as mostly empty whitespace
4. `P2`: Collection detail uses a different shell from the dataset variants, which weakens consistency and wayfinding

## Artifacts

- `qa-targets.json` maps the audited vector, raster, VRT, and collection records
- `FINDINGS.md` contains the prioritized findings list and milestone grouping
- `evidence/` contains 8 screenshots, one desktop and one mobile capture for each detail surface
- `logs/console-vrt.log` captures the repeated VRT tile failures observed during QA

## Deviations from Plan

None in the final artifact set. The only plan correction was made before execution: collection detail was audited on `/collections/:id`, matching the real route configuration.

## Issues Encountered

- The Playwright MCP browser initially collided with a stale local `mcp-chrome` session; the session had to be cleared before the audit could run.
- Console capture for the vector pass was noisy from prior session state and is not used as primary evidence.

## Next Phase Readiness

- The findings doc is ready to seed a milestone focused on preview resilience, responsive detail headers, and detail-shell consistency.
- The easy-win list can be split out for a smaller follow-up if the user wants quick polish before the larger milestone.

---
*Phase: 260320*
*Completed: 2026-03-19*
