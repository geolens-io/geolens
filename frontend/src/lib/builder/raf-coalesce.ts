/**
 * rAF-based paint-write coalescing.
 *
 * `coalesceFrame(key, fn)` queues `fn` under `key` for the next animation
 * frame. If `coalesceFrame` is called again with the same `key` before the
 * frame fires, the earlier `fn` is overwritten by the later one. This means
 * only the LAST write wins per animation frame.
 *
 * Multiple distinct keys all fire on the SAME rAF tick (one shared
 * `requestAnimationFrame` call), so two layers' paint updates still batch
 * into a single repaint.
 *
 * Without `requestAnimationFrame` (SSR, vitest without fake timers) `fn` runs
 * synchronously and nothing is queued.
 */

// `pending` is process-global, keyed only by the coalesce key (e.g.
// `paint:${layerId}`) with no map-instance discriminator. That holds while one
// BuilderMap is mounted at a time and `layer.id` is globally unique; two
// concurrent map surfaces with overlapping layer ids would clobber each other's
// writes on the shared frame.
const pending = new Map<string, () => void>();
let rafHandle: number | null = null;

function flush(): void {
  rafHandle = null;
  // Snapshot and clear first so a coalesceFrame call inside a fn schedules a
  // NEW frame.
  const snapshot = new Map(pending);
  pending.clear();
  for (const fn of snapshot.values()) {
    try {
      fn();
    } catch (e) {
      if (import.meta.env.DEV) {
        console.debug('[raf-coalesce] Error in flushed fn:', e);
      }
    }
  }
}

/**
 * Queue `fn` to run on the next animation frame under `key`. A second call
 * with the same key in the same frame replaces `fn`; different keys do not
 * coalesce.
 */
export function coalesceFrame(key: string, fn: () => void): void {
  if (typeof requestAnimationFrame === 'undefined') {
    fn();
    return;
  }

  pending.set(key, fn);

  if (rafHandle === null) {
    rafHandle = requestAnimationFrame(flush);
  }
}

/** Run the frame queued under `key` now, if there is one, and leave every other key queued. */
export function flushCoalescedFrame(key: string): void {
  const fn = pending.get(key);
  if (!fn) return;
  pending.delete(key);
  // Cancel BEFORE invoking, so a coalesceFrame call made inside `fn` schedules
  // a fresh frame rather than joining one that is about to fire empty.
  if (pending.size === 0 && rafHandle !== null) {
    cancelAnimationFrame(rafHandle);
    rafHandle = null;
  }
  try {
    fn();
  } catch (e) {
    if (import.meta.env.DEV) {
      console.debug('[raf-coalesce] Error in flushed fn:', e);
    }
  }
}

/** Read-only view of the pending map, for tests. */
export function __getPendingForTest(): ReadonlyMap<string, () => void> {
  return pending;
}

/** Flushes all pending entries synchronously, for tests that cannot advance rAF. */
export function __flushForTest(): void {
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle);
    rafHandle = null;
  }
  flush();
}

/** Cancels any scheduled rAF and clears the pending map without running fns. */
export function __resetForTest(): void {
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle);
    rafHandle = null;
  }
  pending.clear();
}

// Under Vite HMR, cancel any pending rAF so the replaced module's flush() does
// not fire stale callbacks.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
    }
    pending.clear();
  });
}
