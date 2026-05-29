---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
plan: "02"
subsystem: frontend/builder/ai
tags:
  - builder
  - ai
  - chat-ui
  - staging
  - i18n
dependency_graph:
  requires:
    - "frontend/src/builder/ai/chat-action-staging.ts (Plan 01 — useChatActionStaging, isDestructiveAction)"
    - "frontend/src/types/api.ts (ChatAction, MapLayerResponse)"
    - "frontend/src/i18n/locales/{en,de,es,fr}/builder.json"
  provides:
    - "frontend/src/components/builder/ChatPanel.tsx (staging tray, inline data card, chip-text helper)"
    - "frontend/src/components/builder/__tests__/ChatPanel.test.tsx (9 new tests covering AI-01/AI-08/AI-09)"
  affects:
    - "Plans 03-04: BuilderRail disabled-state, error banner, viewport chips"
tech_stack:
  added:
    - "Lucide Plus, Trash2 icons (new imports to ChatPanel)"
  patterns:
    - "isDestructiveAction branch in actions event — stage vs direct-dispatch gate"
    - "staging.rejectAll() auto-clear on new handleSend (per UI-SPEC line 143)"
    - "buildChipText helper — translator + layers → { text, fullText } tuple"
    - "IIFE inline table card render inside assistant bubble (show_query_result rows)"
key_files:
  created: []
  modified:
    - frontend/src/components/builder/ChatPanel.tsx
    - frontend/src/components/builder/__tests__/ChatPanel.test.tsx
    - frontend/src/types/api.ts
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "buildChipText uses translator: typeof t (narrowed from useTranslation) not generic TFunction<string> — avoids TS2345 namespace mismatch"
  - "Per-chip Accept button aria-label includes full chip text for accessibility — tests use textContent filter instead of name regex to avoid matching 'Accept all'"
  - "Python json.dump used to write locale files — avoids smart-quote corruption from Edit tool's text processing; preserves 2-space indent"
  - "Inline data card Task 2 merged into Task 1 commit — both modify ChatPanel.tsx, no separate commit needed"
  - "Existing remove_layer undo test updated to use staging accept flow — destructive actions now require user confirmation before dispatch"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-27"
  tasks_completed: 3
  files_created: 0
  files_modified: 7
---

# Phase 1135 Plan 02: ChatPanel Staging Tray + Inline Data Card + i18n — Summary

**One-liner:** Surface 1 chip tray wired to useChatActionStaging (destructive actions stage, not immediate), Surface 2 inline table card for show_query_result rows, buildChipText helper, 12 i18n keys in 4 locales, 9 new tests; BuilderActionSource UNCHANGED.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ChatPanel — integrate useChatActionStaging + Surface 1 staging tray | `6dbc47b7` | ChatPanel.tsx, api.ts, en/de/es/fr builder.json |
| 2 | ChatPanel — Surface 2 inline data-analysis card | `6dbc47b7` | ChatPanel.tsx (merged into Task 1) |
| 3 | ChatPanel test extensions (AI-01/AI-08/AI-09) | `97bcd083` | ChatPanel.test.tsx |

## Implementation Details

### ChatPanel.tsx Integration (~165 LOC added)

**Imports added:**
- `Plus`, `Trash2` from lucide-react (verb icons for staging chips)
- `useChatActionStaging`, `isDestructiveAction` from `@/builder/ai/chat-action-staging`

**Changes in the `actions` event handler (lines ~420-470):**

Old path: every action → `handleChatAction(action)` immediately.

New path:
```
show_query_result → dispatchQueryResult (existing flyover) + pendingActions.push
isDestructiveAction → staging.push(action) + pendingActions.push (for message display)
else → handleChatAction(action) (unchanged immediate path)
```

Snapshot bookkeeping now only fires for non-destructive immediately-dispatched actions (snapshot for staging-accepted actions fires naturally inside `handleChatAction` at accept time).

**handleSend auto-reject (1 line added at top of handleSend):**
```ts
if (staging.pendingActions.length > 0) staging.rejectAll();
```

**buildChipText helper (~35 LOC):**

| Action | Layers available | Output |
|--------|-----------------|--------|
| `add_layer` with topmost layer | layers[0] exists | `Add "NYC Subway" below "Counties"` |
| `add_layer` no reference | no layers | `Add "NYC Subway"` |
| `remove_layer` with feature count | matched layer has dataset_feature_count | `Remove "Boroughs" (5 features)` |
| `remove_layer` no count | matched layer or layer_id fallback | `Remove "Boroughs"` |

Text truncated at 60 chars; full text in `title` attribute.

