/**
 * fix(#1535 codex P2): the session helpers under a store that is FULL rather
 * than denied.
 *
 * These are two different failures and only one of them can strand a stale
 * value. A denied store has nothing persisted, so a failed write leaves
 * nothing behind. A full store still holds the PREVIOUS value, so replacing
 * `geolens-login-redirect` with a longer route throws while the old route
 * stays persisted and authoritative. `OAuthCallbackPage` reads it after the
 * SSO round trip (a full document load, which loses the in-memory mirror) and
 * sends the user somewhere they never asked to go.
 *
 * That is the trade this repo keeps deciding not to make: before the mirror,
 * that write threw and crashed loudly; leaving it stale would convert the
 * crash into a silent wrong destination that survives a reload. Absent beats
 * wrong here, because absent degrades to "/", which is the established
 * correct fallback for that path.
 */
import {
  readSessionStorage,
  writeSessionStorage,
  removeSessionStorage,
  _resetSessionStorageFallback,
} from '@/lib/storage';
import { denySessionStorage, limitSessionStorage } from '@/test/deny-storage';

const KEY = 'geolens-login-redirect';
const SHORT = '/a';
const LONG = '/datasets/a-much-longer-route-than-the-quota-allows';

/** A full document load: the tab's store survives, module state does not. */
function simulateReload() {
  _resetSessionStorageFallback();
}

describe('session storage helpers', () => {
  beforeEach(() => {
    sessionStorage.clear();
    _resetSessionStorageFallback();
  });

  describe('when the store works', () => {
    it('round-trips a value and clears it', () => {
      writeSessionStorage(KEY, SHORT);
      expect(readSessionStorage(KEY)).toBe(SHORT);
      removeSessionStorage(KEY);
      expect(readSessionStorage(KEY)).toBeNull();
    });

    it('survives a reload, because the store is the one that persists', () => {
      writeSessionStorage(KEY, SHORT);
      simulateReload();
      expect(readSessionStorage(KEY)).toBe(SHORT);
    });
  });

  describe('when the store is denied', () => {
    it('keeps the caller intent for this page and reports nothing after a reload', () => {
      const restore = denySessionStorage();
      try {
        writeSessionStorage(KEY, LONG);
        expect(readSessionStorage(KEY)).toBe(LONG);

        simulateReload();
        expect(readSessionStorage(KEY)).toBeNull();
      } finally {
        restore();
      }
    });

    it('removes without throwing, though nothing was ever persisted', () => {
      const restore = denySessionStorage();
      try {
        writeSessionStorage(KEY, LONG);
        expect(() => removeSessionStorage(KEY)).not.toThrow();
        expect(readSessionStorage(KEY)).toBeNull();
      } finally {
        restore();
      }
    });
  });

  describe('when the store is full', () => {
    it('does not let the old value outrank the new one in this page', () => {
      const restore = limitSessionStorage(SHORT.length);
      try {
        writeSessionStorage(KEY, SHORT);
        expect(readSessionStorage(KEY)).toBe(SHORT);

        // Too long for the quota: throws, and the old value is still sitting
        // in the store.
        writeSessionStorage(KEY, LONG);

        expect(readSessionStorage(KEY)).not.toBe(SHORT);
        expect(readSessionStorage(KEY)).toBe(LONG);
      } finally {
        restore();
      }
    });

    it('leaves no stale route behind for the OAuth round trip to read', () => {
      const restore = limitSessionStorage(SHORT.length);
      try {
        writeSessionStorage(KEY, SHORT);
        writeSessionStorage(KEY, LONG);

        simulateReload();

        // Absent, so OAuthCallbackPage degrades to "/". Returning SHORT here
        // would send the user to a route they navigated away from.
        expect(readSessionStorage(KEY)).toBeNull();
      } finally {
        restore();
      }
    });

    it('still persists a value that fits', () => {
      const restore = limitSessionStorage(SHORT.length);
      try {
        writeSessionStorage(KEY, SHORT);
        simulateReload();
        expect(readSessionStorage(KEY)).toBe(SHORT);
      } finally {
        restore();
      }
    });
  });
});
