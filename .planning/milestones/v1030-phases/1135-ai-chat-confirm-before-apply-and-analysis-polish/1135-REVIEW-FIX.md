---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
fixed_at: 2026-05-27T15:55:00Z
review_path: .planning/phases/1135-ai-chat-confirm-before-apply-and-analysis-polish/1135-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 1135: Code Review Fix Report

**Fixed at:** 2026-05-27T15:55:00Z
**Source review:** `.planning/phases/1135-ai-chat-confirm-before-apply-and-analysis-polish/1135-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 8
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: Non-Streaming Fallback Bypasses Staging

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`
**Commit:** d38bc635
**Applied fix:** In the non-streaming fallback action loop (previously lines 562-572), added `if (isDestructiveAction(action)) { staging.push(action); continue; }` guard before `handleChatAction`. Destructive actions now route through the staging buffer in the fallback path, matching the streaming loop's behavior. The `cleanStaleLayerRefs` duplicate that was in the old fallback loop was also removed (cleanup handled inside `handleChatAction` via CR-02).

---

### CR-02: `cleanStaleLayerRefs` Never Called for Staged `remove_layer` Actions

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`
**Commit:** 4a4f6b9f
**Applied fix:** Moved `cleanStaleLayerRefs(mapId, layerId)` inside `handleChatAction`'s `case 'remove_layer':` branch (after `onRemove(layerId)`). Removed the now-redundant call from the streaming loop (lines 469-473). Also updated the misleading comment at line 373-377 to accurately describe the accept path (see IN-03 below — this comment fix was folded into this commit).

---

### WR-01: `buildChipText` Sort Direction Produces Wrong Reference Layer

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`
**Commit:** bc630394
**Applied fix:** Changed `layers.slice().sort((a, b) => b.sort_order - a.sort_order)` to `(a, b) => a.sort_order - b.sort_order` (ascending). `sorted[0]` is now the topmost layer (lowest `sort_order`) rather than the bottom-most layer.

---

### WR-02: `hasPaintMutation` Returns `false` for `replace_paint=true` with Empty/No `paint`

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`
**Commit:** bc381576
**Applied fix:** Changed the third clause of `hasPaintMutation` from `(action.replace_paint === true && paint)` to `(action.replace_paint === true)`. The `replace_paint` intent is sufficient without requiring a non-null/non-empty `paint` object, since `buildChatActionPaint` with `replace_paint=true` starts from `{}` and a wipe-all is a meaningful map mutation.

---

### WR-03: 403/503 from Non-Streaming Fallback Shows Inline Bubble, Not Sticky Banner

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`, `frontend/src/components/builder/__tests__/ChatPanel.test.tsx`
**Commits:** 03bd251c (fix), 90c8b711 (test update)
**Applied fix:** Wrapped the fallback `catch (fallbackErr)` body with a `if (fallbackErr instanceof ApiError && (status === 403 || status === 503))` branch that calls `setErrorBanner(...)` — matching the streaming path. The else branch retains the existing inline bubble for all other errors. The existing test `'shows specific error for ApiError status $status via fallback'` was updated: the 403/503 cases were split into a new `it.each` block (`WR-03: ApiError status $status via fallback routes to sticky banner, not inline bubble`) that asserts `role="alert"` banner presence rather than inline text matching. Test count unchanged (4 cases total, same as before).

---

### IN-01: Duplicate Mention-Format Logic in `chat-suggestions.ts`

**Files modified:** `frontend/src/components/builder/chat-suggestions.ts`
**Commit:** 14bc84e7
**Applied fix:** `mentionName` now delegates to `formatLayerNameForMention`: `return formatLayerNameForMention(layer.display_name ?? layer.dataset_name)`. Both functions are `function` declarations so hoisting is safe despite `formatLayerNameForMention` appearing after `mentionName` in the file.

---

### IN-02: `rows[0]` Used Without Null Guard in Inline Data Card

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`
**Commit:** 146bf721
**Applied fix:** Replaced `const firstRow = rows[0] as Record<string, unknown>; const allColumns = Object.keys(firstRow);` with a null/non-object guard: `const firstRow = rows[0]; if (!firstRow || typeof firstRow !== 'object') return null; const allColumns = Object.keys(firstRow as Record<string, unknown>);`.

---

### IN-03: Misleading Comment — `handleChatAction` Described as Firing `cleanStaleLayerRefs` and Snapshot Logic

**Files modified:** `frontend/src/components/builder/ChatPanel.tsx`
**Commit:** 4a4f6b9f (folded into CR-02 commit)
**Applied fix:** The misleading comment at line 373-377 was rewritten as part of the CR-02 commit (which was the natural place since CR-02 moved `cleanStaleLayerRefs` into `handleChatAction`). The new comment accurately states: accepts route through `handleChatAction` only for the map mutation itself; `cleanStaleLayerRefs` is called inside `handleChatAction`'s `remove_layer` case; the undo snapshot is captured in `handleSend` before `push()`, not inside `acceptAll`/`acceptOne`.

---

_Fixed: 2026-05-27T15:55:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
