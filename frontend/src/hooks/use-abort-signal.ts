import { useEffect, useRef } from 'react';

/**
 * Returns an AbortSignal that fires when the component unmounts.
 * Use to cancel in-flight fetch requests on cleanup.
 *
 * NOTE: This is for unmount cleanup only. For superseding requests
 * (aborting previous search when a new one starts), use a separate
 * AbortController pattern per-request.
 */
export function useAbortSignal(): AbortSignal {
  const ref = useRef(new AbortController());
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    const controller = ref.current;
    return () => {
      mountedRef.current = false;
      // fix(#833): under React StrictMode's dev-only unmount/remount, aborting
      // synchronously here handed every consumer a permanently pre-aborted
      // signal — no render happens between cleanup and re-setup, so a fresh
      // controller could never reach them, and the first real request was
      // silently cancelled. Defer the abort one microtask: StrictMode's
      // re-setup runs synchronously in the same flush and flips mountedRef
      // back, so only a real unmount aborts.
      queueMicrotask(() => {
        if (!mountedRef.current) controller.abort();
      });
    };
  }, []);

  return ref.current.signal;
}
