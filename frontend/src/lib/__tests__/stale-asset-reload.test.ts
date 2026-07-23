// fix(#645): the reload latch must fire once, block rapid repeats, and allow
// a later retry after the window expires — otherwise a broken build loops.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { installStaleAssetReload, reloadOnceForStaleAssets } from '../stale-asset-reload';

const reload = vi.fn();

beforeEach(() => {
  sessionStorage.clear();
  reload.mockClear();
  Object.defineProperty(window, 'location', {
    value: { ...window.location, reload },
    writable: true,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('reloadOnceForStaleAssets', () => {
  it('reloads on first call and latches against immediate repeats', () => {
    expect(reloadOnceForStaleAssets()).toBe(true);
    expect(reloadOnceForStaleAssets()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('allows another reload after the latch window expires', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    expect(reloadOnceForStaleAssets()).toBe(true);
    vi.setSystemTime(1_000_000 + 31_000);
    expect(reloadOnceForStaleAssets()).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });
});

describe('installStaleAssetReload', () => {
  it('reloads and suppresses the throw on vite:preloadError', () => {
    installStaleAssetReload();
    const event = new Event('vite:preloadError', { cancelable: true });
    window.dispatchEvent(event);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it('does not preventDefault when latched (error surfaces normally)', () => {
    sessionStorage.setItem('geolens-asset-reload-at', String(Date.now()));
    installStaleAssetReload();
    const event = new Event('vite:preloadError', { cancelable: true });
    window.dispatchEvent(event);
    expect(reload).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });
});
