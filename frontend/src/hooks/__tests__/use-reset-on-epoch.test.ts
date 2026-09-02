import { renderHook } from '@testing-library/react';
import { useResetOnEpoch } from '@/hooks/use-reset-on-epoch';

// fix(#1761 review round 4): shared by SearchBar, FilterPanel and
// FilterSheet — see their identity tests for the end-to-end behavior this
// enables. These pin the hook's own contract in isolation.
describe('useResetOnEpoch', () => {
  it('does not call reset on mount, even with a nonzero starting epoch', () => {
    const reset = vi.fn();
    renderHook(({ epoch }) => useResetOnEpoch(epoch, reset), {
      initialProps: { epoch: 42 },
    });

    expect(reset).not.toHaveBeenCalled();
  });

  it('calls reset when the epoch changes after mount', () => {
    const reset = vi.fn();
    const { rerender } = renderHook(({ epoch }) => useResetOnEpoch(epoch, reset), {
      initialProps: { epoch: 0 },
    });

    rerender({ epoch: 1 });

    expect(reset).toHaveBeenCalledTimes(1);
  });

  it('does not call reset again on a re-render with the same epoch', () => {
    const reset = vi.fn();
    const { rerender } = renderHook(({ epoch }) => useResetOnEpoch(epoch, reset), {
      initialProps: { epoch: 0 },
    });

    rerender({ epoch: 1 });
    rerender({ epoch: 1 });

    expect(reset).toHaveBeenCalledTimes(1);
  });

  it('calls reset once per subsequent epoch change', () => {
    const reset = vi.fn();
    const { rerender } = renderHook(({ epoch }) => useResetOnEpoch(epoch, reset), {
      initialProps: { epoch: 0 },
    });

    rerender({ epoch: 1 });
    rerender({ epoch: 2 });

    expect(reset).toHaveBeenCalledTimes(2);
  });
});
