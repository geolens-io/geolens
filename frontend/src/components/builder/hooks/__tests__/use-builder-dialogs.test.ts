import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useBuilderDialogs } from '@/components/builder/hooks/use-builder-dialogs';

describe('useBuilderDialogs', () => {
  it('all dialogs start closed', () => {
    const { result } = renderHook(() => useBuilderDialogs());

    expect(result.current.showChat).toBe(false);
    expect(result.current.showAddData).toBe(false);
    expect(result.current.showShare).toBe(false);
    expect(result.current.showInfo).toBe(false);
  });

  it('setShowChat toggles chat visibility', () => {
    const { result } = renderHook(() => useBuilderDialogs());

    act(() => {
      result.current.setShowChat(true);
    });

    expect(result.current.showChat).toBe(true);
  });

  it('keeps dock open across rerenders (notes tab still useful)', () => {
    const { result, rerender } = renderHook(() => useBuilderDialogs());

    // Open dock
    act(() => {
      result.current.setShowChat(true);
    });
    expect(result.current.showChat).toBe(true);

    // A rerender (e.g. AI availability changing upstream) does not close the dock.
    rerender();

    expect(result.current.showChat).toBe(true);
  });
});
