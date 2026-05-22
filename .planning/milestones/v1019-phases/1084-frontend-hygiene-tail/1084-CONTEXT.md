# Phase 1084: Frontend Hygiene Tail - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

The frontend build is clean: zero TypeScript errors and zero spurious console noise on the two documented surfaces (`/maps/new` 422s, `/api/api/` doubled prefix).

This is a hygiene phase. Scope is three independent localized frontend fixes covering REQ TD-09 (36 TS errors in 14 untouched test files), TD-11 (`/maps/new` 422 console-noise pattern from v1008 catalog-first empty-state quirk), and TD-12 (legacy `/api/api/` doubled prefix on quicklook proxy URLs).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP phase goal, success criteria, REQUIREMENTS.md TD-09/TD-11/TD-12 descriptions, and codebase conventions to guide decisions.

### Pre-locked decisions from REQUIREMENTS.md / user direction:
- **TD-09** fix shape: zero `@ts-expect-error` / `@ts-ignore` suppressions added; resolve at root cause in each of the 14 files identified in v1018 Phase 1083 baseline
- **TD-11** fix shape (two options, planner picks based on code structure): (a) gate network calls behind dialog-resolution state, OR (b) route `/maps/new` directly to Create dialog without mounting live editor surface
- **TD-12** fix at source (not nginx patch): identify whether duplication lives in `frontend/src/api/` client base-URL vs route table; fix the single source of truth
- **Verification** uses Playwright MCP for live network-log assertions on (b) `/maps/new` 422 count and (c) `/api/api/` URL pattern count (per user direction `--use-playwright-mcp` flag to autonomous run)

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Expected touch points:
- `frontend/src/**/*.test.{ts,tsx}` — 14 untouched test files with the 36 TS errors
- `frontend/src/pages/MapBuilderPage.tsx` or related catalog-first empty-state plumbing (v1008 origin)
- `frontend/src/api/` — base URL client where doubled-prefix likely originates
- `frontend/src/api/client.ts` `apiFetch()` — known central API client

</code_context>

<specifics>
## Specific Ideas

**TD-09 specifics:**
- Pin behaviour: `cd frontend && npm run typecheck` exit 0 against full project
- Delta target: v1017 baseline (36 errors / 14 files) → v1019 close (0 errors / 0 files)
- Track in CHANGELOG `[1.5.4]` block

**TD-11 specifics:**
- Symptom: visiting `/maps/new` page mounts the live editor, fires 2 mutation hooks against the not-yet-created map (returning 422), then the Create dialog short-circuit takes over and renders the dialog
- Verification: Playwright MCP session visiting `/maps/new` → assert zero 422 entries in network log

**TD-12 specifics:**
- Symptom: legacy quicklook proxy URLs generate `/api/api/<resource>` due to double-prefix concatenation
- All current responses 200 OK (cosmetic), but blocks per-prefix middleware
- Verification: Playwright MCP session → grep network log → assert zero `/api/api/` patterns

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. All TD-09/11/12 scope is fixed by REQUIREMENTS.md.

</deferred>
