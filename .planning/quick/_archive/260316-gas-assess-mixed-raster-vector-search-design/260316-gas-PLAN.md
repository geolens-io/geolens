---
phase: quick-260316-gas
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260316-gas-assess-mixed-raster-vector-search-design/GAP-ANALYSIS.md
  - .planning/quick/260316-gas-assess-mixed-raster-vector-search-design/IMPLEMENTATION-ROADMAP.md
autonomous: true
requirements: [quick-260316-gas]

must_haves:
  truths:
    - "Gap analysis covers all 5 gap categories from research: standards alignment, search/discovery, UI/UX, VRT lifecycle, STAC export"
    - "Each gap has current state, target state, effort estimate, and priority"
    - "Roadmap phases are ordered by dependency and value delivery"
    - "Roadmap references specific files that need modification for each work item"
  artifacts:
    - path: ".planning/quick/260316-gas-assess-mixed-raster-vector-search-design/GAP-ANALYSIS.md"
      provides: "Comprehensive gap analysis comparing current codebase to design doc"
      min_lines: 150
    - path: ".planning/quick/260316-gas-assess-mixed-raster-vector-search-design/IMPLEMENTATION-ROADMAP.md"
      provides: "Phased implementation roadmap derived from gap analysis"
      min_lines: 100
  key_links:
    - from: "IMPLEMENTATION-ROADMAP.md"
      to: "GAP-ANALYSIS.md"
      via: "Each roadmap phase references specific gaps by ID"
      pattern: "GAP-"
---

<objective>
Produce a comprehensive gap analysis and phased implementation roadmap for aligning GeoLens with the proposed record-first discovery architecture (OGC API Records, STAC 1.1, mixed raster/vector search).

Purpose: Give the project owner a clear picture of what exists, what is missing, and a sequenced plan to close the gaps -- enabling informed prioritization of future milestones.
Output: Two documents -- GAP-ANALYSIS.md and IMPLEMENTATION-ROADMAP.md -- in the quick task directory.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260316-gas-assess-mixed-raster-vector-search-design/260316-gas-CONTEXT.md
@.planning/quick/260316-gas-assess-mixed-raster-vector-search-design/260316-gas-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Deep codebase audit and gap analysis document</name>
  <files>.planning/quick/260316-gas-assess-mixed-raster-vector-search-design/GAP-ANALYSIS.md</files>
  <action>
Read the following files to build a complete picture of current state:

Backend (search/discovery):
- `backend/app/search/router.py` -- search endpoints, OGC Records items
- `backend/app/search/service.py` -- search_datasets(), dataset_to_ogc_record(), _build_assets()
- `backend/app/search/schemas.py` -- search request/response schemas
- `backend/app/ogc/router.py` -- OGC Features endpoints, conformance
- `backend/app/ogc/conformance.py` or wherever conformance classes are declared
- `backend/app/datasets/router.py` -- dataset detail endpoint
- `backend/app/datasets/schemas.py` -- DatasetResponse shape

Backend (data model):
- `backend/app/datasets/models.py` -- Dataset, Record models
- `backend/app/raster/models.py` -- RasterAsset, DatasetAsset, VrtSourceLink
- `backend/app/records/router.py` -- VRT/raster record endpoints

Frontend (search UI):
- `frontend/src/pages/SearchPage.tsx`
- `frontend/src/components/search/FilterPanel.tsx`
- `frontend/src/components/search/DatasetCard.tsx`
- `frontend/src/stores/search-store.ts`
- `frontend/src/pages/DatasetPage.tsx` or equivalent detail page

Write GAP-ANALYSIS.md with this structure:

1. **Executive Summary** -- 3-5 sentence overview of alignment status
2. **Methodology** -- What was compared (codebase vs design doc recommendations)
3. **Current Capabilities Summary** -- What GeoLens already does well
4. **Gap Inventory** -- Organized by category, each gap gets:
   - Gap ID (e.g., GAP-STD-01, GAP-SEARCH-01, GAP-UI-01, GAP-VRT-01, GAP-STAC-01)
   - Title
   - Current State (with file references)
   - Target State (from design doc)
   - Priority (Critical / High / Medium / Low)
   - Effort estimate (S/M/L/XL)
   - Dependencies on other gaps
5. **Gap Categories:**
   - Standards Alignment (OGC Records conformance, datetime param, assets merge, STAC properties on records)
   - Search/Discovery (faceted counts, aggregation endpoint, keyword facets, datetime param)
   - UI/UX (faceted count badges, keyword filter UI, detail page consistency)
   - VRT Lifecycle (regeneration, generation tracking, source health)
   - STAC Export (dedicated STAC Item endpoint, STAC Catalog/Collection, extensions declaration)