**Staging tray render (~55 LOC):**
- Outer container: `border border-border rounded-lg bg-muted/30 p-2 space-y-1`
- Header: count using `t('chat.staging.header', { count: N })` with pluralization
- Accept all / Reject all buttons (primary / outline-destructive)
- Per-chip list: VerbIcon + chip text + Accept + Reject buttons
- List gets `max-h-40 overflow-y-auto` when > 4 chips
- Undo button suppressed via `staging.pendingActions.length === 0` gate

**Inline data card render (~50 LOC inside the assistant bubble):**
- IIFE block finds `show_query_result` action with non-null `rows` array
- `rows === null` (no rows field) → no card (existing flyover-only path preserved)
- `rows.length === 0` → empty-state with `chat.queryResult.empty` + `chat.queryResult.emptyHint`
- Non-empty rows → `<table class="table-fixed">` with `max-h-48` scroll wrapper
- 5-column cap with `…` header cell (`aria-label="more columns"`) when overflow
- Row values coerced via `String(raw)` with `title={display}` for truncated cells
- Footer: `t('chat.queryResult.rowCount', { count: rows.length })`

### api.ts additions (additive only)
```ts
dataset_name?: string;   // carried on add_layer actions from backend
rows?: Record<string, unknown>[];  // tabular result rows on show_query_result
```
No BuilderActionSource widening. No new ChatAction type variants.

### 12 New i18n Keys

All 4 locales (en/de/es/fr) updated with identical English stub values (parity-script compliant):

| Key path | Default (en) |
|----------|-------------|
| `chat.staging.header_one` | `"{{count}} pending change — review before applying"` |
| `chat.staging.header_other` | `"{{count}} pending changes — review before applying"` |
| `chat.staging.acceptAll` | `"Accept all"` |
| `chat.staging.rejectAll` | `"Reject all"` |
| `chat.staging.accept` | `"Accept"` |
| `chat.staging.reject` | `"Reject"` |
| `chat.staging.chipAdd` | `"Add \"{{name}}\""` |
| `chat.staging.chipAddBelow` | `"Add \"{{name}}\" below \"{{ref}}\""` |
| `chat.staging.chipRemove` | `"Remove \"{{name}}\""` |
| `chat.staging.chipRemoveFeatures_one` | `"Remove \"{{name}}\" ({{count}} feature)"` |
| `chat.staging.chipRemoveFeatures_other` | `"Remove \"{{name}}\" ({{count}} features)"` |
| `chat.queryResult.empty` | `"The AI query returned no rows."` |
| `chat.queryResult.emptyHint` | `"Try a broader area or different filter."` |
| `chat.queryResult.tableLabel` | `"Query result table"` |
| `chat.queryResult.rowCount_one` | `"{{count}} row"` |
| `chat.queryResult.rowCount_other` | `"{{count}} rows"` |

Note: 12 keys required, 16 written (header_one/header_other + chipRemoveFeatures_one/other + rowCount_one/other count as pluralization pairs). i18n parity test: 2/2 PASS.

### 9 New Vitest Cases (RED→GREEN)

All 9 tests passed after implementation. No RED phase required separately — implementation and tests written in same pass.

**AI-01 / AI-09 staging describe block (5 tests):**

| # | Test | Status |
|---|------|--------|
| 1 | reject-all leaves onAddDataset + onRemove UNCALLED | PASS |
| 2 | acceptOne dispatches exactly ds-A, leaves ds-B chip | PASS |
| 3 | acceptAll dispatches 3 actions in order (ds-A, ds-C, layer-1 remove) | PASS |
| 4 | chip text format: Add "NYC Subway" + Remove "Counties" (5 features) | PASS |
| 5 | set_style negative control: no tray, onPaintChange called directly | PASS |

**AI-08 inline card describe block (4 tests):**

| # | Test | Status |
|---|------|--------|
| 1 | rows present: Essex + Hamilton render in table | PASS |
| 2 | rows=[]: empty state "no rows" + "broader area" text | PASS |
| 3 | 7-column row: 5 visible headers + … indicator | PASS |
| 4 | geojson+bbox only: onQueryResult called, no inline card | PASS |

## Verification Results

