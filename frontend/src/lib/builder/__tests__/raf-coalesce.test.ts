import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  coalesceFrame,
  __getPendingForTest,
  __flushForTest,
  __resetForTest,
} from '../raf-coalesce';

// ---------------------------------------------------------------------------
// rAF mock helpers
// ---------------------------------------------------------------------------

type RafCallback = (time: number) => void;

function mockRaf() {
  let _handle = 0;
  const _queue = new Map<number, RafCallback>();

  const requestAnimationFrame = vi.fn((cb: RafCallback): number => {
    const handle = ++_handle;
    _queue.set(handle, cb);
    return handle;
  });

  const cancelAnimationFrame = vi.fn((handle: number): void => {
    _queue.delete(handle);
  });

  function flush(time = 0): void {
    const entries = Array.from(_queue.entries());
    _queue.clear();
    for (const [, cb] of entries) {
      cb(time);
    }
  }

  return { requestAnimationFrame, cancelAnimationFrame, flush };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('coalesceFrame', () => {
  let raf: ReturnType<typeof mockRaf>;

  beforeEach(() => {
    __resetForTest();
    raf = mockRaf();
    vi.stubGlobal('requestAnimationFrame', raf.requestAnimationFrame);
    vi.stubGlobal('cancelAnimationFrame', raf.cancelAnimationFrame);
  });

  afterEach(() => {
    __resetForTest();
    vi.unstubAllGlobals();
  });

  // -------------------------------------------------------------------------
  // Test 1: Same key called N times collapses to 1 call (last value wins)
  // -------------------------------------------------------------------------
  it('Test 1: 10 calls with the same key inside one frame produce exactly 1 flush (last fn wins)', () => {
    const calls: number[] = [];

    for (let i = 0; i < 10; i++) {
      const value = i;
      coalesceFrame('paint:layer-a', () => calls.push(value));
    }

    // Before flush: pending map has 1 entry (last write won)
    expect(__getPendingForTest().size).toBe(1);
    // rAF was scheduled exactly once
    expect(raf.requestAnimationFrame).toHaveBeenCalledTimes(1);

    // Flush the rAF
    raf.flush();

    // After flush: exactly 1 call, with the LAST value (9)
    expect(calls).toHaveLength(1);
    expect(calls[0]).toBe(9);
    // Pending map is now empty
    expect(__getPendingForTest().size).toBe(0);
  });

  // -------------------------------------------------------------------------
  // Test 2: Different keys do NOT coalesce — both fire on the next tick
  // -------------------------------------------------------------------------
  it('Test 2: different keys both fire on the same rAF tick', () => {
    const resultA: string[] = [];
    const resultB: string[] = [];

    coalesceFrame('paint:layer-a', () => resultA.push('A'));
    coalesceFrame('paint:layer-b', () => resultB.push('B'));

    // One shared rAF scheduled (not two)
    expect(raf.requestAnimationFrame).toHaveBeenCalledTimes(1);
    // Both are in the pending map
    expect(__getPendingForTest().size).toBe(2);

    raf.flush();

    expect(resultA).toEqual(['A']);
    expect(resultB).toEqual(['B']);
  });

  // -------------------------------------------------------------------------
  // Test 3: After the rAF tick fires, new calls schedule a NEW rAF (no sticking)
  // -------------------------------------------------------------------------
  it('Test 3: after flush, subsequent coalesceFrame calls schedule a new rAF', () => {
    const calls: string[] = [];

    coalesceFrame('paint:layer-a', () => calls.push('first-frame'));
    raf.flush();

    expect(calls).toEqual(['first-frame']);
    expect(__getPendingForTest().size).toBe(0);
    // The rAF mock was called once for the first frame
    expect(raf.requestAnimationFrame).toHaveBeenCalledTimes(1);

    // Queue a second frame
    coalesceFrame('paint:layer-a', () => calls.push('second-frame'));
    // A NEW rAF should have been scheduled
    expect(raf.requestAnimationFrame).toHaveBeenCalledTimes(2);

    raf.flush();
    expect(calls).toEqual(['first-frame', 'second-frame']);
  });

  // -------------------------------------------------------------------------
  // Test 4: SSR / no-rAF fallback — invoke fn synchronously
  // -------------------------------------------------------------------------
  it('Test 4: invokes fn synchronously when requestAnimationFrame is undefined (SSR/no-rAF env)', () => {
    // Remove rAF to simulate SSR environment
    vi.stubGlobal('requestAnimationFrame', undefined);

    const calls: string[] = [];
    coalesceFrame('paint:layer-a', () => calls.push('sync-call'));

    // Must have fired synchronously — no need to flush
    expect(calls).toEqual(['sync-call']);
  });

  // -------------------------------------------------------------------------
  // Test 5: __getPendingForTest() is non-empty pre-tick, empty post-tick
  // -------------------------------------------------------------------------
  it('Test 5: pending map is non-empty before flush and empty after flush', () => {
    coalesceFrame('paint:layer-x', () => {});

    // Pre-tick: pending has 1 entry
    const preTick = __getPendingForTest();
    expect(preTick.size).toBe(1);
    expect(preTick.has('paint:layer-x')).toBe(true);

    raf.flush();

    // Post-tick: pending is empty
    const postTick = __getPendingForTest();
    expect(postTick.size).toBe(0);
  });

  // -------------------------------------------------------------------------
  // Bonus: __flushForTest() flushes synchronously without needing rAF mock
  // -------------------------------------------------------------------------
  it('__flushForTest() synchronously flushes pending entries', () => {
    const calls: string[] = [];
    coalesceFrame('key-1', () => calls.push('k1'));
    coalesceFrame('key-2', () => calls.push('k2'));

    expect(__getPendingForTest().size).toBe(2);

    __flushForTest();

    expect(calls).toHaveLength(2);
    expect(calls).toContain('k1');
    expect(calls).toContain('k2');
    expect(__getPendingForTest().size).toBe(0);
  });
});
