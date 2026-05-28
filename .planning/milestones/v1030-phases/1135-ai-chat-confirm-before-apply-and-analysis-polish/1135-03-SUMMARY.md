---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
plan: "03"
subsystem: frontend/builder/ai
tags:
  - builder
  - ai
  - rail
  - error-handling
dependency_graph:
  requires:
    - "frontend/src/hooks/use-ai-availability.ts (Plan 01 — reason field, AIUnavailableReason)"
    - "frontend/src/components/builder/ChatPanel.tsx (Plan 02 — staging tray, existing error bubble)"
    - "frontend/src/i18n/locales/{en,de,es,fr}/builder.json"
  provides:
    - "frontend/src/components/builder/BuilderRail.tsx (AIDisabledState — structured disabled-state UI)"
    - "frontend/src/components/builder/ChatPanel.tsx (errorBanner state — sticky 403/503 banner)"
    - "frontend/src/components/builder/__tests__/BuilderRail.test.tsx (5 AI-02 regression tests)"
    - "frontend/src/components/builder/__tests__/ChatPanel.test.tsx (4 AI-03 regression tests)"
  affects:
    - "Plans 04-06: viewport-aware suggestions, backend docstring, Playwright smoke"
tech_stack:
  added:
    - "Lucide BotOff icon (new import to BuilderRail)"
    - "react-router Link import to BuilderRail (AIDisabledState CTA)"
    - "Button import to BuilderRail (AIDisabledState CTA button)"
  patterns:
    - "AIDisabledState sub-component reads useAIAvailability internally — TanStack deduplicates"
    - "errorBanner state with 'forbidden' | 'unavailable' kind union — route 403/503 to banner, 401/502/network to inline bubble"
    - "setErrorBanner(null) on 'done' event + non-streaming success auto-clears banner"
key_files:
  created: []
  modified:
    - frontend/src/components/builder/BuilderRail.tsx
    - frontend/src/components/builder/__tests__/BuilderRail.test.tsx
    - frontend/src/components/builder/ChatPanel.tsx
    - frontend/src/components/builder/__tests__/ChatPanel.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - "AIDisabledState reads useAIAvailability internally (not passed as prop) — TanStack deduplicates so no extra network request vs parent's isAIAvailable derivation"
  - "t() calls in AIDisabledState include defaultValue to work with the test mock pattern (consistent with existing BuilderRail t() calls)"
  - "Import from 'react-router' not 'react-router-dom' — project uses react-router v7 directly (per MapCard.tsx, MapCreateDialog.tsx precedent)"
  - "BuilderRail.test.tsx switched from @testing-library/react render to @/test/test-utils render — required for MemoryRouter context since AIDisabledState renders Link"
  - "Old test 'opens an AI unavailable panel without mounting ChatPanel' updated: mocks reason='env_disabled' so it tests the new structured disabled-state (title 'AI is disabled') instead of the removed plain-text fallback"
  - "403 streaming errors routed to banner only — the existing mapApiErrorToMessage 403 branch in the inline error bubble path becomes unreachable for new streaming errors but is preserved as defensive fallback for non-streaming path"
  - "401 test uses unambiguous input 'test-auth-401' to avoid the user message text matching the /expired/i regex"
metrics:
  duration: "~7 minutes"
  completed: "2026-05-27"
  tasks_completed: 2
  files_created: 0
  files_modified: 8
---

# Phase 1135 Plan 03: BuilderRail Disabled-State + ChatPanel Error Banner + 14 i18n Keys — Summary

**One-liner:** Structured disabled-state (AIDisabledState + BotOff icon + 3-reason taxonomy + admin CTA) in BuilderRail + sticky 403/503 recoverable-error banner (Retry/Dismiss) in ChatPanel; 14 new i18n keys in 4 locales; 9 regression tests close AI-02 and AI-03.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | BuilderRail structured disabled-state with reason taxonomy + AI-02 regression tests | `87103e4c` | BuilderRail.tsx, BuilderRail.test.tsx, en/de/es/fr builder.json |
| 2 | ChatPanel sticky recoverable-error banner for 403/503 + AI-03 regression tests | `2ed2ecf7` | ChatPanel.tsx, ChatPanel.test.tsx |

