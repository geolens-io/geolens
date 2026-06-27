/**
 * rAF-based paint-write coalescing (PERF-04).
 *
 * `coalesceFrame(key, fn)` queues `fn` under `key` for the next animation
 * frame. If `coalesceFrame` is called again with the same `key` before the
 * frame fires, the earlier `fn` is overwritten by the later one. This means
 * only the LAST write wins per animation frame, which matches the visual
 * contract: "the user sees the value that was current when the frame paints."
 *
 * Multiple distinct keys all fire on the SAME rAF tick (one shared
 * `requestAnimationFrame` call), so two layers' paint updates still batch
 * into a single repaint.
 *
 * SSR / no-rAF fallback: if `requestAnimationFrame` is not available (e.g.
 * Node.js / vitest environment without fake timers), `fn` is invoked
 * synchronously and no queuing occurs. This prevents test-environment hangs
 * and keeps SSR rendering correct.
 */

// builder-audit #338 SYNC-09 (single-builder-instance assumption): `pending` is a
// process-global map keyed ONLY by the coalesce key (e.g. `paint:${layerId}`),
// with no map-instance discriminator. This is intentional for the current
// single-live-builder use case — exactly one BuilderMap is mounted at a time and
// `layer.id` is globally unique, and each queued fn captures its own map/input,
// so there is no cross-instance interference. If two map surfaces with
// overlapping layer ids are ever mounted concurrently (e.g. a builder plus an
// embedded preview), their writes would last-write-wins clobber on the shared
// frame; in that case include a map-instance discriminator in the coalesce key.
const pending = new Map<string, () => void>();
let rafHandle: number | null = null;

function flush(): void {
  rafHandle = null;
  // Snapshot and clear before iterating so that any coalesceFrame call
  // inside a flush fn schedules a NEW frame (not the current one).
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
 * Queue `fn` to run on the next animation frame under the given `key`.
 *
 * Calling `coalesceFrame('paint:layerA', fn1)` followed by
 * `coalesceFrame('paint:layerA', fn2)` within the same frame results in
 * ONLY `fn2` being called (last-write-wins).
 *
 * Calling `coalesceFrame('paint:layerA', fn1)` AND
 * `coalesceFrame('paint:layerB', fn2)` results in BOTH being called (different
 * keys do not coalesce with each other).
 */
export function coalesceFrame(key: string, fn: () => void): void {
  // SSR / test-environment fallback: invoke synchronously if rAF not available
  if (typeof requestAnimationFrame === 'undefined') {
    fn();
    return;
  }

  // Last write wins — overwrite any previously queued fn for this key
  pending.set(key, fn);

  // Schedule a single rAF flush if one isn't already scheduled
  if (rafHandle === null) {
    rafHandle = requestAnimationFrame(flush);
  }
}

// ---------------------------------------------------------------------------
// Test-only introspection helpers (harmless in production — tree-shakeable)
// ---------------------------------------------------------------------------

/** Returns the current pending map (read-only view). Useful in tests to assert
 *  the map is non-empty between `coalesceFrame` and the rAF tick. */
export function __getPendingForTest(): ReadonlyMap<string, () => void> {
  return pending;
}

/** Synchronously flushes all pending entries, simulating what the rAF callback
 *  would do. Useful when vitest cannot advance rAF timers. */
export function __flushForTest(): void {
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle);
    rafHandle = null;
  }
  flush();
}

/** Cancels any scheduled rAF and clears the pending map without executing fns.
 *  Useful in afterEach() cleanup. */
export function __resetForTest(): void {
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle);
    rafHandle = null;
  }
  pending.clear();
}

// ---------------------------------------------------------------------------
// HMR dispose hook (WR-06)
// During Vite hot-module-replacement, cancel any pending rAF so the old
// module's flush() does not fire stale callbacks after the module is replaced.
// This is a no-op in production builds (import.meta.hot is undefined).
// ---------------------------------------------------------------------------
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
    }
    pending.clear();
  });
}
