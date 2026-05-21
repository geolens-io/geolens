---
quick_id: 260408-aa5
phase: 260408-aa5
plan: "01"
subsystem: planning
tags: [3d, terrain, fill-extrusion, postgis, maplibre, design-doc, feasibility-spike]
dependency_graph:
  requires: []
  provides: [3d-feasibility-design-doc]
  affects: []
tech_stack:
  added: []
  patterns: []
key_files:
  created:
    - .planning/quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md
  modified: []
decisions:
  - "Terrain is essentially free: Titiler 2.0.0 ships built-in terrainrgb — no new service or pre-processing needed"
  - "Building extrusion requires zero backend changes — height attribute already travels through ST_AsMVT as a feature property"
  - "ST_AsMVT strips Z (MVT 2.1 spec is 2D-only) — PostGIS 3D geometry delivery requires a non-MVT path"
  - "Recommended sequencing: Phase A (terrain+extrusions) first, Phase B (PostGIS detection), Phase C (GeoJSON-Z) only if demand justifies"
  - "MapLibre declarative terrain and sky props work in v8; fill-extrusion layers use imperative addSource/addLayer"
metrics:
  duration: "~15 minutes"
  completed: 2026-04-08
  tasks_completed: 1
  files_created: 1
---

# Phase 260408-aa5 Plan 01: 3D Data & Maps Support Feasibility Spike Summary

**One-liner:** 3D feasibility spike documenting terrain-via-Titiler terrainrgb (free), fill-extrusion on existing MVT pipeline (zero backend), and MVT 2D-only wall blocking native PostGIS 3D geometry delivery.

## What Was Done

Task 1 produced a single 398-line design document covering all three 3D pillars for GeoLens:

- **Pillar 1 (Terrain):** Titiler 2.0.0 already ships `terrainrgb` and `terrarium` algorithms. Adding `&algorithm=terrainrgb` to the existing proxy URL in `backend/app/tiles/router.py:261-291` is the only backend change needed. Frontend adds a `raster-dem` source + `setTerrain` call + a 3D toggle button.

- **Pillar 2 (Building Extrusions):** The existing `ST_AsMVT` pipeline already delivers numeric attribute columns (including `height`) as MVT feature properties. A `fill-extrusion` companion layer in `fill-adapter.ts` is the entire frontend change — zero backend work.

- **Pillar 3 (PostGIS 3D Geometry):** Z coordinates survive GeoLens ingestion (ogr2ogr has no `-dim` flag; `geom_4326` is unconstrained on dimension) — verified in `ogr.py:344-346` and `metadata.py:464`. The MVT 2.1 spec is 2D-only, so `ST_AsMVTGeom` drops Z regardless. Exposing 3D geometry requires attribute promotion (cheapest), a GeoJSON-Z endpoint (Phase C), or a deferred 3D Tiles path.

The doc closes with a recommended phase breakdown (Phase A: MEDIUM / ~5-8 tasks, Phase B: MEDIUM / ~6-10 tasks, Phase C: LARGE / ~10-15 tasks) and 7 open questions that must be resolved before any phase is promoted to ROADMAP.

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write 3D Data & Maps Support design document | 9333cf5d | `.planning/quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md` |

## Deviations from Plan

The gsd-executor's original commit (`ba0a0aa9`) inadvertently included ~76 unrelated files from stale worktree state that predated this quick task (leftover backend refactors, frontend hook deletions, test removals — all from prior sessions that never reached main). The orchestrator detected this on merge, reset main to the pre-execution HEAD (`683a5b26`), then extracted only `260408-aa5-DESIGN.md` from `ba0a0aa9` via `git checkout ba0a0aa9 -- <file>` and re-committed it atomically as `9333cf5d`. The DESIGN.md content itself is legitimate and satisfies all 8 truths + 3 key_links. Root cause: contaminated worktree base in `.claude/worktrees/agent-a68df8b6` — likely due to many stale worktree branches accumulated across prior sessions. Mitigation going forward: prune `.claude/worktrees/` before quick-task runs, or disable `workflow.use_worktrees` for quick tasks.

## Self-Check: PASSED

- [x] `.planning/quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md` exists (398 lines, >= 300 required)
- [x] All required keywords present: `Terrain`, `fill-extrusion`, `PostGIS`, `ST_AsMVT`, `terrainrgb`, `Recommended Follow-on Phases`, `Open Questions`
- [x] MapLibre cannot-do list present: true 3D meshes, point clouds, 3D Tiles, CityGML, glTF
- [x] Phase A / Phase B / Phase C all present with sizing and dependencies
- [x] Commit `ba0a0aa9` confirmed in git log
- [x] No source files (backend/, frontend/) modified in this task
