---
phase: "1135"
name: "AI Chat Confirm-Before-Apply and Analysis Polish"
gathered: "2026-05-27"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss); ONE user pick: staging shape B"
---

# Phase 1135: AI Chat Confirm-Before-Apply and Analysis Polish — Context

<domain>
## Phase Boundary

Add confirm-before-apply staging for destructive AI actions, action preview chips, viewport-aware suggestions, and an inline data-analysis card — all on top of the v1027 typed action boundary WITHOUT bypassing or widening it.

**Requirements:** AI-01, AI-02, AI-03, AI-04, AI-05, AI-08, AI-09.

**5 ROADMAP success criteria:**
1. User can preview destructive AI actions (`add_layer`, `remove_layer`) before they apply, accept/reject each staged action, and rejecting leaves the map byte-equal to pre-prompt layer state; regression in `ChatPanel.test.tsx`.
2. Action preview chips render before destructive actions apply, showing the staged change in human-readable form ("Add 'NYC subway' below 'Counties'"); chips gated on staging shape B.
3. Suggestion chips reflect current viewport + selected-layer context (not static default list); data-analysis questions render in inline card via existing `show_query_result` action (no new BuilderLayerAction variant beyond extending `add_dataset`).
4. With `AI_ENABLED=false`: AI rail panel surfaces actionable disabled state (no inert dead-end button), zero console errors, regression in `ChatPanel.test.tsx`. Invalid provider key: recoverable error banner + retry. Every new AI hook gated on `enabled: !!token && aiEnabled` (Pitfall #4 / v1010.2 SF-06 recurrence guard).
5. `_validate_chat_layers` visibility-filter decision documented in `chat_actions.py` docstring (Pitfall #5). Schema-context cache key remains `(map_id, dataset_id)` — no `dataset_id`-only shortcut.

</domain>

<decisions>
## Implementation Decisions

### Locked — Staging Shape B (Pitfall #3 NON-NEGOTIABLE pick)

**Selected:** Shape B — `pendingLayers` staging buffer in NEW `chat-action-staging.ts` module that sits ABOVE `dispatchLayerAction`.

**Rationale:**
1. **v1030 hard invariant #5 — no `BuilderActionSource` widening without Future Requirement entry first.** Shape A would require widening the typed action union to `'ai-pending' | 'ai-committed'`, breaking that invariant.
2. **Cleaner separation of concerns.** AI staging is an above-the-dispatcher concern, not a typed-action variant. Keep the dispatcher contract narrow.
3. **Atomic undo is trivial.** Reject = `pendingActions = []`. Map state never mutated until `acceptAll()` / `acceptOne()`.
4. **Reconciler unchanged.** No side-effect gating. v1026 reconciler invariants hold.
5. **`dispatchLayerAction` unchanged.** v1027 typed action-boundary stable.

**Module shape:**
```typescript
// frontend/src/builder/ai/chat-action-staging.ts (NEW, ~150 LOC)
export type PendingAction =
  | { kind: 'add_layer'; payload: AddLayerPayload }
  | { kind: 'remove_layer'; layerId: string }
  | { kind: 'show_query_result'; rows: Row[] };

export interface ChatActionStaging {
  pendingActions: PendingAction[];
  push(action: PendingAction): void;
  acceptAll(): Promise<void>;     // flushes through dispatchLayerAction
  rejectAll(): void;              // clears buffer, no map mutation
  acceptOne(index: number): Promise<void>;
  rejectOne(index: number): void;
}
```

**Wiring point:** AI response handler in `ChatPanel.tsx` (or `useAIChat.ts`) — destructive actions (`add_layer`, `remove_layer`) push into staging buffer; non-destructive (`show_query_result`, viewport-aware suggestions) bypass and dispatch directly.

### Claude's Discretion (Remaining)
All other implementation choices at Claude's discretion. ROADMAP success criteria + Phase 1133 audit + Phase 1134 stabilized dispatcher are the spec.

### Key Pre-Decided Anchors
- **Pitfall #4 (AI gating):** Every new AI consumer hook gated on `enabled: !!token && aiEnabled` per Phase 1133 matrix. Sweep ALL sibling hooks, not just one (v1010.2 SF-06 contract).
- **Pitfall #5 (`_validate_chat_layers` visibility filter):** Document decision in docstring. Default: ANALYSIS sees all layers regardless of visibility (because users hide layers for visual clutter, not for "don't analyze these"). Rationale must appear in docstring.
- **Schema-context cache key:** `(map_id, dataset_id)` — do NOT add `dataset_id`-only fast path (cache invalidation drift).
- **No widening BuilderLayerAction union.** `show_query_result` (already existing per ROADMAP) is sufficient. Extending `add_dataset` to carry analysis result is allowed.
- **Disabled-state and error-banner are recoverable.** ChatPanel detects 503 (AI_ENABLED=false) and 401/403 (invalid key) distinctly. UI affords retry on 401/403; explains "AI is disabled" on 503.

</decisions>

<code_context>
## Existing Code Insights

Anchor files (expanded in plan-phase):
- `backend/app/processing/ai/router.py` (every `/ai/*` endpoint — Phase 1133 matrix is ground truth)
- `backend/app/processing/ai/chat_actions.py` (`_validate_chat_layers` — Pitfall #5 docstring target)
- `backend/app/processing/ai/schema_context.py` (cache key — preserve `(map_id, dataset_id)`)
- `frontend/src/builder/ai/ChatPanel.tsx` (AI rail surface — disabled state + error banner targets)
- `frontend/src/builder/ai/use-ai-chat.ts` (chat lifecycle, AI response handler — staging wiring point)
- `frontend/src/builder/ai/use-ai-availability.ts` (Phase 1133 confirmed gate)
- `frontend/src/builder/dispatchLayerAction.ts` (DO NOT WIDEN union)
- `frontend/src/components/builder/builder-action-contract.ts` (BuilderActionSource — DO NOT WIDEN)

</code_context>

<specifics>
## Specific Ideas

- **Action preview chips:** render in ChatPanel between AI response and Accept/Reject buttons. Chip text format: verb + entity + relative position. Example: `"Add 'NYC subway' below 'Counties'"` or `"Remove 'Boroughs (3 features)'"`.
- **Viewport-aware suggestions:** read `useBuilderViewport` (bounds + zoom) + `useSelectedLayer` and pass as context in suggestion-request payload. Backend already accepts viewport; check if hook surface needs extension.
- **Inline data-analysis card:** use existing `show_query_result` action. Renders below the AI response in ChatPanel with table-shape rows. No new BuilderLayerAction variant.
- **Disabled-state UI:** ChatPanel detects `useAIAvailability()` returns `{ isAIAvailable: false, reason: 'env_disabled' | 'no_key' | 'permission' }` and renders the matching message + (for permission/env_disabled) link to settings.
- **Recoverable error banner:** ChatPanel catches mutation errors, surfaces inline banner with retry button. On retry: re-fire the last user message.

</specifics>

<deferred>
## Deferred Ideas

- Shape A (`BuilderActionSource` widening + atomic undo via snapshot): deferred to a future Future Requirements entry if needed. Not in v1030 scope.
- Multi-step AI workflows / agentic chaining: out-of-scope per REQUIREMENTS.md (no new LLM providers).

</deferred>
