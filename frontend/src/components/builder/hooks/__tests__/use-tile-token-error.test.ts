/**
 * GAP-004: BuilderMap ignores tile-token batch failures.
 * useTileTokenError must:
 *  1. Fire a deduped toast.error when the batch query errors.
 *  2. NOT fire a second toast while still in the error state (dedupe).
 *  3. Clear the error flag after a successful refetch.
 *
 * Tests are RED pre-fix (hook doesn't exist) and GREEN post-fix.
 */
import { renderHook, act } from '@testing-library/react';
import { useTileTokenError } from '../use-tile-token-error';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
  }),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { toast } from 'sonner';

describe('useTileTokenError (GAP-004)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls toast.error with a deduped id when isError=true', () => {
    renderHook(() => useTileTokenError(true));

    expect(toast.error).toHaveBeenCalledTimes(1);
    // Must use a dedup id so the toast doesn't stack on every render
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: expect.any(String) }),
    );
  });

  it('does NOT fire toast when isError=false', () => {
    renderHook(() => useTileTokenError(false));

    expect(toast.error).not.toHaveBeenCalled();
  });

  it('fires toast exactly once on repeated renders with isError=true (dedupe)', () => {
    const { rerender } = renderHook(({ err }) => useTileTokenError(err), {
      initialProps: { err: true },
    });

    rerender({ err: true });
    rerender({ err: true });

    // Should still be 1 — the toast id dedupes subsequent calls
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it('fires toast again after transitioning false→true→false→true', () => {
    const { rerender } = renderHook(({ err }) => useTileTokenError(err), {
      initialProps: { err: false },
    });

    act(() => { rerender({ err: true }); });
    expect(toast.error).toHaveBeenCalledTimes(1);

    act(() => { rerender({ err: false }); });
    act(() => { rerender({ err: true }); });
    // New error episode → toast fires again
    expect(toast.error).toHaveBeenCalledTimes(2);
  });
});
