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
