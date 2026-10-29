/**
 * At most `max` holders at once; the rest wait in arrival order. `acquire`
 * resolves to the release for that slot, and a waiter whose signal aborts
 * leaves the queue with the signal's reason.
 */
export function createSlotPool(max: number) {
  let active = 0;
  const waiting: Array<() => void> = [];

  const release = () => {
    const next = waiting.shift();
    if (next) next();
    else active -= 1;
  };
  const releaseOnce = () => {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      release();
    };
  };

  return {
    acquire(signal?: AbortSignal): Promise<() => void> {
      if (signal?.aborted) return Promise.reject(signal.reason);
      if (active < max) {
        active += 1;
        return Promise.resolve(releaseOnce());
      }
      return new Promise((resolve, reject) => {
        const grant = () => {
          signal?.removeEventListener('abort', abort);
          resolve(releaseOnce());
        };
        const abort = () => {
          waiting.splice(waiting.indexOf(grant), 1);
          reject(signal?.reason);
        };
        signal?.addEventListener('abort', abort, { once: true });
        waiting.push(grant);
      });
    },
  };
}
