/**
 * fix(#438): ARC-06 — a thin, exception-safe, typed home for the `geolens-*`
 * localStorage keys that were previously written as bare string literals
 * scattered across pages. Persisted store state (zustand) keeps its own
 * `persist` config; this is for the ad-hoc view/notes/preference keys.
 *
 * Every access is wrapped: private-mode Safari and storage-disabled browsers
 * throw on access, and a UI preference is never worth crashing a page over.
 */

/** Canonical key builders — the one place these strings are spelled. */
export const storageKeys = {
  mapsView: 'geolens-maps-view',
  mapNotes: (mapId: string) => `geolens-map-notes-${mapId}`,
} as const;

export function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // storage unavailable (private mode / disabled) — a UI preference is not
    // worth surfacing an error for.
  }
}

export function removeStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // storage unavailable — ignore.
  }
}

/**
 * fix(#1515): sessionStorage counterpart, for the same reason the file exists.
 *
 * A `typeof sessionStorage !== 'undefined'` check does NOT make a read safe:
 * the property exists, and it is reading it that raises. In a frame with an
 * opaque origin (sandboxed without `allow-same-origin`) the getter throws
 * `SecurityError`, so a caller reading during render takes the whole page
 * down rather than losing one preference.
 */
/**
 * fix(#1535 codex P1): in-memory mirror for the session keys.
 *
 * Not throwing is not the same as working. `gl-guest-browse` is written by the
 * "Browse the catalog" button and read back by `LandingFirstGuard` one
 * navigation later; a write that silently no-ops leaves the guard bouncing the
 * visitor straight to /login, which is indistinguishable from a dead button in
 * the one environment these helpers exist for.
 *
 * Scope of the mirror is this page's lifetime, not the tab session: a full
 * reload loses it, because in a storage-denied context there is nowhere to
 * persist. That is the cost, and it is accepted. It also means the OAuth
 * round-trip (a full document load) still cannot carry `geolens-login-redirect`
 * through denied storage, so that path degrades to "/" as before.
 */
const memoryFallback = new Map<string, string>();

/** Test-only: drop the mirror between cases (cf. `_resetQuicklookCache`). */
export function _resetSessionStorageFallback(): void {
  memoryFallback.clear();
}

export function readSessionStorage(key: string): string | null {
  try {
    const stored = sessionStorage.getItem(key);
    if (stored !== null) return stored;
  } catch {
    // Denied: fall through to the mirror.
  }
  // A successful read returning null also lands here. That is the full-store
  // case: `writeSessionStorage` clears the key when its write fails, precisely
  // so the read reaches this line instead of returning a stale value.
  return memoryFallback.get(key) ?? null;
}

/**
 * fix(#1527): writing is denied in exactly the same contexts reading is, and
 * for the same reason — the property access raises before `setItem` is ever
 * reached. Guarding only `readSessionStorage` covers half the surface: on the
 * auth path most of these accesses are writes (the login-redirect key, the
 * guest-browse marker), several of them during render or inside a click
 * handler where the throw is a blank page rather than a lost preference.
 */
export function writeSessionStorage(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
    // The store is authoritative once it accepts the value; drop any stale
    // mirror entry so the two cannot diverge.
    memoryFallback.delete(key);
    return;
  } catch {
    // Denied (opaque origin / private mode) or full (quota). Keep it in memory
    // so a reader one navigation later still sees the caller's intent.
    memoryFallback.set(key, value);
  }

  // fix(#1535 codex P2): the write failed, so whatever was persisted under
  // this key BEFORE is now stale — and it would win, because the read prefers
  // a non-null store value and only then consults the mirror. Worse, it
  // outlives the mirror: the OAuth round trip is a full document load, so
  // `OAuthCallbackPage` would read a route the user has already navigated
  // away from and send them there.
  //
  // Drop it, so a post-reload read finds nothing and the caller degrades to
  // "/" instead of to something false. Only the full-store case has anything
  // to clear; a denied store never persisted a value, so this throws and the
  // catch is the whole handling.
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Denied: nothing was ever persisted, so nothing can be stale.
  }
}

export function removeSessionStorage(key: string): void {
  memoryFallback.delete(key);
  try {
    sessionStorage.removeItem(key);
  } catch {
    // storage unavailable — nothing was persisted, so nothing needs clearing.
  }
}
