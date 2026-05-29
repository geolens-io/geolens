/**
 * Shape B staging buffer for destructive AI chat actions (Phase 1135 AI-01).
 *
 * ## Shape B Lock — NON-NEGOTIABLE (1135-CONTEXT.md D-Shape-B / Pitfall #3)
 *
 * This module sits ABOVE `dispatchLayerAction`. It accepts a consumer-supplied
 * `dispatch` function and holds pending destructive actions in a React state
 * buffer until the user explicitly accepts or rejects them.
 *
 * Accepting flushes actions through the caller's dispatch in original push
 * order. Rejecting clears the buffer with zero map mutations — the map state
 * is byte-equal to pre-prompt after rejectAll().
 *
 * `BuilderActionSource` is NOT widened. No `'ai-pending'` or `'ai-committed'`
 * source values are introduced. The v1027 typed action boundary is unchanged.
 * See v1030 hard invariant #5.
 *
 * ## Destructive vs Non-Destructive Actions
 *
 * Destructive (push into staging buffer, require user confirmation):
 *   - `add_layer`    — adds a new layer to the map stack
 *   - `remove_layer` — removes an existing layer from the map stack
 *
 * Non-destructive (bypass the staging buffer, dispatch directly):
 *   - `show_query_result` — displays data; does NOT mutate the layer list
 *   - `set_filter`, `set_style`, `set_data_driven_style`, `set_label`,
 *     `set_opacity`, `toggle_visibility` — attribute/style-only mutations
 *
 * Callers in Plan 02 should branch:
 *   if (isDestructiveAction(action)) staging.push(action);
 *   else dispatch(action);  // dispatch non-destructive directly
 *
 * ## Atomic Undo via rejectAll
 *
 * Because destructive actions are staged and never flushed until acceptAll()
 * or acceptOne(), rejectAll() guarantees that the underlying map state is
 * byte-equal to what it was before the AI prompt was sent. No partial
 * mutations, no snapshot/restore required.
 */
import { useState, useRef, useCallback } from 'react';
import type { ChatAction } from '@/types/api';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/**
 * PendingAction is a ChatAction held in the staging buffer awaiting user
 * confirmation. The staging module accepts any ChatAction shape; production
 * callers (Plan 02) only push destructive actions via isDestructiveAction gate.
 */
export type PendingAction = ChatAction;

/**
 * ChatActionStaging — the shape returned by useChatActionStaging.
 */
export interface ChatActionStaging {
  /** Current staged actions awaiting user confirmation. Immutable reference. */
  pendingActions: ReadonlyArray<PendingAction>;
  /** Append an action to the buffer. */
  push(action: PendingAction): void;
  /**
   * Dispatch all pending actions in original push order, then clear the buffer.
   * Returns a Promise that resolves after all sync dispatches complete.
   */
  acceptAll(): Promise<void>;
  /**
   * Clear the buffer without calling dispatch. Map state is byte-equal to
   * pre-prompt after this call.
   */
  rejectAll(): void;
  /**
   * Dispatch only the action at `index`, then remove it from the buffer.
   * No-op when `index` is out of range.
   */
  acceptOne(index: number): Promise<void>;
  /**
   * Remove only the action at `index` from the buffer without dispatching.
   * No-op when `index` is out of range.
   */
  rejectOne(index: number): void;
}

// ---------------------------------------------------------------------------
// isDestructiveAction predicate
// ---------------------------------------------------------------------------

/**
 * Returns true iff the action mutates the map's layer list (add_layer or
 * remove_layer). Non-destructive actions including show_query_result bypass
 * the staging buffer — see module docstring above.
 *
 * Note: show_query_result is intentionally excluded even though isUndoSafeAction
 * in ChatPanel treats it as non-undo-safe. The distinction here is map-layer-list
 * mutation, not undo safety. show_query_result only displays query data; it
 * does not add or remove MapLibre layers.
 */
export function isDestructiveAction(
  action: ChatAction,
): action is ChatAction & { type: 'add_layer' | 'remove_layer' } {
  return action.type === 'add_layer' || action.type === 'remove_layer';
}

// ---------------------------------------------------------------------------
// useChatActionStaging hook
// ---------------------------------------------------------------------------

/**
 * Staging buffer hook for destructive AI chat actions.
 *
 * @param dispatch - Consumer-supplied function that receives a PendingAction
 *   and applies it to the map. Typically wraps dispatchLayerAction from
 *   builder-action-contract.ts. The hook mirrors the latest dispatch via a ref
 *   so re-renders never produce stale closures.
 */
export function useChatActionStaging(
  dispatch: (action: PendingAction) => void,
): ChatActionStaging {
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);

  // Mirror latest dispatch to avoid stale closure across re-renders.
  const dispatchRef = useRef(dispatch);
  dispatchRef.current = dispatch;

  // Stable mirror of the current pending actions array. Updated in sync with
  // setPendingActions so accept/reject methods can read the current buffer
  // without relying on setState updater side-effects (which React StrictMode
  // may invoke twice). This ref is the single source of truth for dispatch;
  // the state array is the single source of truth for rendering.
  const actionsRef = useRef<PendingAction[]>([]);

  const push = useCallback((action: PendingAction) => {
    actionsRef.current = [...actionsRef.current, action];
    setPendingActions(actionsRef.current);
  }, []);

  const rejectAll = useCallback(() => {
    actionsRef.current = [];
    setPendingActions([]);
  }, []);

  const acceptAll = useCallback(async (): Promise<void> => {
    // Snapshot before clearing so we dispatch the correct actions even if
    // push() is called concurrently on the next render.
    const snapshot = actionsRef.current;
    actionsRef.current = [];
    setPendingActions([]);
    // Yield one microtask so React can flush the clear before dispatching.
    await Promise.resolve();
    for (const action of snapshot) {
      dispatchRef.current(action);
    }
  }, []);

  const rejectOne = useCallback((index: number) => {
    if (index < 0 || index >= actionsRef.current.length) return;
    const next = actionsRef.current.slice();
    next.splice(index, 1);
    actionsRef.current = next;
    setPendingActions(next);
  }, []);

  const acceptOne = useCallback(async (index: number): Promise<void> => {
    if (index < 0 || index >= actionsRef.current.length) return;
    const action = actionsRef.current[index];
    const next = actionsRef.current.slice();
    next.splice(index, 1);
    actionsRef.current = next;
    setPendingActions(next);
    // Yield one microtask so React can flush the splice before dispatch fires.
    await Promise.resolve();
    dispatchRef.current(action);
  }, []);

  return { pendingActions, push, acceptAll, rejectAll, acceptOne, rejectOne };
}
