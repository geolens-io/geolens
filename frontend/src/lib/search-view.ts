import { DEFAULT_PAGE_SIZE } from '@/lib/constants';
import { readStorage, storageKeys, writeStorage } from '@/lib/storage';

export type SearchResultDensity = 'comfortable' | 'compact';

const COMPACT_PAGE_SIZE = 25;

// Storage may be unavailable, so the last view chosen this session is kept in
// memory and storage only seeds and persists it.
let chosenDensity: SearchResultDensity | null = null;

export function readStoredDensity(): SearchResultDensity {
  if (chosenDensity) return chosenDensity;
  return readStorage(storageKeys.searchView) === 'compact' ? 'compact' : 'comfortable';
}

export function storeDensity(density: SearchResultDensity): void {
  chosenDensity = density;
  writeStorage(storageKeys.searchView, density);
}

/** Test-only: forget the view chosen in memory. */
export function _resetChosenDensity(): void {
  chosenDensity = null;
}

export function pageSizeFor(density: SearchResultDensity): number {
  return density === 'compact' ? COMPACT_PAGE_SIZE : DEFAULT_PAGE_SIZE;
}

/** Page size of the remembered result view; the search store starts from it. */
export function storedPageSize(): number {
  return pageSizeFor(readStoredDensity());
}