6. **Cross-cutting Concerns** -- Shared patterns (e.g., assets refactoring affects both standards and STAC export)
7. **Summary Matrix** -- Table of all gaps with priority and effort

Use the RESEARCH.md findings as the starting point but verify and deepen each gap with actual code inspection. Add specific line references or function names where relevant.
  </action>
  <verify>
    <automated>test -f ".planning/quick/260316-gas-assess-mixed-raster-vector-search-design/GAP-ANALYSIS.md" && wc -l ".planning/quick/260316-gas-assess-mixed-raster-vector-search-design/GAP-ANALYSIS.md" | awk '{if ($1 >= 150) print "PASS: "$1" lines"; else print "FAIL: only "$1" lines"}'</automated>
  </verify>
  <done>GAP-ANALYSIS.md exists with 150+ lines covering all 5 gap categories, each gap has an ID, current/target state, priority, effort, and dependencies</done>
</task>

<task type="auto">
  <name>Task 2: Phased implementation roadmap derived from gaps</name>
  <files>.planning/quick/260316-gas-assess-mixed-raster-vector-search-design/IMPLEMENTATION-ROADMAP.md</files>
  <action>
Using the completed GAP-ANALYSIS.md, write IMPLEMENTATION-ROADMAP.md with this structure:

1. **Overview** -- How gaps were sequenced (dependency order, value delivery, risk reduction)
2. **Phasing Strategy** -- Explain the rationale: quick wins first, then foundations, then features, then polish
3. **Phase Breakdown** (4-6 phases):

For each phase:
- Phase name and theme
- Gap IDs addressed (referencing GAP-ANALYSIS.md)
- Prerequisites (which earlier phases must complete)
- Work items with:
  - Specific files to create/modify
  - What changes (endpoint additions, schema changes, UI components)
  - Acceptance criteria
- Estimated scope (number of plans, approximate context budget)
- Value delivered (what becomes possible after this phase ships)

Suggested phasing (adjust based on actual gap analysis):
- **Phase 1: Standards Foundation** -- OGC Records conformance, datetime param, merge assets keys. Low risk, high standards alignment.
- **Phase 2: Search Enhancement** -- Faceted counts endpoint, aggregate query, type count badges in UI. Medium effort, high user value.
- **Phase 3: STAC Export Layer** -- Dedicated STAC Item/Collection endpoints, stac_extensions declaration. Medium effort, enables machine clients.
- **Phase 4: UI Discovery Polish** -- Keyword facet UI, detail page consistency, additional filters. Medium effort, UX refinement.
- **Phase 5: VRT Lifecycle** -- Regeneration endpoint, generation tracking, source health monitoring. Higher effort, operational value.

4. **Dependency Graph** -- Mermaid diagram showing phase dependencies
5. **Risk Assessment** -- What could go wrong, migration concerns, breaking changes
6. **Quick Wins** -- Things that can be done immediately with minimal risk (e.g., conformance declaration, stac_extensions array)
7. **Decision Points** -- Choices the project owner needs to make before certain phases (e.g., whether to fully separate STAC endpoints or keep unified)
  </action>
  <verify>
    <automated>test -f ".planning/quick/260316-gas-assess-mixed-raster-vector-search-design/IMPLEMENTATION-ROADMAP.md" && grep -c "GAP-" ".planning/quick/260316-gas-assess-mixed-raster-vector-search-design/IMPLEMENTATION-ROADMAP.md" | awk '{if ($1 >= 5) print "PASS: references "$1" gap IDs"; else print "FAIL: only "$1" gap references"}'</automated>
  </verify>
  <done>IMPLEMENTATION-ROADMAP.md exists with 4-6 phases, each referencing specific gap IDs from GAP-ANALYSIS.md, with file-level work items, acceptance criteria, and a dependency graph</done>
</task>

</tasks>

<verification>
- Both documents exist in the quick task directory
- GAP-ANALYSIS.md covers all 5 categories with gap IDs
- IMPLEMENTATION-ROADMAP.md references gap IDs from the analysis
- Roadmap phases have concrete file references and acceptance criteria
- No code changes made -- documents only
</verification>

<success_criteria>
- Gap analysis identifies and catalogs every gap from the research plus any additional gaps found during deep code inspection
- Each gap has actionable detail: current state with file references, target state, priority, effort, dependencies
- Roadmap phases are logically sequenced by dependency and value
- Project owner can use the roadmap to create future GSD milestones
</success_criteria>

<output>
After completion, create `.planning/quick/260316-gas-assess-mixed-raster-vector-search-design/260316-gas-SUMMARY.md`
</output>
