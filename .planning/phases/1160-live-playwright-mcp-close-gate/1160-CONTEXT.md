# Phase 1160: Live Playwright MCP Close-Gate - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Mode:** Orchestrator-driven QA gate (no executor subagent — executors lack `mcp__playwright__*`; the orchestrator drives all live MCP + the standard automated gate directly).

<domain>
## Phase Boundary

QA-01: prove every v1035 fix on the live stack + green standard gate before tagging.
- Live (orchestrator-driven, MCP/curl on the running stack): (a) SEC-01 anon vector-tile/token denial for public-unpublished; (b) BLDR-01 raster basemap below data; (c) BLDR-02 terrain eye toggles 3D; (d) BLDR-04 hypso-tint hides with parent; (e) EXP-01 anon export of public-published; (f) MAPS-01 zero createRoot errors.
- Standard gate: `npm run typecheck` 0, vitest green, `e2e:smoke:builder` + `:core` green, focused backend tiles/export pytest green, i18n parity, `make openapi-check` no-drift.

</domain>

<decisions>
## Implementation Decisions
- Orchestrator restarts api + frontend before the gate (fresh bundles — avoids the stale-bundle QA hazard). Live SEC-01/EXP-01 verified via anonymous curl against the running api (deterministic); a public dataset is temporarily flipped to `internal` to exercise the leak path, then reverted. BLDR visual behaviors covered by vitest + e2e + live observation.
</decisions>

<code_context>
## Existing Code Insights
- No code changes expected in 1160 (verification phase). Any defect found is fixed in-place and attributed to its source phase.
</code_context>

<specifics>
## Specific Ideas
- QA-01 acceptance = all 6 live items pass + the full standard gate green.
</specifics>

<deferred>
## Deferred Ideas
- None.
</deferred>
