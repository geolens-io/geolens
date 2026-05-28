---
phase: "1139"
name: "Quality Sweep and Playwright Close-Gate"
gathered: "2026-05-28"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss)"
---

# Phase 1139: Quality Sweep and Playwright Close-Gate — Context

<domain>
## Phase Boundary

Close v1030 via live Playwright MCP across three viewports, disabled-AI smoke, full test/lint/i18n green, CHANGELOG `[Unreleased]` populated, and OpenAPI/SDK refresh where backend changed. Canonical close-gate (v1027/v1028/v1029 precedent).

**Requirements:** QA-01, QA-02, QA-03, QA-04.

**4 ROADMAP success criteria:**
1. Live Playwright MCP at 1440×900 / 800×600 / 414×896: every render mode renders, layer ops (add/delete/toggle/rename/drag) work, save persists across reload, shared/embed parity, ZERO console errors per viewport.
2. Live MCP with `AI_ENABLED=false`: AI rail actionable disabled state, no inert button, no `/ai/*` console errors, no broken-canvas.
3. `npm run typecheck` exit 0; vitest green; `npm run lint` exit 0; `e2e:smoke:builder` green; i18n parity 2/2.
4. CHANGELOG `[Unreleased]` populated with measured numbers; OpenAPI snapshot regenerated where backend changed (ai/router.py in 1135, maps/router.py + embed_tokens/schemas.py in 1137); SDK regenerated (Pitfall #15 — OpenAPI/types diff non-empty AND CHANGELOG silent is a blocker).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion + Orchestrator-driven MCP
All choices at Claude's discretion. **Live MCP is orchestrator-driven** (per feedback_playwright_mcp_orchestrator_only — gsd-executor lacks mcp__playwright__* access).

### Pre-Decided Anchors
- **Backend changed surfaces (OpenAPI refresh needed):** Phase 1135 `backend/app/processing/ai/chat_actions.py` (show_query_result rows) + `ai/router.py`/`sql_generator.py` docstrings; Phase 1137 `backend/app/modules/embed_tokens/schemas.py` (wildcard reject) + `maps/router.py` (CSP frame-ancestors). Check if any of these changed the OpenAPI surface (request/response shapes) — docstring-only changes don't, but schema validation changes might.
- **OpenAPI dual-snapshot order (project memory):** `make openapi` (geolens) BEFORE `npm run fetch-openapi` (sibling docs).
- **CHANGELOG measured numbers:** RasterEditor stub → 7 controls (5 raster sliders + Fade + Opacity); line-cap/line-join added; AI confirm = Shape B (pendingLayers staging buffer); share polish = chips + presets + branding + legend + iframe preview.
- **AI_ENABLED=false smoke:** requires stack restart with env override. Test then restore.
- **Pre-existing e2e failures (project memory):** `accessibility.spec.ts:151` + `builder-unified-stack.spec.ts:193` are NOT regressions (reproduce on 736cffca). Document, don't fix.

</decisions>

<code_context>
## Existing Code Insights

- `frontend/package.json` (typecheck, lint, test, e2e:smoke:builder, i18n scripts)
- `CHANGELOG.md` ([Unreleased] section)
- `Makefile` (openapi target)
- Backend changed files in 1135/1137 (OpenAPI surface check)
- Carry-forward findings from prior phases' MCP verifies (1134-06, 1135-06, 1137-MCP-VERIFY, 1138-MCP-VERIFY)

</code_context>

<specifics>
## Specific Ideas

- Plan 01: Quality gates (typecheck/vitest/lint/e2e:smoke:builder/i18n) — executor runs all, reports green or surfaces failures.
- Plan 02: CHANGELOG [Unreleased] + OpenAPI/SDK refresh — executor.
- Plan 03: Orchestrator-driven 3-viewport live MCP + disabled-AI smoke — checklist artifact + orchestrator drives.

</specifics>

<deferred>
## Deferred Ideas

- CI-01-v1030 GH Actions billing — carry-forward, outside polish scope (STATE.md blocker).
</deferred>
