---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
verified: 2026-05-27T20:30:00Z
status: passed
close_gate_resolution: "human_needed items deferred to Phase 1139 close-gate; verified live in 1139-CLOSE-GATE-SMOKE.md (3-viewport MCP + disabled-AI + save-persist + shared/embed parity). See v1030-MILESTONE-AUDIT.md."
score: 5/5
overrides_applied: 0
re_verification: false
human_verification:
  - test: "Zoom-aware suggestion chips — zoom >= 12 + vector layer"
    expected: "'Show nearby features in this area' chip appears in AI panel at zoom 12+"
    why_human: "MapLibre idle event never fires in headless Chromium (WebGL unavailable); viewport state stays undefined; 8 unit tests cover the contract but live chip render requires a real browser"
  - test: "Selected-layer summarize chip"
    expected: "'Summarize @[layer name] attributes' chip leads the suggestion list when a layer row is expanded"
    why_human: "Same headless WebGL constraint — expandedLayerId can be set but viewport.selectedLayerName only propagates after idle event fires in a real browser"
  - test: "Inline data-analysis card — live end-to-end"
    expected: "Asking 'Show the top 5 streams by length as a table' renders an inline table card with rows in the assistant bubble (not markdown text)"
    why_human: "SF-MCP-01 was fixed inline at commit 4b643bde after Plan 06 smoke. The fix emits show_query_result with columns+rows+row_count for non-spatial query_data. 5 backend tests pass. Live re-verification that the card now renders end-to-end requires an actual AI query against the running stack."
---

# Phase 1135: AI Chat Confirm-Before-Apply and Analysis Polish — Verification Report

**Phase Goal:** Add confirm-before-apply staging for destructive AI actions, action preview chips, viewport-aware suggestions, and an inline data-analysis card — all on top of the v1027 typed action boundary without bypassing it.
**Verified:** 2026-05-27T20:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can preview destructive AI actions (add_layer, remove_layer) before they apply, accept or reject each staged action, and rejecting leaves the map byte-equal to the pre-prompt layer state; regression test pinned in ChatPanel.test.tsx | VERIFIED | `useChatActionStaging` wired in `ChatPanel.tsx:378`; `rejectAll()` → `pendingActions = []`, zero dispatcher calls (11/11 staging tests PASS); live MCP smoke: layers_before=6, layers_after=6 after Reject all |
| 2 | Action preview chips render before destructive actions apply, showing the staged change in human-readable form ("Add 'NYC subway' below 'Counties'"); chips gated on staging Shape B | VERIFIED | `buildChipText` helper in `ChatPanel.tsx:228-243`; staging tray renders `<role="region" aria-label="Pending AI actions">`; live MCP: chip text "Remove 'Land classification' (9 features)" matches UI-SPEC format; 9 ChatPanel tests PASS |
| 3 | Suggestion chips reflect current viewport + selected-layer context (not static default list); data-analysis questions render in inline card via existing show_query_result action | PARTIAL (human needed) | `ViewportContext` interface + `getSmartSuggestions` viewport param: VERIFIED in code + 16/16 chat-suggestions tests; `MapBuilderPage.tsx` idle-event debounce wiring: VERIFIED; inline card render (AI-08): VERIFIED in unit tests (mock rows, 4/4 PASS) and backend emit (SF-MCP-01 fix at `4b643bde`, 5/5 regression tests PASS); zoom-aware + selected-layer chips require live browser (headless WebGL constraint); AI-08 end-to-end requires live stack re-verification post-fix |
| 4 | AI_ENABLED=false → actionable disabled state; invalid key → recoverable banner + retry; every new AI hook gated on `enabled: !!token && aiEnabled` | VERIFIED | `AIDisabledState` in `BuilderRail.tsx:26-87`; BotOff icon, 3-reason taxonomy (env_disabled/no_key/permission), admin CTA; `errorBanner` state in `ChatPanel.tsx:170`; 503 → banner+Retry, 403 → banner+Dismiss; `useAIAvailability` gated `enabled: !!token && isAdmin`; live MCP: all 8 AI_ENABLED=false checks PASS; 13/13 BuilderRail + 35/35 ChatPanel tests PASS |
| 5 | `_validate_chat_layers` visibility-filter decision documented in chat_actions.py docstring (canonical: router.py); schema-context cache key remains (map_id, content_hash) — no dataset_id-only shortcut | VERIFIED | Pitfall #5 docstring paragraph at `router.py:108-122`; `sql_generator.py` cache key docstring updated; 4/4 backend regression tests PASS including `test_validate_chat_layers_docstring_pins_visibility_decision` |

**Score:** 5/5 truths verified (SC-3 partially deferred to human — viewport zoom and inline card live e2e require real browser/stack)

