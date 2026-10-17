import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useExpiryClock } from '../use-expiry-clock';

const MAX_TIMEOUT_MS = 2 ** 31 - 1;
const NOW = new Date('2026-01-10T12:00:00Z');

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

it('schedules a far-future expiry within the timer limit and does not spin', () => {
  const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
  const inThirtyDays = new Date(NOW.getTime() + 30 * 86_400_000).toISOString();

  renderHook(() => useExpiryClock([inThirtyDays]));

  expect(setTimeoutSpy).toHaveBeenCalledTimes(1);
  expect(setTimeoutSpy.mock.calls[0][1]).toBeLessThanOrEqual(MAX_TIMEOUT_MS);

  act(() => {
    vi.advanceTimersByTime(5_000);
  });

  expect(setTimeoutSpy).toHaveBeenCalledTimes(1);
});
