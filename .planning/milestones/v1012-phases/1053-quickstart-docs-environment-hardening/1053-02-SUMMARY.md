---
phase: 1053-quickstart-docs-environment-hardening
plan: 02
subsystem: docs
tags: [quickstart, docs, cross-repo, seed-natural-earth, seed-ago-data, docker-compose]

requires:
  - phase: none
    provides: n/a

provides:
  - "Quickstart page documents both API seeders as canonical post-login data path"
  - "Demo overlay framed as an optional alternative, not the primary path"
  - "Anchor #create-your-first-api-key established for Plan 03 forward-reference"

affects: [1053-quickstart-docs-environment-hardening]

tech-stack:
  added: []
  patterns:
    - "Cross-repo doc edit committed in sibling repo (~/Code/getgeolens.com) referencing plan REQ-IDs"

key-files:
  created: []
  modified:
    - "~/Code/getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx"

key-decisions:
  - "EW-01 option (b): keep docker-compose.demo.yml as-is, relabel in docs (no compose surgery)"
  - "Merged 'What you should see' H2 into '## 3. First login' prose (editorial — cleaner flow)"
  - "Service topology H2 kept in place between Seed section and Alternative section"

patterns-established: []

requirements-completed:
  - DOC-01
  - EW-01

duration: 5min
completed: 2026-05-19
---

# Phase 1053 Plan 02: Quickstart Seed Sample Data + Demo Overlay Relabel Summary

**API-seeder path (seed-natural-earth.py + seed-ago-data.py) documented as canonical post-login step in quickstart; demo overlay demoted to an 'Alternative' section with commit d50b9ec on getgeolens.com/main**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-19T21:05:00Z
- **Completed:** 2026-05-19T21:10:04Z
- **Tasks:** 3
- **Files modified:** 1 (sibling repo)

## Accomplishments

- Added `## 4. Seed sample data` section to quickstart documenting both `seed-natural-earth.py` (offline, ~109 datasets, 3-5 min) and `seed-ago-data.py` (live AGO connector, NJ Highlands default)
- Merged the "What you should see" H2 into "## 3. First login" prose — removed the floating heading that previously created an awkward detour between login and the demo section
- Demoted "Try the themed demo" to `## Alternative: bundled bake-time demo` positioned AFTER the new Seed section, preserving all demo content (signature stories, reset commands, attribution) with explicit "secondary path" framing
- Anchor `#create-your-first-api-key` placed in Seed AGO subsection prose for Plan 03 (DOC-02) to resolve

## New Section Structure (heading-level outline)

```
## 1. Clone and run the installer
## 2. Verify services
## 3. First login
## 4. Seed sample data
    ### Seed Natural Earth (offline)
    ### Seed live ArcGIS Online data
## Service topology
## Alternative: bundled bake-time demo
## Next steps
```

## Task Commits

All three tasks landed in a single cross-repo commit (Tasks 1 + 2 were file edits; Task 3 was the commit):

1. **Task 1: Replace demo section with Seed sample data** - `d50b9ec` (docs)
2. **Task 2: Add Alternative: bundled bake-time demo subsection** - `d50b9ec` (docs)
3. **Task 3: Commit cross-repo change** - `d50b9ec` (docs — sibling repo `~/Code/getgeolens.com`)

**Sibling-repo commit:** `d50b9eca3a260701bcea7d2e59db85114d8edaf9` on `~/Code/getgeolens.com/main` (NOT pushed)

## Files Created/Modified

- `~/Code/getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx` — Added "## 4. Seed sample data" canonical section + "## Alternative: bundled bake-time demo" demotion section; merged "What you should see" into section 3 prose

## Decisions Made

- EW-01 option (b) honored: `docker-compose.demo.yml` kept as-is; quickstart rewrite makes single-compose canonical
- "What you should see" H2 merged into "## 3. First login" paragraph — the standalone heading had no numbering and read as an orphan; merged prose is cleaner
- Full demo content (signature stories bullet list, reset commands, attribution) preserved inline — no linked guide exists (`find` returned empty); content trimmed is not needed as the bulleted list is appropriate length

## Deviations from Plan

None - plan executed exactly as written. The editorial merge of "What you should see" into section 3 prose is within the plan's explicit guidance: "Use editorial judgment — the priority is that the seeder path is the most prominent post-login step."

## Issues Encountered

None.

## User Setup Required

None - docs-only change.

## Next Phase Readiness

- Plan 03 (DOC-02, DOC-03, DOC-05) can now extend the "## 4. Seed sample data" section by adding the "### Create your first API key" subsection that resolves the `#create-your-first-api-key` anchor placed in this plan
- This repo (`~/Code/geolens`) has ZERO tracked-file changes — git status is clean

## Self-Check: PASSED

- Sibling-repo commit exists: `d50b9eca3a260701bcea7d2e59db85114d8edaf9`
- Commit subject references DOC-01 + EW-01: PASS
- Only file changed: `docs/src/content/docs/guides/quickstart/index.mdx`: PASS
- `grep -c "seed-natural-earth.py"` → 2: PASS
- `grep -c "seed-ago-data.py"` → 3: PASS
- "Seed sample data" section present: PASS
- "Alternative" heading present: PASS
- `docker-compose.demo.yml` still referenced (preserved): PASS
- This repo git status: clean (no changes)

**DOC-01 + EW-01 closed via cross-repo commit `d50b9ec`.**

---
*Phase: 1053-quickstart-docs-environment-hardening*
*Completed: 2026-05-19*