## Artifact Details

### Task 1: AIDisabledState component in BuilderRail.tsx

**New component:** `AIDisabledState` (local, before the `BuilderRail` export)

Consumes `useAIAvailability()` + `useAuthStore(s => s.isAdmin())`. Branches on `reason`:

| reason | Title | Body | CTA |
|--------|-------|------|-----|
| `env_disabled` | "AI is disabled" | "An administrator has disabled AI for this instance." | "Go to Settings" (admin only) |
| `no_key` | "AI not configured" | "A provider API key is required before AI chat can be used." | "Configure in Settings" (admin only) |
| `permission` | "AI unavailable" | "You don't have permission to use AI chat." | None |
| `null` / loading | Spinner only | — | — |

Container: `flex h-full flex-col items-center justify-center gap-3 p-6 text-sm` with `role="status" aria-live="polite"` and `data-ai-reason={reason}`.

**Replaced block:** Lines 170-181 plain-text disabled-state replaced with `{activePanel === 'ai' && !aiAvailable && <AIDisabledState />}`.

**New imports added to BuilderRail.tsx:**
- `BotOff` from lucide-react
- `Link` from `'react-router'` (project uses react-router v7, NOT react-router-dom)
- `Button` from `@/components/ui/button`
- `useAIAvailability` from `@/hooks/use-ai-availability`
- `useAuthStore` from `@/stores/auth-store`

**5 regression tests (AI-02):**

| # | Test | Status |
|---|------|--------|
| 1 | reason=env_disabled + isAdmin → "AI is disabled" title + "Go to Settings" link | PASS |
| 2 | reason=env_disabled + NOT admin → "AI is disabled" title, NO CTA link | PASS |
| 3 | reason=no_key + isAdmin → "AI not configured" title + "Configure in Settings" link | PASS |
| 4 | reason=permission + isAdmin → "AI unavailable" (data-ai-reason scoped), NO link | PASS |
| 5 | isLoading=true → spinner rendered (no title/body) | PASS |

**Updated existing test:** "opens an AI unavailable panel without mounting ChatPanel" now mocks `reason='env_disabled'` and checks for "AI is disabled" (new structured copy) instead of the removed plain-text "AI is unavailable".

### Task 2: ChatPanel error banner

**New state:** `errorBanner: { kind: 'forbidden' | 'unavailable'; retryMessage: string } | null`

**Error routing:**
- `err.status === 403` → `setErrorBanner({ kind: 'forbidden', retryMessage: userMsg })` — banner with Dismiss only
- `err.status === 503` → `setErrorBanner({ kind: 'unavailable', retryMessage: userMsg })` — banner with Retry button
- `err.status === 401` → existing inline error bubble (unchanged)
- `err.status === 502` → existing inline error bubble (unchanged)
- network/unknown errors → existing inline error bubble (unchanged)

**Banner render:** First child of `role="log"` div. Sticky at top: `sticky top-0 z-10`. Role: `role="alert" aria-live="assertive"`.

**Auto-clear:** `setErrorBanner(null)` fires on streaming `'done'` event AND on non-streaming `sendChatMessage` success response.

**4 regression tests (AI-03):**

| # | Test | Status |
|---|------|--------|
| 1 | 503 → banner with "AI is unavailable" + Retry; Retry re-fills input + clears banner | PASS |
| 2 | 403 → banner with "AI access lost" + Dismiss; NO Retry anywhere; Dismiss clears banner | PASS |
| 3 | 401 → NO banner; inline error bubble shows "please log in again" (negative control) | PASS |
| 4 | network error → NO banner; inline error bubble shows generic error (negative control) | PASS |

### 14 New i18n Keys (4 locales: en/de/es/fr)

**8 rail.* keys (Task 1):**

| Key | en default |
|-----|-----------|
| `rail.aiDisabledTitle` | "AI is disabled" |
| `rail.aiDisabledBody` | "An administrator has disabled AI for this instance." |
| `rail.aiNoKeyTitle` | "AI not configured" |
| `rail.aiNoKeyBody` | "A provider API key is required before AI chat can be used." |
| `rail.aiPermissionTitle` | "AI unavailable" |
| `rail.aiPermissionBody` | "You don't have permission to use AI chat." |
| `rail.aiGoToSettings` | "Go to Settings" |
| `rail.aiConfigureSettings` | "Configure in Settings" |

