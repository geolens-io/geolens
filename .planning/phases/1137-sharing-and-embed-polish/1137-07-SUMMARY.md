---
phase: 1137-sharing-and-embed-polish
plan: "07"
subsystem: smoke-checklist
tags: [share, mcp-smoke, close-gate, orchestrator-driven]

requires:
  - phase: 1137-01
    provides: url-normalize helper (url-normalize.ts, 22 vitest, SHARE-06)
  - phase: 1137-02
    provides: backend CSP no-* invariant (schema 422 + _build_frame_ancestors drop)
  - phase: 1137-03
    provides: ViewerMap showInlineBranding + SHARE-09 export PNG pins
  - phase: 1137-04
    provides: SharePanel chip-based allowed-origins UI (SHARE-02/SHARE-06)
  - phase: 1137-05
    provides: expiration preset Select + Pitfall #6 docstrings (SHARE-04)
  - phase: 1137-06
    provides: iframe preview pane + inflightEmbedCreate ref (SHARE-03/Pitfall #7)

provides:
  - "1137-MCP-SMOKE.md: 573-line orchestrator-driven Playwright smoke checklist covering all 6 SHARE REQs + 3 Pitfalls + 7 HARD-INVARIANTs"

affects:
  - "Orchestrator (follows checklist directly using mcp__playwright__* tools)"
  - "Phase 1137 close-gate decision (PASS/PARTIAL/FAIL aggregate)"

tech-stack:
  added: []
  patterns:
    - "Orchestrator-driven MCP smoke pattern: checklist artifact produced by executor; orchestrator follows directly"

key-files:
  created:
    - .planning/phases/1137-sharing-and-embed-polish/1137-MCP-SMOKE.md
  modified: []

decisions:
  - "Checklist uses data-testid selectors where available (data-testid='share-preview-iframe', 'viewer-branding-overlay') + aria-role/label fallbacks for surfaces without testids"
  - "Section 6 (Pitfall #7 race) is best-effort UI smoke — authoritative pin is the vitest test; MCP smoke confirms production code path matches"
  - "Enterprise edition branding suppression (SHARE-07) marked DEFERRED TO UNIT TESTS — 4 vitest pins cover isEnterprise:true path; dev stack runs community edition"
  - "Export PNG (SHARE-09) visual verify deferred to unit tests — auto-download path varies by OS; 4 regression pins in use-builder-save.test.ts are authoritative"

metrics:
  duration: "~5min"
  completed: "2026-05-27"
  tasks_completed: 1
  files_changed: 1
---

# Phase 1137 Plan 07: MCP Smoke Checklist Artifact Summary

**573-line orchestrator-driven Playwright smoke checklist covering SHARE-02/03/04/06/07/09 plus Pitfalls #6/#7/#8 plus 7 HARD-INVARIANT grep checks; ready for orchestrator to follow directly on live localhost:8080.**

## What Was Built

### Task 1: 1137-MCP-SMOKE.md

Created `.planning/phases/1137-sharing-and-embed-polish/1137-MCP-SMOKE.md` — a self-contained, 9-section checklist the orchestrator follows directly using `mcp__playwright__*` tools.

**Sections:**

1. **SHARE-02 / SHARE-06 — Chip-Based Allowed Origins** (Steps 1.1–1.13)
   - Navigate to builder → open Share dialog → enable domain restriction → add `Example.com` → verify canonical chip `https://example.com` → try `*` → verify inline "Wildcard origin not allowed" error → remove chip
   - Tools named: `mcp__playwright__browser_navigate`, `mcp__playwright__browser_click`, `mcp__playwright__browser_type`, `mcp__playwright__browser_evaluate`, `mcp__playwright__browser_take_screenshot`

2. **SHARE-04 — Expiration Preset Select** (Steps 2.1–2.7)
   - Open Select → verify 6 options → pick "7 days" (no extra Save) → Pitfall #6 check (Copy link still present) → "Custom date…" reveals DatePicker
   - Tools named: `mcp__playwright__browser_click`, `mcp__playwright__browser_evaluate`, `mcp__playwright__browser_take_screenshot`

3. **SHARE-07 — Community-Edition Viewer Branding** (Steps 3.1–3.7)
   - Non-embed mode: AppFooter present, inline overlay absent
   - Embed mode: inline overlay `"Powered by GeoLens"` present, AppFooter absent
   - Tools named: `mcp__playwright__browser_navigate`, `mcp__playwright__browser_evaluate`, `mcp__playwright__browser_take_screenshot`

4. **SHARE-09 — Legend + Title in Shared Viewer** (Steps 4.1–4.7)
   - Map title block renders, MapLegend overlay present, `?legend=false` hides legend, export PNG via unit tests
   - Tools named: `mcp__playwright__browser_navigate`, `mcp__playwright__browser_evaluate`, `mcp__playwright__browser_click`, `mcp__playwright__browser_take_screenshot`

5. **SHARE-03 — Iframe Embed-Preview Pane** (Steps 5.1–5.9)
   - Preview collapsed by default, click to expand, sandbox = `"allow-scripts"` ONLY (SEC-07), title = `"Map embed preview"`, security footer visible
   - Tools named: `mcp__playwright__browser_navigate`, `mcp__playwright__browser_click`, `mcp__playwright__browser_evaluate`, `mcp__playwright__browser_take_screenshot`

6. **Pitfall #7 — inflightEmbedCreate Race Dedupe** (Steps 6.1–6.6)
   - Double-click "Generate share link" via evaluate → verify only 1 POST for embed-token endpoint via `performance.getEntriesByType` + `mcp__playwright__browser_console_messages`
   - Tools named: `mcp__playwright__browser_click`, `mcp__playwright__browser_evaluate`, `mcp__playwright__browser_take_screenshot`, `mcp__playwright__browser_console_messages`

7. **HARD-INVARIANT Regression Sweep** (7 Bash grep checks)
   - sandbox="allow-scripts" count, allow-same-origin as JSX attr, BuilderActionSource absent, SHARE-08 not touched, frame-ancestors no-*, inflightEmbedCreate present, url-normalize exports (4)

8. **Pitfall #8 — Canonical Form Round-Trip** (Bash unit test confirmation)
   - `npm test -- url-normalize --run`: 22 passed

9. **Final Sign-Off Table** (12-row aggregate)
   - All 6 SHARE REQ IDs + 3 Pitfalls + HARD-INVARIANTs + aggregate PASS/PARTIAL/FAIL field

## Task Commits

1. **Task 1: MCP smoke checklist** — `e5d96089` (docs)
   - `.planning/phases/1137-sharing-and-embed-polish/1137-MCP-SMOKE.md` created (573 lines)

## Hand-off Contract

**Phase 1137 implementation complete (Plans 01-06 shipped).**

Checklist artifact `1137-MCP-SMOKE.md` is now ready.

Per `feedback_playwright_mcp_orchestrator_only` memory:
- The **orchestrator** has `mcp__playwright__*` tools and MUST drive the smoke.
- **gsd-executor sub-agents do NOT have those tools** — never delegate the smoke to an executor spawn.

**Orchestrator action on resume:**
1. Open `.planning/phases/1137-sharing-and-embed-polish/1137-MCP-SMOKE.md`
2. Pre-flight: confirm `docker compose ps` shows 5 healthy services.
3. Execute Sections 1–9 in sequence, calling the named `mcp__playwright__*` tools + Bash greps.
4. Fill in the Section 9 sign-off table with aggregate disposition.
5. Surface to operator: "X/12 PASS, Y PARTIAL, Z FAIL" and either close Phase 1137 or propose a v1137.1 carry-forward plan.

## Deviations from Plan

None — plan executed exactly as written. The checklist structure matches the plan's 8-section spec; an additional Section 8 (Pitfall #8 unit confirmation) was added to cover the Pitfall #8 sign-off table row more completely.

## Self-Check: PASSED

- File exists: `.planning/phases/1137-sharing-and-embed-polish/1137-MCP-SMOKE.md` — YES (573 lines)
- Commit exists: `e5d96089` — verified in git log
- `mcp__playwright__` occurrences: 68 (> 15 required)
- Section headers: 9 (`## Section 1` through `## Section 9`)
- Disposition references: 16

---
*Phase: 1137-sharing-and-embed-polish*
*Completed: 2026-05-27*
