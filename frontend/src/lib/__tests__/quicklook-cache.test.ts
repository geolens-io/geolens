import { afterEach, describe, expect, it } from 'vitest';
import {
  isQuicklookKnownMissing,
  markQuicklookMissing,
  _resetQuicklookCache,
} from '@/lib/quicklook-cache';

describe('quicklook-cache (SP-07)', () => {
  afterEach(() => {
    _resetQuicklookCache();
  });

  it('returns false for an id that has not 404d this session', () => {
    expect(isQuicklookKnownMissing('dataset-fresh')).toBe(false);
  });

  it('returns true after markQuicklookMissing for the same id', () => {
    markQuicklookMissing('dataset-broken');
    expect(isQuicklookKnownMissing('dataset-broken')).toBe(true);
  });

  it('does not affect unrelated ids', () => {
    markQuicklookMissing('a');
    expect(isQuicklookKnownMissing('a')).toBe(true);
    expect(isQuicklookKnownMissing('b')).toBe(false);
  });

  it('persists across an in-memory cache drop via sessionStorage', async () => {
    // Mark, then reach in and only blow away the module-level memory cache.
    // The next read must rebuild from sessionStorage.
    markQuicklookMissing('persisted');

    // Re-import the module fresh by clearing only the memory cache state.
    // We use Vite's ESM `import` here against the same path so the module's
    // module-level `memoryCache` variable is the same instance. To prove the
    // sessionStorage roundtrip, we simulate a fresh page-load: dynamically
    // re-import via vi.resetModules() so the module is reinitialized but
    // sessionStorage (jsdom singleton) carries the prior state.
    const { vi } = await import('vitest');
    vi.resetModules();
    const fresh = await import('@/lib/quicklook-cache');
    expect(fresh.isQuicklookKnownMissing('persisted')).toBe(true);
  });

  it('_resetQuicklookCache clears both memory and sessionStorage', () => {
    markQuicklookMissing('to-be-cleared');
    expect(isQuicklookKnownMissing('to-be-cleared')).toBe(true);

    _resetQuicklookCache();

    expect(isQuicklookKnownMissing('to-be-cleared')).toBe(false);
    expect(window.sessionStorage.getItem('geolens-quicklook-404')).toBeNull();
  });

  it('is idempotent when marking the same id twice', () => {
    markQuicklookMissing('dup');
    markQuicklookMissing('dup');
    expect(isQuicklookKnownMissing('dup')).toBe(true);
  });
});
