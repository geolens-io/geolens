import { DEFAULT_PAGE_SIZE } from '@/lib/constants';
import { readStorage, storageKeys } from '@/lib/storage';

export type SearchResultDensity = 'comfortable' | 'compact';

export const COMPACT_PAGE_SIZE = 25;

export function readStoredDensity(): SearchResultDensity {
  return readStorage(storageKeys.searchView) === 'compact' ? 'compact' : 'comfortable';
}

export function pageSizeFor(density: SearchResultDensity): number {
  return density === 'compact' ? COMPACT_PAGE_SIZE : DEFAULT_PAGE_SIZE;
}

/** Page size of the remembered result view; the search store starts from it. */
export function storedPageSize(): number {
  return pageSizeFor(readStoredDensity());
}
