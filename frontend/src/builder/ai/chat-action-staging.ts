/**
 * Staging buffer for destructive AI chat actions.
 *
 * Wraps the CALLER'S `dispatch` handler; it never calls `dispatchLayerAction`
 * itself. Pending destructive actions stay in a React state buffer until the
 * user accepts or rejects them. Accepting flushes them through `dispatch` in
 * push order; rejecting clears the buffer with zero map mutations, so the map
 * is byte-equal to its pre-prompt state and no snapshot/restore is needed.
 *
 * `BuilderActionSource` is not widened: no `'ai-pending'` or `'ai-committed'`
 * source values exist.
 *
 * Destructive (staged, need confirmation): `add_layer`, `remove_layer`.
 * Everything else (`show_query_result`, `set_filter`, `set_style`,
 * `set_data_driven_style`, `set_label`, `set_opacity`, `toggle_visibility`)
 * dispatches directly. Callers branch on `isDestructiveAction`.
 */
import { useState, useRef, useCallback } from 'react';
import type { ChatAction } from '@/types/api';

/** A ChatAction held in the staging buffer awaiting user confirmation. */
type PendingAction = ChatAction;

interface ChatActionStaging {
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

/**
 * True iff the action mutates the map's layer list (add_layer or remove_layer).
 * `show_query_result` is excluded: it only displays data, whatever
 * ChatPanel's `isUndoSafeAction` says about undo safety.
 */
export function isDestructiveAction(
  action: ChatAction,
): action is ChatAction & { type: 'add_layer' | 'remove_layer' } {
  return action.type === 'add_layer' || action.type === 'remove_layer';
}

/**
 * @param dispatch - Applies a PendingAction to the map. The latest value is
 *   mirrored in a ref so re-renders never produce stale closures.
 */
export function useChatActionStaging(
  dispatch: (action: PendingAction) => void,
): ChatActionStaging {
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);

  const dispatchRef = useRef(dispatch);
  dispatchRef.current = dispatch;

  // Updated in sync with setPendingActions so accept/reject read the current
  // buffer without setState updater side-effects (StrictMode may invoke them
  // twice). The ref drives dispatch; the state drives rendering.
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
    // Snapshot first so a concurrent push() can't change what is dispatched.
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
