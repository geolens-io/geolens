---
phase: 260329-bn7
plan: "01"
subsystem: frontend/design-tokens
tags: [design-guide, css-tokens, info-color, token-hierarchy]
dependency_graph:
  requires: []
  provides: [AUDIT-01, AUDIT-02, AUDIT-03]
  affects: [frontend/src/index.css, docs/DESIGN-GUIDE.md]
tech_stack:
  added: []
  patterns: [OKLCH teal/cyan hue 195 for info semantic color]
key_files:
  created: []
  modified:
    - frontend/src/index.css
    - docs/DESIGN-GUIDE.md
decisions:
  - "--info hue shifted to 195 (teal/cyan), matching --viz-5, to differentiate info from primary (hue 250)"
  - "Token Usage Hierarchy added to DESIGN-GUIDE Section 2 — semantic tokens first, surface tokens second, primary scale last"
  - "Minimalism Rule one-liner added to Section 1 as a conservative default for color decisions"
metrics:
  duration: 5min
  completed: "2026-03-29"
  tasks_completed: 2
  files_modified: 2
---

# Phase 260329-bn7 Plan 01: Design Guide Audit Findings Summary

**One-liner:** Info status color shifted to teal/cyan hue 195 (from primary-blue 250) with token hierarchy and minimalism rule added to DESIGN-GUIDE.md.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Shift --info token hue from primary-blue (250) to teal/cyan (195) | 44ac57cb | frontend/src/index.css |
| 2 | Add Token Usage Hierarchy, Minimalism Rule, update info values in DESIGN-GUIDE.md | 6d36a970 | docs/DESIGN-GUIDE.md |

## Changes Made

### Task 1 — frontend/src/index.css

Updated 3 CSS custom property values (light-mode info-foreground was already white, no hue needed):

- `:root` `--info`: `oklch(0.55 0.18 250)` → `oklch(0.55 0.15 195)`
- `.dark` `--info`: `oklch(0.72 0.17 250)` → `oklch(0.72 0.14 195)`
- `.dark` `--info-foreground`: `oklch(0.20 0.05 250)` → `oklch(0.20 0.05 195)`

Chroma reduced slightly (0.18→0.15 light, 0.17→0.14 dark) to stay in sRGB gamut for teal. The hue 195 aligns with `--viz-5` (the existing teal slot in the data viz palette).

### Task 2 — docs/DESIGN-GUIDE.md

Three edits:

**Edit A (Section 1):** Added Minimalism Rule paragraph after the Key Principles bullet list:
> "Default rule: When unsure which tokens or colors to use, stick with `background` + `card` + `primary`. Do not introduce new tokens or colors without a clear reason."

**Edit B (Section 2):** Added "Token Usage Hierarchy" subsection before "Primary Scale":
- Level 1: Semantic tokens (90% of use cases)
- Level 2: Surface tokens (elevation stacking)
- Level 3: Primary scale tokens (rare edge cases)
- Hard rule against using scale tokens for UI semantics

**Edit C (Status Colors table):** Updated `--info` and `--info-foreground` rows to reflect the new hue 195 values, keeping CSS and guide in sync.

Final line count: 711 (min_lines requirement: 700 — satisfied).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- frontend/src/index.css exists with hue 195 info tokens: confirmed (grep shows 3 matches)
- docs/DESIGN-GUIDE.md exists with Token Usage Hierarchy section: confirmed
- docs/DESIGN-GUIDE.md contains Minimalism Rule: confirmed
- docs/DESIGN-GUIDE.md contains oklch(0.55 0.15 195): confirmed
- Commit 44ac57cb exists: confirmed
- Commit 6d36a970 exists: confirmed
