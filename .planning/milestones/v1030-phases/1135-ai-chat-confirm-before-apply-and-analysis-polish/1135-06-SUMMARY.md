---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
plan: "06"
subsystem: qa/smoke
tags:
  - smoke
  - playwright-mcp
  - ai
  - live-verification
dependency_graph:
  requires:
    - "1135-01-SUMMARY.md (chat-action-staging.ts foundation)"
    - "1135-02-SUMMARY.md (ChatPanel staging tray + inline data card)"
    - "1135-03-SUMMARY.md (BuilderRail AIDisabledState + error banner)"
    - "1135-04-SUMMARY.md (viewport-aware suggestion chips)"
    - "1135-05-SUMMARY.md (Pitfall#5 docstring + cache key pin)"
  provides:
    - ".planning/phases/1135-ai-chat-confirm-before-apply-and-analysis-polish/1135-MCP-SMOKE.md"
  affects:
    - "Phase 1139 close-gate: SF-MCP-01 backend gap must be resolved before AI-08 is fully verified"
tech_stack:
  added: []
  patterns:
    - "Playwright headless smoke with rate-limited auth: allow 60s between login attempts; use single login per session"
    - "Builder URL is /maps/:id (not /builder/:id) via MapViewerGate → MapBuilderPage route"
    - "AI_ENABLED flip via PATCH /api/admin/ai-status (PersistentConfig DB-stored) — no .env restart required"
    - "Headless WebGL unavailability: MapLibre idle event never fires → viewport stays undefined → zoom-aware chips cannot be verified headlessly"
    - "textContent() returns empty for flex containers in headless Chrome; use .$$eval('p') to get child paragraph text"
key_files:
  created:
    - .planning/phases/1135-ai-chat-confirm-before-apply-and-analysis-polish/1135-MCP-SMOKE.md
  modified: []
decisions:
  - "AI-08 FAIL disposition: SF-MCP-01 carry-forward to Phase 1139. Backend chat_actions.py:_collect_chat_action() never sets rows on show_query_result for non-spatial queries; frontend card is ready but backend wiring is missing."
  - "AI-05 zoom-aware chips DEFERRED: headless WebGL failure prevents MapLibre idle events; 8 unit tests in Plan 04 cover the contract. Interactive verification documented in smoke report."
  - "AI_ENABLED toggle via admin API (PATCH /api/admin/ai-status) avoids docker restart; PersistentConfig stores in DB, no .env mutation required."
  - "Map restored to 6-layer state after smoke (no persistent modification — browser closed without save trigger)."
metrics:
  duration: "~75 minutes"
  completed: "2026-05-27"
  tasks_completed: 2
  files_created: 1
  files_modified: 0
---

# Phase 1135 Plan 06: Live MCP Smoke — Summary

**Live Playwright MCP smoke across 5 AI surfaces (AI_ENABLED=true) + disabled-state (AI_ENABLED=false); AI-01/AI-02/AI-05/AI-09 PASS, AI-08 FAIL (backend gap SF-MCP-01), AI-03 SKIPPED (unit-tested).**

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | AI_ENABLED=true smoke — Surfaces 1, 2, 5 | `5750adb2` | 1135-MCP-SMOKE.md |
| 2 | AI_ENABLED=false smoke — Surface 3 disabled-state | `5750adb2` | 1135-MCP-SMOKE.md (appended) |

*Tasks 1 and 2 committed together — single smoke report file.*

## Smoke Results Summary

### AI_ENABLED=true (10 sub-checks)

| REQ | Surface | Status |
|-----|---------|--------|
| AI-01/AI-09 | Staging tray render | PASS |
| AI-01 | Reject-all byte-equal | PASS |
| AI-01 | Accept-all dispatches | PASS |
| AI-01 | Accept-one partial | SKIPPED (single-action responses; unit tests cover) |
| AI-09 | Chip text format | PASS — `Remove "Land classification" (9 features)` |
| AI-01 | Tray header | PASS — `"1 pending change — review before applying"` |
| AI-08 | Inline card render | FAIL — SF-MCP-01 (see below) |
| AI-08 | 5-column cap | SKIPPED (backend gap; unit tests cover) |
| AI-08 | Empty-rows state | SKIPPED (backend gap; unit tests cover) |
| AI-05 | Initial suggestion chips | PASS — 4 geometry-type chips rendered |
| AI-05 | Zoom-aware chips | DEFERRED (headless WebGL; unit tests cover) |
| AI-03 | Error banner | SKIPPED (not naturally reproducible; unit tests cover) |
| CONSOLE | Zero error events | PASS — 0 application-level errors |

### AI_ENABLED=false (8 sub-checks, all PASS)

| REQ | Surface | Status |
|-----|---------|--------|
| AI-02 | Rail button label → "AI unavailable" | PASS |
| AI-02 | ChatPanel not mounted | PASS |
| AI-02 | "AI is disabled" title | PASS |
| AI-02 | "An administrator has disabled AI for this instance." body | PASS |
| AI-02 | BotOff icon | PASS |
| AI-02 | "Go to Settings" CTA (admin user) | PASS |
| AI-02 | `data-ai-reason="env_disabled"` attribute | PASS |
| Pitfall#4 | Console silence (zero /ai/* 4xx/5xx) | PASS |

## Key Visual Evidence (Screenshots)

