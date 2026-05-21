# Quick Task 260421-m3b: Create map-audit command - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Task Boundary

Review existing .claude/commands/ conventions and create a new `/map-audit` command that audits a specific saved map by ID — covering style quality, data integrity, performance, design, MapLibre spec compliance, and sharing/access.

</domain>

<decisions>
## Implementation Decisions

### Map Input Method
- Map ID as the `$ARGUMENTS` parameter (UUID)
- Usage: `/map-audit <map-id>` or `/map-audit <map-id> <scope>`

### Audit Dimensions
- Full coverage: style quality, data integrity, performance concerns, design quality, MapLibre Style Spec compliance, sharing/access
- Supports scoped execution via `$ARGUMENTS` (e.g., `/map-audit <id> style`, `/map-audit <id> data`)

### Data Access
- Live API fetch via `curl` to `/maps/{id}/` endpoint (requires running server)
- Falls back gracefully if server not running

### Visual Verification
- Playwright MCP integration for visual verification of the rendered map
- Navigate to the map viewer, screenshot, inspect rendered layers, check dark mode, etc.
- Similar pattern to builder-audit Subagent 7 Phase B

</decisions>

<specifics>
## Specific Ideas

- Follow the exact structure of existing commands (INTAKE → SUBAGENT DISPATCH → SYNTHESIS → DELIVERY)
- Include scoped execution support like builder-audit (`/map-audit <id> style`, `/map-audit <id> data`, etc.)
- Audit report goes to `docs-internal/audits/map-audit-{YYYYMMDD}.md`
- Include "WHAT NOT TO FLAG" section for known acceptable patterns
- Include "RELATIONSHIP TO OTHER COMMANDS" section

</specifics>

<canonical_refs>
## Canonical References

- `.claude/commands/builder-audit.md` — closest analog (map builder audit with Playwright MCP)
- `backend/app/modules/catalog/maps/models.py` — Map/MapLayer models
- `backend/app/modules/catalog/maps/schemas.py` — API response schemas
- `frontend/src/types/api.ts` — MapResponse/MapLayerResponse TypeScript types
- `frontend/src/components/builder/layer-adapters/` — layer rendering logic

</canonical_refs>
