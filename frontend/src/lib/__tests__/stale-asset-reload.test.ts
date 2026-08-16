// fix(#645): the reload latch must fire once, block rapid repeats, and allow
// a later retry after the window expires — otherwise a broken build loops.
// fix(#1515): and when the latch itself is unreachable, it must not reload at
// all — an unlatched reload IS the loop.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { installStaleAssetReload, reloadOnceForStaleAssets } from '../stale-asset-reload';

const reload = vi.fn();

/**
 * Make `sessionStorage` behave the way a sandboxed iframe without
 * allow-same-origin does: the PROPERTY ACCESS throws, it does not return null
 * or an object whose methods fail. Restored by the returned callback.
 */
function denyStorage(): () => void {
  const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
  const descriptor: PropertyDescriptor = {
    configurable: true,
    get() {
      throw new DOMException(
        "Failed to read the 'sessionStorage' property from 'Window': The document " +
          "is sandboxed and lacks the 'allow-same-origin' flag.",
        'SecurityError'
      );
    },
  };
  Object.defineProperty(window, 'sessionStorage', descriptor);
  if (globalThis !== (window as unknown as typeof globalThis)) {
    Object.defineProperty(globalThis, 'sessionStorage', descriptor);
  }
  return () => {
    if (original) {
      Object.defineProperty(window, 'sessionStorage', original);
      if (globalThis !== (window as unknown as typeof globalThis)) {
        Object.defineProperty(globalThis, 'sessionStorage', original);
      }
    }
  };
}

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

  it('does not reload at all when the latch is unreachable (#1515)', () => {
    const restore = denyStorage();
    try {
      expect(reloadOnceForStaleAssets()).toBe(false);
      expect(reloadOnceForStaleAssets()).toBe(false);
      expect(reloadOnceForStaleAssets()).toBe(false);
      expect(reload).not.toHaveBeenCalled();
    } finally {
      restore();
    }
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

  it('lets the preload error surface when the latch is unreachable (#1515)', () => {
    installStaleAssetReload();
    const restore = denyStorage();
    try {
      const event = new Event('vite:preloadError', { cancelable: true });
      window.dispatchEvent(event);
      expect(reload).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
    } finally {
      restore();
    }
  });
});
