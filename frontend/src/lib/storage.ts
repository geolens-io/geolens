/**
 * Exception-safe, typed access for ad hoc `geolens-*` view, note, and
 * preference keys. Persisted Zustand state owns its own storage configuration.
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
 * Exception-safe sessionStorage mirror for opaque origins and quota failures.
 * The mirror preserves navigation intent within the current document; a full
 * OAuth reload cannot preserve it and therefore falls back to the root route.
 */
const memoryFallback = new Map<string, string>();

/** Test-only: drop the mirror between cases. */
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

/** Guard property access as well as setItem because either may throw. */
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

  // Remove any stale persisted value that would outrank the mirror and survive
  // an OAuth reload. A denied store has nothing to remove and throws safely.
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
