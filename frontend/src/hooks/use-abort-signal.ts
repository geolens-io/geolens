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

  useEffect(() => {
    const controller = ref.current;
    return () => {
      controller.abort();
    };
  }, []);

  return ref.current.signal;
}
