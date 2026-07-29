import { StrictMode } from 'react';
import { renderHook } from '@testing-library/react';
import { useAbortSignal } from '@/hooks/use-abort-signal';

// Flush pending microtasks (the deferred abort in the hook's cleanup).
const flushMicrotasks = () => new Promise<void>((resolve) => { setTimeout(resolve, 0); });

describe('useAbortSignal', () => {
  it('aborts the signal on unmount', async () => {
    const { result, unmount } = renderHook(() => useAbortSignal());
    const signal = result.current;
    expect(signal.aborted).toBe(false);

    unmount();
    await flushMicrotasks();
    expect(signal.aborted).toBe(true);
  });

  // fix(#833): StrictMode's dev-only unmount/remount used to abort the one
  // controller the consumer ever sees, silently cancelling the first real
  // request in dev.
  it('does not return a pre-aborted signal under StrictMode double-invoke', async () => {
    const { result, unmount } = renderHook(() => useAbortSignal(), {
      wrapper: StrictMode,
    });
    const signal = result.current;

    await flushMicrotasks();
    expect(signal.aborted).toBe(false);

    // A real unmount must still abort.
    unmount();
    await flushMicrotasks();
    expect(signal.aborted).toBe(true);
  });
});