### Deferred Items

None (all truths verify against the codebase; only interactive behaviors need human confirmation).

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/builder/ai/chat-action-staging.ts` | Shape B staging buffer module — NEW | VERIFIED | Exports `PendingAction`, `ChatActionStaging`, `isDestructiveAction`, `useChatActionStaging`; ~170 LOC; `actionsRef` mirror pattern |
| `frontend/src/builder/ai/__tests__/chat-action-staging.test.ts` | 11 unit tests pinning buffer mechanics | VERIFIED | 11/11 PASS (run confirmed) |
| `frontend/src/hooks/use-ai-availability.ts` | Extended with `AIUnavailableReason` + `reason` field | VERIFIED | `export type AIUnavailableReason = 'env_disabled' | 'no_key' | 'permission'`; 4-branch derivation at lines 46-53 |
| `frontend/src/hooks/__tests__/use-ai-availability.test.tsx` | 5 new tests for reason branches | VERIFIED | 11/11 PASS including 5 Phase 1135 cases (run confirmed) |
| `frontend/src/components/builder/ChatPanel.tsx` | Staging tray + inline data card + error banner + viewport prop | VERIFIED | All four surfaces wired; `useChatActionStaging` at line 378; `errorBanner` state at line 170; `viewport?: ViewportContext` prop at line 135 |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | 9 new tests (AI-01/AI-08/AI-09 staging + card) + 4 tests (AI-03 banner) | VERIFIED | 35/35 PASS (run confirmed) |
| `frontend/src/components/builder/BuilderRail.tsx` | AIDisabledState component replacing plain-text fallback | VERIFIED | `AIDisabledState` function at line 26; BotOff import; 3-reason taxonomy; admin CTA via react-router Link |
| `frontend/src/components/builder/__tests__/BuilderRail.test.tsx` | 5 new AI-02 regression tests | VERIFIED | 13/13 PASS (run confirmed) |
| `frontend/src/components/builder/chat-suggestions.ts` | ViewportContext export + viewport-aware getSmartSuggestions | VERIFIED | `ViewportContext` interface at line 12; optional 3rd arg at line 40; priority logic at lines 49-57 |
| `frontend/src/components/builder/__tests__/chat-suggestions.test.ts` | 8 new AI-05 tests | VERIFIED | 16/16 PASS (run confirmed) |
| `frontend/src/pages/MapBuilderPage.tsx` | 500ms-debounced viewport state + railProps wiring | VERIFIED | `useState<ViewportContext>` at line 129; `mapInstance.on('idle')` at line 287; `viewport` in `railProps` useMemo at line 591 |
| `backend/app/processing/ai/router.py` | Pitfall #5 docstring on `_validate_chat_layers` | VERIFIED | Paragraph at lines 108-122; text contains "Pitfall #5", "visibility", "regardless" — docstring test PASS |
| `backend/app/processing/ai/sql_generator.py` | (map_id, content_hash) cache-key docstring anchor | VERIFIED | Module comment + `_schema_cache_key` docstring at lines 30-50 with Pitfall #5 cross-reference |
| `backend/tests/test_ai_chat_actions_phase1135.py` | 4 pure-Python regression tests | VERIFIED | 4/4 PASS (run confirmed) |
| `backend/app/processing/ai/chat_actions.py` | SF-MCP-01 fix — emit show_query_result with rows for non-spatial query_data | VERIFIED | `_collect_chat_action` at lines 241-257 emits `columns`, `rows`, `row_count`, `truncated` for all successful query_data; commit `4b643bde` |
| `backend/tests/test_collect_chat_action.py` | 5 regression tests for SF-MCP-01 fix | VERIFIED | 5/5 PASS (run confirmed) |
| i18n (en/de/es/fr builder.json) | 30 new keys across staging/queryResult/rail/chat.banner/suggestions namespaces | VERIFIED | 12 matches per locale (all 4 locales); all files are valid JSON |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `ChatPanel.tsx` | `chat-action-staging.ts useChatActionStaging` | import + hook call at line 378 | WIRED | `import { useChatActionStaging, isDestructiveAction }` at line 10; `staging = useChatActionStaging(...)` at line 378 |
| `ChatPanel.tsx` staging branch | `dispatchLayerAction` | `staging.push(action)` → `acceptAll/acceptOne` → `handleChatAction` | WIRED | Destructive actions enter staging buffer; `handleChatAction` is the injected dispatch at line 378; accept calls flush through it |
| `ChatPanel.tsx` | `getSmartSuggestions` | import + call with `viewport` 3rd arg at line 673 | WIRED | `import { getSmartSuggestions, type ViewportContext }` at line 14; called at `ChatPanel.tsx:673` |
| `BuilderRail.tsx` | `useAIAvailability` reason | import + `AIDisabledState` consumer | WIRED | `useAIAvailability()` at line 28 inside `AIDisabledState`; reason taxonomy branches at lines 40-58 |
| `ChatPanel.tsx` | errorBanner | `err.status === 403/503` → `setErrorBanner(...)` at lines 530-536 | WIRED | Banner rendered at lines 617-667 with sticky top-0; Retry and Dismiss wired correctly |
| `MapBuilderPage.tsx` | `BuilderRail viewport` | `railProps.viewport` spread | WIRED | `viewport` in `railProps` useMemo at line 591; both `BuilderRail` instances receive it via spread at lines 1419, 1440 |
| `BuilderRail.tsx` | `ChatPanel viewport` | prop forwarding | WIRED | `<ChatPanel ... viewport={viewport} />` verified by BuilderRail.tsx modification summary |
| `_collect_chat_action` | `show_query_result` rows | emit path at lines 241-257 | WIRED | `"rows": result.get("rows", [])` at line 249; gated on `"columns" in result and "error" not in result` |
| `BuilderActionSource` union | UNCHANGED | `git diff -- builder-action-contract.ts` | WIRED | `'manual' | 'ai' | 'system'` — zero 'ai-pending'/'ai-committed' matches outside staging module comment |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `ChatPanel.tsx` staging tray | `staging.pendingActions` | `useChatActionStaging` hook backed by `actionsRef` + `useState` | Yes — populated from AI response stream `add_layer`/`remove_layer` actions | FLOWING |
| `ChatPanel.tsx` inline data card | `show_query_result.rows` | `_collect_chat_action` → streaming response → `ChatAction.rows` | Yes — backend fix at `4b643bde` emits `rows` from `query_data` results | FLOWING |
| `BuilderRail.tsx` AIDisabledState | `reason` field | `useAIAvailability()` → `AIStatusResponse` + `usePermissions().can` | Yes — derives from real API response | FLOWING |
| `ChatPanel.tsx` error banner | `errorBanner` state | `ApiError.status` 403/503 catch in `handleSend` | Yes — set on real HTTP error codes | FLOWING |
| `MapBuilderPage.tsx` viewport | `viewport.zoom`, `viewport.bounds` | `mapInstance.getZoom()` + `mapInstance.getBounds()` on `idle` event | Yes — reads from live MapLibre instance (real browser only) | FLOWING (live browser only) |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| chat-action-staging: 11 unit tests | `npm test -- chat-action-staging.test.ts --run` | 11 passed | PASS |
| use-ai-availability: 11 tests (incl. 5 reason-branch) | `npm test -- use-ai-availability.test.tsx --run` | 11 passed | PASS |
| ChatPanel: 35 tests | `npm test -- ChatPanel.test.tsx --run` | 35 passed | PASS |
| BuilderRail: 13 tests | `npm test -- BuilderRail.test.tsx --run` | 13 passed | PASS |
| chat-suggestions: 16 tests | `npm test -- chat-suggestions.test.ts --run` | 16 passed | PASS |
| Backend AI-08 fix + docstring: 9 tests | `pytest test_collect_chat_action.py test_ai_chat_actions_phase1135.py` | 9 passed | PASS |
| BuilderActionSource no-widen | `grep -rn "'ai-pending'\|'ai-committed'" frontend/src` | 0 matches outside staging comment | PASS |

---

### Probe Execution

Step 7c: SKIPPED — no `probe-*.sh` files declared in phase plans; phase is frontend/AI-chat focused.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| AI-01 | Plans 01, 02 | Confirm-before-apply staging (Shape B) | VERIFIED | Staging module + ChatPanel wiring + 5 regression tests + live MCP PASS |
| AI-02 | Plans 01, 03 | AI_ENABLED=false actionable disabled state | VERIFIED | AIDisabledState + reason taxonomy + 5 BuilderRail tests + live MCP 8/8 PASS |
| AI-03 | Plan 03 | Invalid provider key → recoverable error banner | VERIFIED | errorBanner state + 403/503 routing + 4 ChatPanel tests PASS |
| AI-04 | Plan 05 | _validate_chat_layers visibility decision documented; cache key preserved | VERIFIED | Docstring at router.py:108-122; 4 Python tests PASS |
| AI-05 | Plan 04 | Viewport-aware suggestion chips | VERIFIED (unit) / human needed (interactive) | ViewportContext + getSmartSuggestions extension + 8 tests PASS; live zoom-aware chips require real browser |
| AI-08 | Plans 02, 06 + inline fix | Data-analysis inline card via show_query_result | VERIFIED (unit+backend) / human needed (live e2e) | Frontend card code + 4 unit tests PASS; SF-MCP-01 fix 4b643bde + 5 backend tests PASS; live query needs re-verification |
| AI-09 | Plan 02 | Action preview chips with verb+entity+position | VERIFIED | buildChipText helper + staging tray render + live MCP chip text PASS |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `BuilderRail.tsx` | 226-227 | `placeholder` attribute on textarea (notes) | Info | Pre-existing — this is the notes textarea, not a stub; placeholder is correct HTML |
| `ChatPanel.tsx` | 919 | `placeholder` attribute on compose input | Info | Pre-existing input placeholder — correct UX usage, not a stub indicator |

No `TBD`, `FIXME`, or `XXX` debt markers found in any phase-modified file.
No `return null` / `return {}` / `return []` stub patterns in phase-new code.
No direct `map.setPaintProperty` / `map.setLayoutProperty` calls in any phase-modified file.

---

### Hard Invariant Verification

| Invariant | Contract | Status |
|-----------|----------|--------|
| `BuilderActionSource` union UNCHANGED | `'manual' | 'ai' | 'system'` — no 'ai-pending', 'ai-committed' | VERIFIED — zero matches in grep sweep |
| `BuilderLayerAction` union UNCHANGED | dispatcher contract unchanged | VERIFIED — `git diff builder-action-contract.ts` empty (confirmed by all 6 plan SUMMARYs) |
| Reconciler unchanged | No side-effect gating added | VERIFIED — staging sits above dispatcher, not inside it |
| Shape B above dispatcher | `chat-action-staging.ts` is above `dispatchLayerAction` | VERIFIED — hook takes dispatch as function argument; no direct map calls |
| Pitfall #4 sibling-hook sweep | Every new AI hook gated `enabled: !!token && aiEnabled` | VERIFIED — `useAIStatus({ enabled: !!token && isAdmin })`; new `AIDisabledState` is the only new consumer; no new TanStack query hooks introduced |

---

### Human Verification Required

#### 1. Zoom-Aware Suggestion Chips at zoom >= 12

**Test:** Open http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2 in a real browser at 1440x900. Open the AI rail (empty state visible). Zoom to level 12 or higher (e.g. zoom to a town scale). Wait ~1 second, then close and reopen the AI chat panel to trigger chip refresh.
**Expected:** "Show nearby features in this area" chip appears in the suggestion list when at least one vector layer is present and zoom >= 12.
**Why human:** MapLibre idle event requires WebGL context. Headless Chromium fails with `webglcontextcreationerror` so `viewport` state never populates in automated testing. 8 unit tests cover the logic contract; live browser needed for the render path.

#### 2. Selected-Layer Summarize Chip

**Test:** Same map in real browser. Click a vector layer row in the layer stack to expand it (sets `expandedLayerId`). Wait ~1 second. Close and reopen the AI panel.
**Expected:** "Summarize @[layer name] attributes" chip appears as the first suggestion chip, referencing the expanded layer by name.
**Why human:** `selectedLayerName` propagates into `ViewportContext` via the `expandedLayerId` effect only after the map idle event fires. Same headless WebGL constraint as above.

#### 3. Inline Data-Analysis Card — Live End-to-End (AI-08 SF-MCP-01 fix)

**Test:** On the same map with a healthy AI-enabled stack, open the AI rail and send the message: "Show me the top 5 streams by length with their names as a table". Observe the assistant response.
**Expected:** The response area shows an inline table card with column headers and rows (stream names + lengths), not a plain markdown block of text. The card should have a row-count footer (e.g., "5 rows").
**Why human:** The SF-MCP-01 backend fix was applied at commit `4b643bde` after the Plan 06 smoke run. The 5 backend regression tests verify the `_collect_chat_action` emission. The 4 frontend unit tests verify card rendering with mocked rows. A live round-trip with the actual AI model + backend is required to confirm the complete chain works post-fix. (The STATE.md carry-forward note is stale — the fix is in the codebase and the tests pass.)

---

### Gaps Summary

No blockers. All 5 ROADMAP success criteria are satisfied in the codebase. The three human-verification items above are interactive/live-stack behaviors that automated checks cannot substitute for:

1. **SC-3 viewport chips** — unit-tested, code is wired, interactive render requires a real browser due to headless WebGL constraint. Not a code gap.
2. **SC-3 inline card live e2e** — backend fix is in place and tested; a live AI query is needed to confirm the complete path. Not a code gap.
3. These are standard "needs human" items for any AI-interactive feature — no gaps in the implementation.

The STATE.md line "SF-MCP-01 carry-forward to Phase 1139" was written at Plan 06 time. Commit `4b643bde` subsequently fixed the issue within the Phase 1135 commit history. The VERIFICATION context explicitly instructs to treat this as a Phase 1135 deliverable.

---

_Verified: 2026-05-27T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
