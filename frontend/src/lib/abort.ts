/**
 * Abort when the caller's signal fires or after `ms`, whichever is first.
 * `AbortSignal.any` is missing from Safari before 17.4 and Firefox before 124,
 * which the build still targets, so those browsers get a manual composition.
 */
export function signalWithTimeout(signal: AbortSignal | undefined | null, ms: number): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  if (!signal) return timeout;
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([signal, timeout]);
  const controller = new AbortController();
  const abort = (source: AbortSignal) => () => controller.abort(source.reason);
  if (signal.aborted) controller.abort(signal.reason);
  else if (timeout.aborted) controller.abort(timeout.reason);
  else {
    signal.addEventListener('abort', abort(signal), { once: true });
    timeout.addEventListener('abort', abort(timeout), { once: true });
  }
  return controller.signal;
}

/** Resolves after `ms`, or rejects with the signal's reason as soon as it aborts. */
export function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(signal.reason);
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', abort, { once: true });
  });
}
