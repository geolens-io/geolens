# Phase 1105: Builder Error Hygiene - Context

**Gathered:** 2026-05-24
**Status:** Ready for execution
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Keep builder map error reporting specific, non-overlapping, and console-clean for ADK marketing smoke checks.
</domain>

<code_context>
## Existing Code Insights

- `BuilderMap` routed unknown MapLibre errors into a basemap tile toast.
- The basemap notice sat at top-left and overlapped the top-left NavigationControl.
- OpenFreeMap Positron emits missing-image warnings for road shield expressions unless the remote style is sanitized before MapLibre loads it.
</code_context>
