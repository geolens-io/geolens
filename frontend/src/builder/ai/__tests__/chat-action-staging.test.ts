/**
 * Unit tests for the Shape B chat-action-staging module (Phase 1135 AI-01).
 *
 * Tests the staging buffer mechanics: push, acceptAll order, rejectAll clears
 * buffer with zero dispatch calls, acceptOne removes only the indexed action,
 * rejectOne clears only the indexed action, isDestructiveAction predicate gate.
 *
 * These tests run without a real React tree or MapLibre instance — the staging
 * module is pure (no map mutations, no API calls).
 */
import { renderHook, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { isDestructiveAction, useChatActionStaging } from '../chat-action-staging';
import type { ChatAction } from '@/types/api';

// ---------------------------------------------------------------------------
// Helpers — build minimal ChatAction fixtures
// ---------------------------------------------------------------------------

function makeAction(type: ChatAction['type'], layerId = 'layer-1'): ChatAction {
  return { type, layer_id: layerId };
}

function addLayerAction(datasetId = 'ds-A'): ChatAction {
  return { type: 'add_layer', dataset_id: datasetId };
}

function removeLayerAction(layerId = 'layer-B'): ChatAction {
  return { type: 'remove_layer', layer_id: layerId };
}

// ---------------------------------------------------------------------------
// Test 1–3: isDestructiveAction predicate
// ---------------------------------------------------------------------------

describe('isDestructiveAction', () => {
  it('returns true for add_layer and remove_layer', () => {
    expect(isDestructiveAction(makeAction('add_layer'))).toBe(true);
    expect(isDestructiveAction(makeAction('remove_layer'))).toBe(true);
  });

  it('returns false for show_query_result', () => {
    // show_query_result is NOT destructive — bypasses staging buffer per CONTEXT.md
    expect(isDestructiveAction(makeAction('show_query_result'))).toBe(false);
  });

  it('returns false for all other non-destructive types', () => {
    const nonDestructive: ChatAction['type'][] = [
      'set_filter',
      'set_style',
      'set_data_driven_style',
      'set_label',
      'set_opacity',
      'toggle_visibility',
    ];
    for (const type of nonDestructive) {
      expect(isDestructiveAction(makeAction(type))).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// Tests 4–11: useChatActionStaging hook mechanics
// ---------------------------------------------------------------------------

describe('useChatActionStaging', () => {
  // mockFn is the vi.fn() spy used for call-count assertions.
  // dispatch is the typed version passed to the hook.
  let mockFn: ReturnType<typeof vi.fn>;
  let dispatch: (action: ChatAction) => void;

  beforeEach(() => {
    mockFn = vi.fn();
    dispatch = mockFn as unknown as (action: ChatAction) => void;
  });

  // Test 4
  it('push appends to pendingActions in order', () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));

    act(() => {
      result.current.push(addLayerAction('ds-A'));
      result.current.push(removeLayerAction('layer-B'));
      result.current.push(addLayerAction('ds-C'));
    });

    expect(result.current.pendingActions).toHaveLength(3);
    expect(result.current.pendingActions[0]).toMatchObject({ type: 'add_layer', dataset_id: 'ds-A' });
    expect(result.current.pendingActions[1]).toMatchObject({ type: 'remove_layer', layer_id: 'layer-B' });
    expect(result.current.pendingActions[2]).toMatchObject({ type: 'add_layer', dataset_id: 'ds-C' });
  });

  // Test 5
  it('rejectAll clears buffer with zero dispatch calls', () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));

    act(() => {
      result.current.push(addLayerAction('ds-A'));
      result.current.push(removeLayerAction('layer-B'));
      result.current.push(addLayerAction('ds-C'));
    });

    act(() => {
      result.current.rejectAll();
    });

    expect(result.current.pendingActions).toHaveLength(0);
    expect(mockFn).not.toHaveBeenCalled();
  });

  // Test 6
  it('acceptAll invokes dispatch N times in original push order', async () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));
    const a = addLayerAction('ds-A');
    const b = removeLayerAction('layer-B');
    const c = addLayerAction('ds-C');

    act(() => {
      result.current.push(a);
      result.current.push(b);
      result.current.push(c);
    });

    await act(async () => {
      await result.current.acceptAll();
    });

    expect(mockFn).toHaveBeenCalledTimes(3);
    expect(mockFn).toHaveBeenNthCalledWith(1, a);
    expect(mockFn).toHaveBeenNthCalledWith(2, b);
    expect(mockFn).toHaveBeenNthCalledWith(3, c);
  });

  // Test 7
  it('acceptAll clears buffer after flush', async () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));

    act(() => {
      result.current.push(addLayerAction('ds-A'));
      result.current.push(removeLayerAction('layer-B'));
    });

    await act(async () => {
      await result.current.acceptAll();
    });

    expect(result.current.pendingActions).toHaveLength(0);
  });

  // Test 8
  it('acceptOne dispatches only the indexed action and removes it', async () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));
    const a = addLayerAction('ds-A');
    const b = removeLayerAction('layer-B');
    const c = addLayerAction('ds-C');

    act(() => {
      result.current.push(a);
      result.current.push(b);
      result.current.push(c);
    });

    await act(async () => {
      await result.current.acceptOne(1);
    });

    expect(mockFn).toHaveBeenCalledTimes(1);
    expect(mockFn).toHaveBeenCalledWith(b);
    expect(result.current.pendingActions).toHaveLength(2);
    expect(result.current.pendingActions[0]).toEqual(a);
    expect(result.current.pendingActions[1]).toEqual(c);
  });

  // Test 9
  it('rejectOne removes only the indexed action and never dispatches', () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));
    const a = addLayerAction('ds-A');
    const b = removeLayerAction('layer-B');
    const c = addLayerAction('ds-C');

    act(() => {
      result.current.push(a);
      result.current.push(b);
      result.current.push(c);
    });

    act(() => {
      result.current.rejectOne(0);
    });

    expect(result.current.pendingActions).toHaveLength(2);
    expect(result.current.pendingActions[0]).toEqual(b);
    expect(result.current.pendingActions[1]).toEqual(c);
    expect(mockFn).not.toHaveBeenCalled();
  });

  // Test 10
  it('acceptOne with out-of-range index is a no-op', async () => {
    const { result } = renderHook(() => useChatActionStaging(dispatch));
    const a = addLayerAction('ds-A');

    act(() => {
      result.current.push(a);
    });

    await act(async () => {
      await result.current.acceptOne(5);
    });

    expect(result.current.pendingActions).toHaveLength(1);
    expect(mockFn).not.toHaveBeenCalled();
  });

  // Test 11
  it('dispatchRef mirrors latest dispatch — no stale closure on re-render', async () => {
    const mock1 = vi.fn();
    const mock2 = vi.fn();
    const dispatch1 = mock1 as unknown as (action: ChatAction) => void;
    const dispatch2 = mock2 as unknown as (action: ChatAction) => void;

    const { result, rerender } = renderHook(
      ({ fn }: { fn: (action: ChatAction) => void }) => useChatActionStaging(fn),
      { initialProps: { fn: dispatch1 } },
    );

    // Re-render with the new dispatch before pushing — stale closure guard
    rerender({ fn: dispatch2 });

    act(() => {
      result.current.push(addLayerAction('ds-X'));
    });

    await act(async () => {
      await result.current.acceptAll();
    });

    expect(mock2).toHaveBeenCalledTimes(1);
    expect(mock1).not.toHaveBeenCalled();
  });
});
