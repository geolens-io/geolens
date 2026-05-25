# Phase 1102: ADK Saved Map Composition - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Compose the primary and 3D relief ADK saved maps from the upgraded source data.
</domain>

<decisions>
## Implementation Decisions

### the agent's Discretion
The compose script should upsert maps rather than create duplicates, and map state should be durable without manual terrain or layer-order API patches.
</decisions>

<code_context>
## Existing Code Insights

`compose_marketing_maps.py` already logs every API call, bootstraps a temporary API key, ingests datasets, and creates saved maps.
</code_context>

<specifics>
## Specific Ideas

- Primary map keeps terrain disabled and vectors above rasters.
- Bonus Map 2 enables terrain with a deliberate exaggeration value and a pitched/bearing view suitable for screenshots.
- Use `PUT /api/maps/{id}` with full replacement layers for existing maps.
</specifics>

<deferred>
## Deferred Ideas

Public sharing/embedding polish is out of scope; builder verification happens in Phase 1106.
</deferred>
