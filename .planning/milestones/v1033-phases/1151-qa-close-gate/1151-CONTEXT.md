# Phase 1151: QA Close-Gate - Context

**Gathered:** 2026-05-29
**Status:** Ready (orchestrator-driven)
**Mode:** Close-gate — no planner/executor. QA-01 (live Playwright MCP) is orchestrator-only (subagents lack `mcp__playwright__*`); QA-02 (code gates) run inline.

<domain>
## Phase Boundary
Verify v1033 (phases 1148-1150) on the two ADK sample maps via live MCP + run the deterministic code gates + write the CHANGELOG. Requirements: QA-01, QA-02.
</domain>

<decisions>
- QA-01 driven by the orchestrator directly (live MCP). Evidence in `.planning/audits/v1033-evidence/`.
- QA-02 gates: frontend typecheck + full vitest + test:i18n + lint; backend raster+tile pytest; `make openapi-check` (expect no drift); `e2e:smoke:builder`.
- CHANGELOG entry `[1.8.0] - 2026-05-29` (v1032 was 1.7.0; v1033 adds the label indicator feature + fixes → minor bump).
</decisions>

<specifics>
Map A (`8dd6a129`): terrain on fresh load; DEM editor shows Terrain; label indicator present/absent; single render-as control; 0 console errors. Map B (`c39be324`): hillshade renders, terrain off, 0 console errors.
</specifics>

<deferred>None.</deferred>