```
✓ npm test -- ChatPanel.test.tsx chat-action-staging.test.ts --run
  Test Files: 2 passed (2)
  Tests: 42 passed (42)

✓ npm run typecheck
  exit 0 (clean)

✓ npm run test:i18n
  Tests: 2 passed (2)

✓ git diff -- frontend/src/components/builder/builder-action-contract.ts
  EMPTY — BuilderActionSource union UNCHANGED

✓ grep -rnE "'ai-pending'|'ai-committed'" frontend/src --include="*.ts*"
  Zero matches outside chat-action-staging.ts comment
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python json.dump used for locale files to avoid smart-quote corruption**
- **Found during:** Task 1 i18n key insertion
- **Issue:** The Edit tool's text processing converted ASCII `"` to U+201C/U+201D smart quotes in the new JSON key-value pairs, making the locale files invalid JSON (Node.js JSON.parse throws "Expected double-quoted property name").
- **Fix:** Reverted all 4 locale files via `git checkout` then used Python's `json.dump` with `ensure_ascii=False` to programmatically insert the new keys, guaranteeing clean ASCII quotes throughout.
- **Files modified:** en/de/es/fr builder.json
- **Commit:** `6dbc47b7`

**2. [Rule 1 - Bug] Existing `remove_layer` undo test updated for staging flow**
- **Found during:** Task 3 test run (1 failing test)
- **Issue:** The pre-existing test `does not offer undo for remove_layer actions` sent a `remove_layer` action and immediately expected `onRemove` to have been called. With Phase 1135 staging, `remove_layer` goes into the staging buffer — it does NOT dispatch until the user accepts. Test failed with `expect(onRemove).toHaveBeenCalledWith('layer-1')` never satisfying.
- **Fix:** Updated the test to click "Accept all" before asserting `onRemove` was called. The undo assertion (no undo button for remove_layer) still holds after accepting.
- **Files modified:** ChatPanel.test.tsx
- **Commit:** `97bcd083`

**3. [Rule 1 - Bug] Per-chip Accept button test query fixed from `/^accept$/i` to textContent filter**
- **Found during:** Task 3 test run (1 failing test)
- **Issue:** The plan's suggested test used `findAllByRole('button', { name: /^accept$/i })` to find per-chip Accept buttons. The actual buttons have `aria-label="Accept Add \"A\" below \"Test Dataset\""` (full action text), so the exact regex found 0 matches. Additionally, using `/^accept /i` matched 3 buttons (2 per-chip + 1 "Accept all").
- **Fix:** Wait for tray to render, then filter all buttons by `textContent?.trim() === 'Accept'` to get only the per-chip Accept buttons (not "Accept all" which has text "Accept all").
- **Files modified:** ChatPanel.test.tsx
- **Commit:** `97bcd083`

**4. [Rule 1 - Bug] `.mock.calls` TypeScript error on renderPanel return type**
- **Found during:** Task 3 typecheck
- **Issue:** `props.onAddDataset.mock.calls` fails with TS2339 because `renderPanel()` returns a union type `((datasetId: string) => void) | Mock<Procedure>`. TypeScript cannot narrow the union to `Mock`.
- **Fix:** Used `(props.onAddDataset as any).mock.calls as [string][]` with explicit cast + comment. This is in test code only.
- **Files modified:** ChatPanel.test.tsx
- **Commit:** `97bcd083`

## BuilderActionSource Unchanged Confirmation

```
git diff -- frontend/src/components/builder/builder-action-contract.ts
(empty)
```

`BuilderActionSource = 'manual' | 'ai' | 'system'` — byte-equal to pre-plan state.
No 'ai-pending', no 'ai-committed', no new union members. v1030 hard invariant #5 holds.

## Cross-References

- CONTEXT.md Shape B lock: D-Shape-B (Pitfall #3 NON-NEGOTIABLE) — satisfied
- UI-SPEC Surface 1 (lines 94-151): staging tray layout, chip format — implemented
- UI-SPEC Surface 2 (lines 154-209): inline data card — implemented  
- UI-SPEC Regression Test Contracts (lines 468-476) — 9 new tests cover all listed contracts
- Phase 1135-01-SUMMARY.md: chat-action-staging.ts foundation
- ROADMAP AI-01: confirm-before-apply staging — closed by this plan (5 regression tests pin the contract)
- ROADMAP AI-08: inline data-analysis card — closed by this plan (4 tests pin the contract)
- ROADMAP AI-09: action preview chips — closed by this plan (chip-text test pins the format)

## Self-Check

**Files exist:**
- `frontend/src/components/builder/ChatPanel.tsx`: FOUND
- `frontend/src/components/builder/__tests__/ChatPanel.test.tsx`: FOUND
- `frontend/src/i18n/locales/en/builder.json`: FOUND (modified)
- `frontend/src/i18n/locales/de/builder.json`: FOUND (modified)
- `frontend/src/i18n/locales/es/builder.json`: FOUND (modified)
- `frontend/src/i18n/locales/fr/builder.json`: FOUND (modified)

**Commits exist:**
- `6dbc47b7`: FOUND
- `97bcd083`: FOUND

## Self-Check: PASSED
