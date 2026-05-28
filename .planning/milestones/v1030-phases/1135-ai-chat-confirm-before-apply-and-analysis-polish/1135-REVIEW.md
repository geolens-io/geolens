---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
reviewed: 2026-05-27T00:00:00Z
depth: deep
files_reviewed: 10
files_reviewed_list:
  - frontend/src/builder/ai/chat-action-staging.ts
  - frontend/src/components/builder/ChatPanel.tsx
  - frontend/src/components/builder/BuilderRail.tsx
  - frontend/src/components/builder/chat-suggestions.ts
  - frontend/src/hooks/use-ai-availability.ts
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/types/api.ts
  - backend/app/processing/ai/chat_actions.py
  - backend/app/processing/ai/router.py
  - backend/app/processing/ai/sql_generator.py
findings:
  critical: 2
  warning: 3
  info: 3
  total: 8
status: issues_found
---

# Phase 1135: Code Review Report

**Reviewed:** 2026-05-27
**Depth:** deep
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 1135 introduces the Shape B staging buffer for destructive AI chat actions (add_layer/remove_layer), a per-reason disabled-state UI for the AI rail, a sticky error banner for service-level errors, an inline data card for non-spatial query results, and viewport-aware suggestion chips. The Shape B invariant (no BuilderActionSource widening) is correctly preserved by `chat-action-staging.ts`. The backend AI-08 fix correctly emits `show_query_result` for non-spatial query results.

Two blockers were found: the non-streaming fallback path bypasses the staging buffer entirely, applying destructive actions without user confirmation; and `cleanStaleLayerRefs` is never called when a staged `remove_layer` action is accepted. Three warnings cover error-handling inconsistency, a wrong sort direction in chip text, and a predicate logic error in `hasPaintMutation`.

---

## Critical Issues

### CR-01: Non-Streaming Fallback Bypasses Staging — Destructive Actions Applied Without Confirmation

**File:** `frontend/src/components/builder/ChatPanel.tsx:562-573`

**Issue:** The non-streaming fallback path (reached when streaming fails before any actions are applied and the error is not 401/402/403/502/503) dispatches all actions including `add_layer` and `remove_layer` directly through `handleChatAction` without staging them first. This defeats the core Phase 1135 invariant that destructive actions require explicit user confirmation before map mutation.

```typescript
// CURRENT (lines 562-573) — add_layer and remove_layer applied immediately:
for (const action of responseActions) {
  handleChatAction(action);   // <-- add_layer / remove_layer fire here with no staging
  if (!isUndoSafeAction(action) && lastSnapshotRef.current) {
    lastSnapshotRef.current.supportsUndo = false;
  }
  const layerId = getActionLayerId(action);
  if (action.type === 'remove_layer' && layerId) {
    cleanStaleLayerRefs(mapId, layerId);
  }
}
```

**Fix:** Route destructive actions through `staging.push()` in the non-streaming fallback, exactly as the streaming loop does:

```typescript
for (const action of responseActions) {
  if (isDestructiveAction(action)) {
    staging.push(action);
    // still record in responseActions for the message bubble
    continue;
  }
  handleChatAction(action);
  if (!isUndoSafeAction(action) && lastSnapshotRef.current) {
    lastSnapshotRef.current.supportsUndo = false;
  }
  const layerId = getActionLayerId(action);
  if (action.type === 'remove_layer' && layerId) {
    cleanStaleLayerRefs(mapId, layerId);
  }
}
```

---

### CR-02: `cleanStaleLayerRefs` Never Called for Staged `remove_layer` Actions

**File:** `frontend/src/components/builder/ChatPanel.tsx:373-378` (comment) and `317-371` (implementation)

**Issue:** The comment at line 375 states "Accepts route through `handleChatAction` so cleanStaleLayerRefs + snapshot logic fires on the same path." This is incorrect — `handleChatAction` contains neither `cleanStaleLayerRefs` nor snapshot logic. When `staging.acceptAll()` or `staging.acceptOne()` fires for a `remove_layer` action, the accept path is: `staging.dispatchRef.current(action)` → `handleChatAction(action)` → `onRemove(layerId)`. The `cleanStaleLayerRefs` call is absent. Session storage retains history entries referencing the removed layer, meaning future AI prompts will include stale `actions[].layer_id` references for a layer that no longer exists on the map.

