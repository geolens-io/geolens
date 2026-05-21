---
quick_id: 260408-lnq
phase: quick
plan: "01"
type: doc-only
tags:
  - demo
  - content-strategy
  - docs
dependency_graph:
  requires: []
  provides:
    - "260408-lnq-PROPOSAL.md: demo environment themed content strategy"
  affects: []
tech_stack:
  added: []
  patterns: []
key_files:
  created:
    - .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md
  modified: []
decisions:
  - "Three themed collections for the demo: Planet Earth — Physical Systems, Global Development & People, Borders Boundaries & Contested Space"
  - "ACLED rejected (three-EULA-conflict — governmental, commercial, AI training); UCDP GED v25.1 CC-BY is the substitution"
  - "Automation posture: automate data ingest + collection assignment; hand-curate maps as JSON fixtures exported from the UI"
  - "A7 (table→polygon join in map builder) is the critical unverified dependency — resolve before committing Theme 2 choropleth map scope"
  - "Six maps on the ship list (A7-independent); four additional maps deferred until A7 resolves"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-08"
  tasks_completed: 2
  files_created: 1
---

# Quick Task 260408-lnq: Demo Environment Data & Maps Brainstorm — Summary

**One-liner:** Three-theme demo strategy with 6 signature maps, fixture-based automation posture, explicit ACLED→UCDP substitution, and A7 as the gating dependency for choropleth maps.

## What Was Done

Distilled the 430-line RESEARCH.md into a 363-line executive-readable PROPOSAL.md covering: three recommended themes with dataset tables, a 10-map decision table (6 ship / 4 A7-deferred), geopolitics safety analysis with ACLED rejection rationale, a consolidated data sources catalog, the automation recommendation (fixture-based maps), 8 open questions with A7 as the critical gate, and a concrete 6-plan implementation phase sketch.

## Output

**PROPOSAL.md** at `.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md`

All 10 required sections present in order: TL;DR, Current State, Recommended Themes, Datasets per Theme, Signature Maps, Geopolitics Safety Notes, Data Sources Catalog, Automation Recommendation, Open Questions & Dependencies, Suggested Next Steps.

## Decisions Made

1. **Three themes selected:** Planet Earth — Physical Systems (raster/VRT story), Global Development & People (table records + semantic search), Borders Boundaries & Contested Space (geopolitics safely). Backup themes (Climate & Disaster, Energy & Infrastructure, Culture & History) documented but rejected for weaker record-type coverage.

2. **ACLED rejected, UCDP substituted:** ACLED EULA conflicts with governmental use, commercial use, and AI training — all three apply simultaneously to GeoLens. UCDP GED v25.1 (CC-BY 4.0, no AI restriction) is the drop-in replacement for conflict event data.

3. **Automation posture: fixture-based maps.** Automate all data ingest and collection assignment using primitives from `seed-natural-earth.py`. Hand-curate signature maps once in the UI, export via `GET /api/maps/{id}`, commit as JSON fixtures. Seeder resolves dataset UUIDs by source filename stem at runtime.

4. **Ship list: 6 maps (A7-independent).** Maps 1.1, 1.2, 2.1, 3.1, 3.2, 3.3 ship regardless of A7. Maps 2.2, 2.3, 3.4 are conditional on A7 resolution. Map 1.3 is "add if time permits."

5. **A7 is the single gating dependency.** Resolve whether the map builder can join a `record_type=table` CSV to an ADM0 polygon on ISO3 before committing Theme 2 choropleth scope.

## Deviations from Plan

None — plan executed exactly as written. Both tasks (draft first half, complete second half) were merged into a single write operation for efficiency since the document was designed as a unit.

## Self-Check

- [x] PROPOSAL.md exists at the target path
- [x] All 10 required section headers present (10 H2 sections confirmed)
- [x] TL;DR has exactly 5 decisive bullets covering all required topics
- [x] Three dataset tables with source, format, size, record_type, license, rationale — no TBD
- [x] Signature Maps table: 6 ship + 4 deferred with A7 clearly marked on Maps 2.2 and 3.4
- [x] ACLED rejection with three-EULA-conflict rationale present in Safety Notes
- [x] UCDP substitution documented with CC-BY 4.0 verification
- [x] Natural Earth disputed-boundaries policy cited with URL
- [x] Language discipline rule for layer descriptions reproduced verbatim
- [x] Data Sources Catalog consolidates every source with license + verification status
- [x] Automation recommendation is decisive (automate data, fixture maps, no automated share tokens)
- [x] Open Questions numbered list with A7 as #1 and "CRITICAL" flag
- [x] Suggested Next Steps sketches 6-plan phase with sequencing notes
- [x] File references both RESEARCH.md and CONTEXT.md at the top
- [x] No "TASK 2 CONTINUES BELOW" marker in final file
- [x] 363 lines — within 300-700 target range; meaningful distillation, not duplication
- [x] No code, scripts, or fixtures touched

## Self-Check: PASSED