- `smoke-t1-remove.png`: Staging tray with "1 pending change — review before applying", Accept all + Reject all buttons, chip "Remove 'Lan...' (9 features)" with per-chip Accept/Reject
- `smoke-t2-after-reject.png`: Staging tray gone after Reject all; layer stack unchanged (still 6 layers)
- `smoke-accept-after.png`: Layer count drops from 6 to 5 after Accept all (NHD lakes removed); "Applied 1 change" indicator
- `smoke-chips-initial.png`: AI panel with "Ask AI" + "Experimental" badge; 4 geometry-based suggestion chips
- `smoke-d2-rail-open.png`: Disabled state: BotOff icon, "AI is disabled", "An administrator has disabled AI for this instance.", "Go to Settings" button

## Deviations from Plan

### Findings

**SF-MCP-01 — AI-08 Backend Gap (FAIL, CARRY-FORWARD to Phase 1139)**

- **Found during:** Task 1 Phase 6: Surface 2 analysis query verification
- **Root cause:** `chat_actions.py:_collect_chat_action()` only creates `show_query_result` action when `query_data` returns GeoJSON geometry. For non-spatial tabular queries, the function returns `None` — no `show_query_result` action emitted to frontend. `ChatAction.rows` in `types/api.ts:1248` is defined but never populated by backend.
- **Live behavior:** "Show me the top 5 streams by length as a table" → AI returns markdown table as text, NOT `show_query_result` with rows. Frontend inline card never renders.
- **Disposition:** CARRY-FORWARD to Phase 1139. Backend fix required:
  ```python
  if tool_name == "query_data":
      action = {"type": "show_query_result"}
      if "geojson" in result: action["geojson"] = result["geojson"]; action["bbox"] = result["bbox"]
      if result.get("rows"): action["rows"] = result["rows"]
      return action
  ```
- **Files to modify:** `backend/app/processing/ai/chat_actions.py:_collect_chat_action()`
- **Note:** Plans 02 frontend (4 unit tests mock `rows` directly, all PASS) and types/api.ts definition are correct; only backend emission path missing.

**Operational Deviations (non-failing)**

- **Builder URL**: Plan spec said `/builder/:id` — actual route is `/maps/:id` via `MapViewerGate`. Corrected during smoke. Root cause: plan was written before checking App.tsx routes.
- **AI_ENABLED flip**: Plan said "edit .env + docker restart". Actual mechanism: `PersistentConfig` stores in DB; `PATCH /api/admin/ai-status {"enabled": false}` is the correct toggle. No restart needed. More production-realistic than env mutation.
- **`textContent()` on flex container**: Returns empty in headless Chrome for overflow-hidden flex containers. Fixed by checking child `<p>` elements directly — both methods confirm the correct text is rendered.
- **WebGL in headless**: MapLibre canvas throws `webglcontextcreationerror` in headless Chromium (SwiftShader). Map never renders visually, but all non-map UI (layer stack, AI rail, staging tray) functions correctly. Zoom-dependent chip testing deferred.

## Stack Mutation Timeline

| Time | Action | Result |
|------|--------|--------|
| 2026-05-27 ~19:05 | `PATCH /api/admin/ai-status {enabled: false}` | `{enabled: false}` confirmed |
| 2026-05-27 ~19:06 | AI_ENABLED=false smoke run | `data-ai-reason="env_disabled"` verified; console silence PASS |
| 2026-05-27 ~19:06 | `PATCH /api/admin/ai-status {enabled: true}` | `{enabled: true}` confirmed |
| Post-smoke | Map state check via API | 6 layers, identical to pre-smoke — no persistent modification |

## Operator Sign-Off (Autonomous Mode)

**Autonomous confidence:** NEEDS_REVIEW (1 surface FAIL: SF-MCP-01 AI-08 backend gap)

**CLEAR-TO-MERGE with follow-up:** Phase 1135 (Plans 01-05 code) is clear to merge:
- AI-01: PASS (reject-all byte-equal, accept-all dispatches, staging tray)
- AI-02: PASS (env_disabled disabled state, data-ai-reason, console silence)
- AI-03: SKIPPED with rationale (4 unit tests)
- AI-05: PASS (initial chips) + DEFERRED for zoom-aware (8 unit tests, headless constraint)
- AI-08: FAIL (SF-MCP-01 backend gap — frontend is ready, backend wiring missing)
- AI-09: PASS (chip text format verified)

**SF-MCP-01 action:** Add `rows` emission to `_collect_chat_action()` in Phase 1139 or as a dedicated quick task before v1030 close.

## Cross-References

- [1135-MCP-SMOKE.md](1135-MCP-SMOKE.md) — full evidence tables
- ROADMAP AI-01/02/03/04/05/08/09 — all closed by Plans 01-05 (live verification: 01/02/05/09 PASS, 03 SKIPPED, 08 PARTIAL-backend-gap)
- UI-SPEC Surfaces 1-5 — covered per surface
- Pitfall#4 console-silence verification — PASS (zero /ai/* 4xx/5xx in disabled mode)
- Plan 02 unit tests (AI-08) — 4 tests mock `rows` directly and PASS; live verification blocked by SF-MCP-01
- Plan 04 unit tests (AI-05) — 8 tests cover zoom-aware chip contract; live headless deferred

## Self-Check

**Files exist:**
- `.planning/phases/1135-ai-chat-confirm-before-apply-and-analysis-polish/1135-MCP-SMOKE.md`: FOUND

**Commits exist:**
- `5750adb2`: FOUND

## Self-Check: PASSED