**6 chat.banner* keys (Task 2):**

| Key | en default |
|-----|-----------|
| `chat.bannerForbiddenTitle` | "AI access lost" |
| `chat.bannerForbiddenBody` | "You no longer have permission to use AI chat. Contact your administrator to restore access." |
| `chat.bannerUnavailableTitle` | "AI is unavailable" |
| `chat.bannerUnavailableBody` | "The AI service is temporarily unavailable. Try again in a moment." |
| `chat.bannerRetry` | "Retry" |
| `chat.bannerDismiss` | "Dismiss" |

## Verification Results

```
✓ cd frontend && npm test -- BuilderRail ChatPanel --run
  Test Files: 2 passed (2)
  Tests: 48 passed (48)
  (13 BuilderRail: 8 original + 5 new AI-02)
  (35 ChatPanel: 31 original + 4 new AI-03)

✓ cd frontend && npm run typecheck
  exit 0 (clean)

✓ cd frontend && npm run test:i18n
  Tests: 2 passed (2) — 4-locale parity holds with 14 new keys

✓ git diff -- frontend/src/components/builder/builder-action-contract.ts
  EMPTY — BuilderActionSource union UNCHANGED (Pitfall #3 protection)

✓ grep -rnE "'ai-pending'|'ai-committed'" frontend/src --include="*.ts*"
  Zero matches outside chat-action-staging.ts comment
```

## Pitfall #4 Sibling-Hook Sweep Re-Verification

`grep -rn "useAIAvailability\b" frontend/src --include="*.tsx" --include="*.ts" | grep -v __tests__ | grep -v use-ai-availability.ts`

**Consumers post-plan (10 files → 12 matches, up from 10 pre-plan):**
1. `MapCreateDialog.tsx` — `isAIAvailable` destructure (unchanged)
2. `OverviewTab.tsx` — `isAIAvailable` destructure (unchanged)
3. `MetadataTab.tsx` — `isAIAvailable` destructure (unchanged)
4. `SourceQualityTab.tsx` — `isAIAvailable` destructure (unchanged)
5. `MapBuilderPage.tsx` — `isAIAvailable` destructure (unchanged)
6. **`BuilderRail.tsx` (NEW)** — 3 new references: import line + JSDoc comment + `useAIAvailability()` call in `AIDisabledState`

`AIDisabledState` is the **only new consumer** this plan adds. It calls `useAIAvailability()` which already uses the composite gate `enabled: !!token && isAdmin`. No new `useAIStatus` or `useEmbeddingStats` direct consumers were introduced. The v1010.2 SF-06 recurrence guard holds.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] react-router-dom → react-router import correction**
- **Found during:** Task 1 GREEN phase (test run — "Failed to resolve import 'react-router-dom'")
- **Issue:** Plan spec said `import { Link } from 'react-router-dom'`, but the project uses `react-router` v7 directly (not react-router-dom). All existing Link imports in the project use `from 'react-router'` (MapCard.tsx, MapCardGrid.tsx, RegisterForm.tsx, etc.)
- **Fix:** Changed import to `from 'react-router'`
- **Files modified:** `BuilderRail.tsx`
- **Commit:** `87103e4c`

**2. [Rule 1 - Bug] t() calls must include defaultValue for test mock compatibility**
- **Found during:** Task 1 GREEN phase (tests returned key strings instead of translated text)
- **Issue:** `AIDisabledState` used bare `t(titleKey)` calls. The test file's `react-i18next` mock returns `options?.defaultValue ?? _key`, so without `defaultValue`, the key string is rendered (`rail.aiDisabledTitle`) rather than "AI is disabled".
- **Fix:** Added `defaultValue` to each `t()` call in `AIDisabledState`, consistent with existing BuilderRail pattern
- **Files modified:** `BuilderRail.tsx`
- **Commit:** `87103e4c`