Additionally, in the streaming path (lines 455–463), `remove_layer` actions reach `staging.push()` via the `if (isDestructiveAction(action))` branch and `continue` — execution never reaches the `cleanStaleLayerRefs` call at lines 469–473, which is guarded by `!isDestructiveAction`. So the cleanup is unreachable for any staged `remove_layer` in the streaming path too.

**Fix:** Move `cleanStaleLayerRefs` into `handleChatAction` for the `remove_layer` case, so it fires regardless of which path dispatches the action:

```typescript
case 'remove_layer':
  if (layerId) {
    onRemove(layerId);
    cleanStaleLayerRefs(mapId, layerId);  // add here
  }
  break;
```

Then remove the duplicate call sites in the streaming loop (line 469–473) and the non-streaming fallback loop (line 567–571). Also update the misleading comment at line 375.

---

## Warnings

### WR-01: `buildChipText` Sort Direction Produces Wrong Reference Layer for "Add Below" Chip

**File:** `frontend/src/components/builder/ChatPanel.tsx:227-231`

**Issue:** The chip text for `add_layer` actions reads `chat.staging.chipAddBelow` with `ref` set to `sorted[0]` where `sorted = layers.slice().sort((a, b) => b.sort_order - a.sort_order)` — a **descending** sort. Since `sort_order=0` is the topmost layer (prepended at index 0 per BSR-18), descending sort places the layer with the **highest** sort_order at index 0, which is the **bottom-most** existing layer. However, a new `add_layer` action inserts at `sort_order=0` — the **top** of the stack, above all existing layers. The chip therefore reads "Add [name] below [bottomLayer]" when the actual insertion point is above all existing layers, not below the bottom-most one. Users see a misleading confirmation prompt.

```typescript
// CURRENT — sorts descending, grabs highest sort_order = bottom layer:
const sorted = layers.slice().sort((a, b) => b.sort_order - a.sort_order);
const topLayer = sorted[0];  // this is actually the bottom-most layer

// FIX — sort ascending to get the top-most (sort_order=0 or smallest) as the reference:
const sorted = layers.slice().sort((a, b) => a.sort_order - b.sort_order);
const topLayer = sorted[0];  // now correctly the topmost existing layer
```

The i18n key `chat.staging.chipAddBelow` should then describe the new layer going "above" the reference layer, or the sort direction should be corrected to use ascending order so `sorted[0]` genuinely is the topmost layer.

---

### WR-02: `hasPaintMutation` Returns `false` for `replace_paint=true` with Empty/No `paint`

**File:** `frontend/src/components/builder/ChatPanel.tsx:99-106`

**Issue:** The third clause of `hasPaintMutation` is `action.replace_paint === true && paint` — requiring `paint` to be truthy. An action with `replace_paint=true` and no paint keys (empty `{}` or absent `paint`) passes `getActionPaint` returning `null`, making the clause false and the whole predicate false. Consequently, `handleChatAction` for `set_style` silently ignores this action (`hasPaintMutation` guards the dispatch). But `buildChatActionPaint` with `replace_paint=true` starts from an empty object and applies no new keys — this would wipe all existing paint properties, which is a meaningful map mutation that should not be suppressed.

```typescript
// CURRENT (line 103-104):
(action.replace_paint === true && paint),

// FIX — replace_paint intent is sufficient without requiring non-empty paint:
(action.replace_paint === true),
```

---

### WR-03: 403 Error from Non-Streaming Fallback Shows Inline Bubble, Not Sticky Banner

**File:** `frontend/src/components/builder/ChatPanel.tsx:584-594`

