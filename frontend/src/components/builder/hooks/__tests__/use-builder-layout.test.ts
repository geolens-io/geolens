import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useBuilderLayout } from '@/components/builder/hooks/use-builder-layout';

/**
 * matchMedia stub — returns a MediaQueryList-like object whose `matches` is
 * set by the query string and the current `window.innerWidth`.
 *
 * The pattern is: `(max-width: Npx)` → matches when innerWidth <= N.
 */
function makeMatchMedia(width: number) {
  return (query: string) => {
    const match = query.match(/max-width:\s*(\d+)px/);
    const maxWidth = match ? parseInt(match[1], 10) : Infinity;
    const obj = {
      matches: width <= maxWidth,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    };
    return obj;
  };
}

describe('useBuilderLayout', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('viewport band: wide (>= 1100px)', () => {
    it('isRail=false, isEditorHidden=false at 1200px', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      vi.stubGlobal('matchMedia', makeMatchMedia(1200));

      const { result } = renderHook(() => useBuilderLayout());

      expect(result.current.isRail).toBe(false);
      expect(result.current.isEditorHidden).toBe(false);
    });

    it('backward-compat: isCompact and isMobile alias to isRail and isEditorHidden', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      vi.stubGlobal('matchMedia', makeMatchMedia(1200));

      const { result } = renderHook(() => useBuilderLayout());

      expect(result.current.isCompact).toBe(result.current.isRail);
      expect(result.current.isMobile).toBe(result.current.isEditorHidden);
    });
  });

  describe('viewport band: rail mode (800–1099px)', () => {
    it('isRail=true, isEditorHidden=false at 1024px', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1024 });
      vi.stubGlobal('matchMedia', makeMatchMedia(1024));

      const { result } = renderHook(() => useBuilderLayout());

      expect(result.current.isRail).toBe(true);
      expect(result.current.isEditorHidden).toBe(false);
    });
  });

  describe('viewport band: editor hidden (< 800px)', () => {
    it('isRail=true, isEditorHidden=true at 600px', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 600 });
      vi.stubGlobal('matchMedia', makeMatchMedia(600));

      const { result } = renderHook(() => useBuilderLayout());

      expect(result.current.isRail).toBe(true);
      expect(result.current.isEditorHidden).toBe(true);
    });
  });

  describe('listener cleanup on unmount', () => {
    it('removes MQL change listeners on unmount', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      const mockMql = makeMatchMedia(1200);
      const removeListeners: Array<[string, EventListenerOrEventListenerObject]> = [];
      const trackedMql = (query: string) => {
        const obj = mockMql(query);
        obj.removeEventListener = vi.fn((...args) => {
          removeListeners.push(args as [string, EventListenerOrEventListenerObject]);
        });
        return obj;
      };
      vi.stubGlobal('matchMedia', trackedMql);

      const { unmount } = renderHook(() => useBuilderLayout());
      unmount();

      // Two MQL listeners should be removed (rail + editorHidden)
      expect(removeListeners.length).toBe(2);
      expect(removeListeners.every(([event]) => event === 'change')).toBe(true);
    });
  });

  describe('breakpoint constants', () => {
    it('uses 1100 and 800 as locked breakpoints', () => {
      // These values are locked from UI-SPEC §"Responsive breakpoints"
      // We test the boundary: at exactly 1099, isRail should be true
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1099 });
      vi.stubGlobal('matchMedia', makeMatchMedia(1099));

      const { result } = renderHook(() => useBuilderLayout());
      expect(result.current.isRail).toBe(true);
      expect(result.current.isEditorHidden).toBe(false);
    });

    it('at exactly 800, isEditorHidden should be false (boundary is < 800)', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });
      vi.stubGlobal('matchMedia', makeMatchMedia(800));

      const { result } = renderHook(() => useBuilderLayout());
      // 800 is NOT less than 800, so editor should not be hidden
      expect(result.current.isRail).toBe(true);
      expect(result.current.isEditorHidden).toBe(false);
    });
  });
});
