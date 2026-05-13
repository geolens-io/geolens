import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
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
  let removeEventListenerSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');
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
      expect(result.current.viewportWidth).toBe(1200);
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
      expect(result.current.viewportWidth).toBe(1024);
    });
  });

  describe('viewport band: editor hidden (< 800px)', () => {
    it('isRail=true, isEditorHidden=true at 600px', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 600 });
      vi.stubGlobal('matchMedia', makeMatchMedia(600));

      const { result } = renderHook(() => useBuilderLayout());

      expect(result.current.isRail).toBe(true);
      expect(result.current.isEditorHidden).toBe(true);
      expect(result.current.viewportWidth).toBe(600);
    });
  });

  describe('resize handler updates state', () => {
    it('updates viewportWidth when window resize fires', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      vi.stubGlobal('matchMedia', makeMatchMedia(1200));

      const { result } = renderHook(() => useBuilderLayout());
      expect(result.current.viewportWidth).toBe(1200);
      expect(result.current.isRail).toBe(false);

      // Simulate resize to 600px
      act(() => {
        Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 600 });
        vi.stubGlobal('matchMedia', makeMatchMedia(600));
        window.dispatchEvent(new Event('resize'));
      });

      expect(result.current.viewportWidth).toBe(600);
    });
  });

  describe('listener cleanup on unmount', () => {
    it('calls removeEventListener for resize on unmount', () => {
      Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });
      vi.stubGlobal('matchMedia', makeMatchMedia(1200));

      const { unmount } = renderHook(() => useBuilderLayout());
      unmount();

      expect(removeEventListenerSpy).toHaveBeenCalledWith('resize', expect.any(Function));
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
