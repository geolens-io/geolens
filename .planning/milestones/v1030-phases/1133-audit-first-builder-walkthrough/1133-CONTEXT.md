---
phase: "1133"
name: "Audit-First Builder Walkthrough"
gathered: "2026-05-27"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss)"
---

# Phase 1133: Audit-First Builder Walkthrough — Context

<domain>
## Phase Boundary

Produce a single ground-truth backlog (`BUILDER-WALKTHROUGH-AUDIT.md`) that downstream phases (1134-1138) verify against, plus the AI consumer-gating matrix and a `todo.md` staleness pass that prevents already-shipped items from being re-scheduled.

This is the **mandatory audit-first phase** for v1030 — hard precedent from v1019 / v1020 / v1021 / v1027 / v1028 (audit-first sequencing) AND v1011's 11/11 live MCP smoke methodology.

Per ROADMAP success criteria:
1. `BUILDER-WALKTHROUGH-AUDIT.md` exists at `.planning/phases/1133-*/` with one finding per surface, triaged P0/P1/P2, covering every render mode (fill / line / circle / symbol / heatmap / cluster / raster / basemap / DEM/terrain) and citing the canonical ADK map plus at least one representative map per mode.
2. The audit doc contains a complete AI consumer-gating matrix: every `/ai/*` endpoint × frontend hook with explicit columns for `enabled: !!token && aiEnabled` gating, 403 distinct surface, and 503 distinct surface (Pitfall #4).
3. Each `todo.md` line 96-171 item is classified as `closed-in-prior-milestone` / `live-regression` / `genuine-new-gap` with a milestone citation per closed item (Pitfall #13).
4. v1027 typed action-boundary + v1026 reconciler + v1008 unified-stack invariants verified live: `grep` for `map.setPaintProperty` / `map.setLayoutProperty` outside `layer-adapters/` and `map-sync.ts` returns clean; `BuilderLayerAction` union remains the only mutation entry point.
5. SHARE-08 (OG-cards) disposition recorded: 1200×630 thumbnail variant exists OR a Future Requirements entry flags SHARE-08 to v1031 with rationale.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, and codebase conventions to guide decisions.

### Key Pre-Decided Anchors (from ROADMAP & STATE)
- **Audit-first invariant**: This phase must ship `BUILDER-WALKTHROUGH-AUDIT.md` BEFORE any code-touching phase (1134+) starts. No code changes in 1133 except the audit doc.
- **MCP-driven**: Live Playwright MCP at `http://localhost:8080` against canonical ADK map `c39be324-6815-40e5-8143-00a2723827b2` plus representative maps per render mode.
- **Pitfall #4 (AI gating)**: Every `/ai/*` hook must show `enabled: !!token && aiEnabled` per v1010.2 SF-06 pattern.
- **Pitfall #13 (todo.md staleness)**: Cross-reference every todo.md line 96-171 against v1011 / v1027 / v1028 / v1029 milestone summaries to detect already-shipped items.
- **Pitfall #10 (smaller screen)**: Audit ≤800px collisions but DO NOT propose moving NavigationControl — v1011 RESP-01/02 contract holds.

</decisions>

<code_context>
## Existing Code Insights

Will be gathered during plan-phase research. Anchor files for the audit doc:
- `frontend/src/pages/MapBuilderPage.tsx` (layer dispatch + scene routing)
- `frontend/src/builder/dispatchLayerAction.ts` + `frontend/src/builder/layer-adapters/` (v1027 typed boundary)
- `frontend/src/builder/map-sync.ts` (v1026 reconciler)
- `frontend/src/builder/ai/` (AI chat surface + consumer hooks)
- `frontend/src/components/MapShareSheet.tsx` (post-3ed5ceb3 token separation)
- `.planning/todo.md` lines 96-171 (staleness pass source)

</code_context>

<specifics>
## Specific Ideas

- The audit doc is a SINGLE markdown file at `.planning/phases/1133-audit-first-builder-walkthrough/1133-BUILDER-WALKTHROUGH-AUDIT.md`.
- Findings are tabulated by render mode with columns: Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer | Owning Phase.
- AI matrix is a separate section/table within the same doc.
- todo.md staleness pass is a separate section with classification per item.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. ROADMAP phase description is the spec.

</deferred>