**Issue:** In the non-streaming fallback (`sendChatMessage`), all `ApiError`s from the fallback request are funneled to `mapApiErrorToMessage()` and displayed as an inline error bubble (line 588). If the fallback request returns 403 (permissions revoked mid-session) or 503 (AI down), the result is an inline bubble saying "You don't have access" or "AI unavailable" — not the sticky banner that the streaming path shows for the same status codes (lines 530–537). Users who experience this edge case see inconsistent UX and no retry affordance. The 503 case is particularly notable because the streaming path shows a retry button, but the non-streaming fallback path never does.

**Fix:** Mirror the streaming error classification in the fallback catch block:

```typescript
} catch (fallbackErr) {
  if (fallbackErr instanceof ApiError && (fallbackErr.status === 403 || fallbackErr.status === 503)) {
    setErrorBanner({
      kind: fallbackErr.status === 403 ? 'forbidden' : 'unavailable',
      retryMessage: userMsg,
    });
  } else {
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: 'error',
        content: mapApiErrorToMessage(fallbackErr),
        retryMessage: userMsg,
      },
    ]);
  }
}
```

---

## Info

### IN-01: Duplicate Mention-Format Logic in `chat-suggestions.ts`

**File:** `frontend/src/components/builder/chat-suggestions.ts:18-25`

**Issue:** `mentionName(layer: MapLayerResponse)` and `formatLayerNameForMention(name: string)` contain identical formatting logic (`name.includes(' ') ? '@[${name}]' : '@${name}'`). `mentionName` could simply delegate to `formatLayerNameForMention`:

```typescript
function mentionName(layer: MapLayerResponse): string {
  return formatLayerNameForMention(layer.display_name ?? layer.dataset_name);
}
```

This removes the duplication and ensures the two paths stay in sync if the format ever changes.

---

### IN-02: `rows[0]` Used Without Null Guard in Inline Data Card

**File:** `frontend/src/components/builder/ChatPanel.tsx:739-740`

**Issue:** After `rows.length === 0` is checked at line 731, the non-empty branch assumes `rows[0]` is a non-null `Record<string, unknown>`. The cast at line 739 (`const firstRow = rows[0] as Record<string, unknown>`) has no runtime null check. If the backend ever returns `[null, ...]` (e.g. due to a database NULL row that survives serialization), `Object.keys(firstRow)` at line 740 throws `TypeError: Cannot convert undefined or null to object` and crashes the message bubble render. The risk is low given the backend's typed `rows` output, but the cast is unsafe.

**Fix:** Add a null guard or use optional chaining:

```typescript
const firstRow = rows[0];
if (!firstRow || typeof firstRow !== 'object') return null;
const allColumns = Object.keys(firstRow as Record<string, unknown>);
```

---

### IN-03: Misleading Comment — `handleChatAction` Described as Firing `cleanStaleLayerRefs` and Snapshot Logic

**File:** `frontend/src/components/builder/ChatPanel.tsx:373-377`

**Issue:** The comment block reads: "Accepts route through `handleChatAction` so cleanStaleLayerRefs + snapshot logic fires on the same path as the existing immediate-dispatch flow." This is factually incorrect regardless of the CR-02 fix status: `handleChatAction` does not call `cleanStaleLayerRefs` and does not touch `lastSnapshotRef`. The snapshot is taken in `handleSend` before the staging push, not inside `handleChatAction`. The comment misleads future maintainers into believing the accept path is equivalent to the direct-dispatch path.

**Fix:** Replace with accurate documentation:

```typescript
// Phase 1135 AI-01 / AI-09: staging buffer for destructive actions (add_layer / remove_layer).
// `staging.push(action)` defers the action until the user accepts or rejects it.
// NOTE: accepts route through `handleChatAction` only for the map mutation itself.
// cleanStaleLayerRefs is called inside handleChatAction's remove_layer case (see CR-02 fix).
// The undo snapshot is captured in handleSend before push() — acceptAll/acceptOne do NOT
// retake a snapshot; the pre-streaming snapshot serves as the undo target for the whole turn.
```

---

_Reviewed: 2026-05-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
