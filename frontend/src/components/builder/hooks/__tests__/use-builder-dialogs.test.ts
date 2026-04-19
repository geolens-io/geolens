import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useBuilderDialogs } from '@/components/builder/hooks/use-builder-dialogs';

describe('useBuilderDialogs', () => {
  it('all dialogs start closed', () => {
    const { result } = renderHook(() => useBuilderDialogs(true));

    expect(result.current.showChat).toBe(false);
    expect(result.current.showAddData).toBe(false);
    expect(result.current.showShare).toBe(false);
    expect(result.current.showInfo).toBe(false);
    expect(result.current.sidebarCollapsed).toBe(false);
  });

  it('setShowChat toggles chat visibility', () => {
    const { result } = renderHook(() => useBuilderDialogs(true));

    act(() => {
      result.current.setShowChat(true);
    });

    expect(result.current.showChat).toBe(true);
  });

  it('keeps dock open when AI becomes unavailable (notes tab still useful)', () => {
    let aiAvailable = true;
    const { result, rerender } = renderHook(() => useBuilderDialogs(aiAvailable));

    // Open dock
    act(() => {
      result.current.setShowChat(true);
    });
    expect(result.current.showChat).toBe(true);

    // AI becomes unavailable — dock stays open (Notes tab still useful)
    aiAvailable = false;
    rerender();

    expect(result.current.showChat).toBe(true);
  });

  it('setSidebarCollapsed toggles sidebar state', () => {
    const { result } = renderHook(() => useBuilderDialogs(true));

    act(() => {
      result.current.setSidebarCollapsed(true);
    });

    expect(result.current.sidebarCollapsed).toBe(true);
  });
});
