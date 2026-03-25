import { renderHook } from '@testing-library/react';
import { useUnsavedGuard } from '../use-unsaved-guard';

const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
const mockUseBlocker = vi.fn(() => mockBlocker);

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

  it('calls useBlocker with true when hasUnsavedChanges is true', () => {
    renderHook(() => useUnsavedGuard(true));
    expect(mockUseBlocker).toHaveBeenCalledWith(true);
  });

  it('calls useBlocker with false when hasUnsavedChanges is false', () => {
    renderHook(() => useUnsavedGuard(false));
    expect(mockUseBlocker).toHaveBeenCalledWith(false);
  });

  it('adds beforeunload listener when hasUnsavedChanges is true', () => {
    renderHook(() => useUnsavedGuard(true));
    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('does not add beforeunload listener when hasUnsavedChanges is false', () => {
    renderHook(() => useUnsavedGuard(false));
    const beforeunloadCalls = addSpy.mock.calls.filter(
      ([event]) => event === 'beforeunload',
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
