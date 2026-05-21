---
status: complete
---

# Quick Task 260421-m3b: Create /map-audit command

**Completed:** 2026-04-21

## What was done

Created `.claude/commands/map-audit.md` (706 lines) — a comprehensive audit command for inspecting a specific saved map by UUID.

## Command structure

- **INTAKE**: Fetches map via live API (`curl /api/maps/{id}/`), parses JSON, extracts layer catalog and share state
- **6 parallel subagents**: Style Quality, Data Integrity, Performance, Design Quality, MapLibre Spec Compliance, Sharing & Access
- **Playwright MCP**: Visual verification — screenshots rendered map, tests dark mode, responsive, shared view
- **SYNTHESIS**: A-F grading per dimension (Style Quality and Spec Compliance weighted 2x)
- **DELIVERY**: Report to `docs-internal/audits/map-audit-{YYYYMMDD}.md`

## Key features

- Scoped execution: `/map-audit <id> style` runs only style quality checks
- Embedded MapLibre Style Spec reference (valid properties, expressions, enums, ranges)
- Custom property exemptions (underscore-prefixed GeoLens paint props)
- 14 false-positive exemptions in WHAT NOT TO FLAG
- Comparison to prior audit for same map

## Artifacts

- `.claude/commands/map-audit.md` — the command file
