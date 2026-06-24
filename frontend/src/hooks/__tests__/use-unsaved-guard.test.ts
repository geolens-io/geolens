import { renderHook } from '@testing-library/react';
import { useUnsavedGuard } from '../use-unsaved-guard';

const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
const mockUseBlocker = vi.fn((..._args: unknown[]) => mockBlocker);

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useBlocker: (...args: unknown[]) => mockUseBlocker(...args),
  };
});

describe('useUnsavedGuard', () => {
  let addSpy: ReturnType<typeof vi.spyOn>;
  let removeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    addSpy = vi.spyOn(window, 'addEventListener');
    removeSpy = vi.spyOn(window, 'removeEventListener');
  });

  afterEach(() => {
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  // The blocker is now passed as a FUNCTION (so hash-only tab navigation isn't
  // blocked); it should only block on real PATHNAME changes when dirty.
  it('blocks pathname changes when hasUnsavedChanges is true', () => {
    renderHook(() => useUnsavedGuard(true));
    const blockerFn = mockUseBlocker.mock.calls[0][0] as (args: {
      currentLocation: { pathname: string };
      nextLocation: { pathname: string };
    }) => boolean;
    expect(typeof blockerFn).toBe('function');
    expect(
      blockerFn({
        currentLocation: { pathname: '/datasets/1' },
        nextLocation: { pathname: '/' },
      }),
    ).toBe(true);
  });

  it('does not block hash-only navigation even when hasUnsavedChanges is true', () => {
    renderHook(() => useUnsavedGuard(true));
    const blockerFn = mockUseBlocker.mock.calls[0][0] as (args: {
      currentLocation: { pathname: string };
      nextLocation: { pathname: string };
    }) => boolean;
    expect(
      blockerFn({
        currentLocation: { pathname: '/datasets/1' },
        nextLocation: { pathname: '/datasets/1' },
      }),
    ).toBe(false);
  });

  it('does not block pathname changes when hasUnsavedChanges is false', () => {
    renderHook(() => useUnsavedGuard(false));
    const blockerFn = mockUseBlocker.mock.calls[0][0] as (args: {
      currentLocation: { pathname: string };
      nextLocation: { pathname: string };
    }) => boolean;
    expect(
      blockerFn({
        currentLocation: { pathname: '/datasets/1' },
        nextLocation: { pathname: '/' },
      }),
    ).toBe(false);
  });

  it('adds beforeunload listener when hasUnsavedChanges is true', () => {
    renderHook(() => useUnsavedGuard(true));
    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('does not add beforeunload listener when hasUnsavedChanges is false', () => {
    renderHook(() => useUnsavedGuard(false));
    const beforeunloadCalls = addSpy.mock.calls.filter(
      ([event]: [string, ...unknown[]]) => event === 'beforeunload',
    );
    expect(beforeunloadCalls).toHaveLength(0);
  });

  it('removes beforeunload listener on cleanup', () => {
    const { unmount } = renderHook(() => useUnsavedGuard(true));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('removes listener when hasUnsavedChanges transitions to false', () => {
    const { rerender } = renderHook(
      ({ dirty }) => useUnsavedGuard(dirty),
      { initialProps: { dirty: true } },
    );
    rerender({ dirty: false });
    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('returns the blocker object', () => {
    const { result } = renderHook(() => useUnsavedGuard(true));
    expect(result.current).toBe(mockBlocker);
  });
});