**3. [Rule 3 - Blocking] BuilderRail.test.tsx switched to test-utils render**
- **Found during:** Task 1 GREEN phase (router context error from Link component)
- **Issue:** BuilderRail.test.tsx was importing `render` from `@testing-library/react` which doesn't provide `MemoryRouter`. The new `AIDisabledState` renders `<Link>` which requires router context.
- **Fix:** Changed import to `render` from `@/test/test-utils` (which wraps with MemoryRouter + QueryClient). All 8 existing tests continue to pass — they don't require any router-specific behavior.
- **Files modified:** `BuilderRail.test.tsx`
- **Commit:** `87103e4c`

**4. [Rule 1 - Bug] Updated existing test for new disabled-state behavior**
- **Found during:** Task 1 GREEN phase (1 existing test failing)
- **Issue:** Test "opens an AI unavailable panel without mounting ChatPanel" checked for the OLD plain-text "AI is unavailable". The replacement `AIDisabledState` renders a spinner when `reason=null` (the default mock value) — no text content.
- **Fix:** Added a per-test spy `reason='env_disabled'` so the test exercises the new structured state and checks for "AI is disabled" (the new title). The test's core assertion — that `ChatPanel` is NOT mounted when AI is unavailable — is preserved.
- **Files modified:** `BuilderRail.test.tsx`
- **Commit:** `87103e4c`

**5. [Rule 1 - Bug] 401 test used ambiguous input text**
- **Found during:** Task 2 GREEN phase (401 test failed with "Found multiple elements with /expired/i")
- **Issue:** Test typed "expired session" as user input. The user message text "expired session" matched the `/expired/i` regex used to find the inline error bubble — causing `findByText` to match both the user message and the error text.
- **Fix:** Changed input text to `'test-auth-401'` (no overlap with error text) and used a more specific regex `/please log in again|session expired\. please/i` matching the i18n value `t('chat.errorSessionExpired')`.
- **Files modified:** `ChatPanel.test.tsx`
- **Commit:** `2ed2ecf7`

## BuilderActionSource Unchanged Confirmation

```
git diff -- frontend/src/components/builder/builder-action-contract.ts
(empty)
```

`BuilderActionSource = 'manual' | 'ai' | 'system'` — byte-equal to pre-plan state.
No 'ai-pending', no 'ai-committed', no new union members. v1030 hard invariant #5 holds.

## Cross-References

- UI-SPEC Surface 3 (lines 212-272): disabled-state reason taxonomy — implemented
- UI-SPEC Surface 4 (lines 274-330): recoverable error banner — implemented
- ROADMAP AI-02: `AI_ENABLED=false` produces actionable disabled state — CLOSED by this plan
- ROADMAP AI-03: invalid provider key (403/503) surfaces recoverable banner — CLOSED by this plan
- Phase 1133-01-SUMMARY.md: AI consumer-gating matrix (enabled: !!token && isAdmin)
- v1010.2 SF-06 recurrence guard: AIDisabledState only new consumer, composite gate from Plan 01 preserved
- Phase 1135-01-SUMMARY.md: reason field foundation (AIUnavailableReason, use-ai-availability.ts)
- Phase 1135-02-SUMMARY.md: ChatPanel staging tray (Plans 01-02 dependency chain complete)

## Self-Check

**Files exist:**
- `frontend/src/components/builder/BuilderRail.tsx`: FOUND (modified)
- `frontend/src/components/builder/__tests__/BuilderRail.test.tsx`: FOUND (modified)
- `frontend/src/components/builder/ChatPanel.tsx`: FOUND (modified)
- `frontend/src/components/builder/__tests__/ChatPanel.test.tsx`: FOUND (modified)
- `frontend/src/i18n/locales/en/builder.json`: FOUND (modified — 14 new keys)
- `frontend/src/i18n/locales/de/builder.json`: FOUND (modified)
- `frontend/src/i18n/locales/es/builder.json`: FOUND (modified)
- `frontend/src/i18n/locales/fr/builder.json`: FOUND (modified)

**Commits exist:**
- `87103e4c`: FOUND
- `2ed2ecf7`: FOUND

## Self-Check: PASSED
