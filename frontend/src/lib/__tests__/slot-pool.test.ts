import { abortableDelay } from '@/lib/abort';
import { createSlotPool } from '@/lib/slot-pool';

describe('createSlotPool', () => {
  it('holds at most max slots and hands a released one to the next waiter', async () => {
    const pool = createSlotPool(1);
    const first = await pool.acquire();
    let second = false;
    const waiter = pool.acquire().then((release) => {
      second = true;
      return release;
    });
    await Promise.resolve();
    expect(second).toBe(false);

    first();
    first(); // A second release of the same slot frees nothing more.
    const release = await waiter;
    expect(second).toBe(true);
    let third = false;
    void pool.acquire().then(() => {
      third = true;
    });
    await Promise.resolve();
    expect(third).toBe(false);
    release();
  });

  it('drops a waiter whose signal aborts', async () => {
    const pool = createSlotPool(1);
    const held = await pool.acquire();
    const controller = new AbortController();
    const waiter = pool.acquire(controller.signal);
    controller.abort(new Error('gave up'));
    await expect(waiter).rejects.toThrow('gave up');

    held();
    // The aborted waiter took nothing, so the slot is free.
    await expect(pool.acquire()).resolves.toBeTypeOf('function');
  });
});

describe('abortableDelay', () => {
  it('rejects with the reason when the signal aborts mid-wait', async () => {
    const controller = new AbortController();
    const wait = abortableDelay(60_000, controller.signal);
    controller.abort(new Error('stop'));
    await expect(wait).rejects.toThrow('stop');
    await expect(abortableDelay(10, controller.signal)).rejects.toThrow('stop');
  });
});
