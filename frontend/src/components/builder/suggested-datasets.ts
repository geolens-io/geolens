/**
 * Hand-curated suggested datasets (BSR-19).
 *
 * Replace placeholder UUIDs with real catalog UUIDs per deployment.
 * IDs must be valid UUID v4 (8-4-4-4-12 hex). Cards whose IDs 404 are
 * silently hidden — no broken UI. Cards whose IDs are not valid UUIDs
 * never fire an API call (no 422 noise).
 *
 * This module MUST NOT import from any backend module or perform any
 * runtime I/O. It is a pure client-side constant used by EmptyStackState
 * to populate the suggested dataset list when the layer stack is empty.
 */

export interface SuggestedDataset {
  id: string;
  name: string;
  record_type: 'vector_dataset' | 'raster_dataset' | 'vrt_dataset';
  geometry_type?: string;
  feature_count?: number;
  crs?: string;
}

/**
 * Ships empty by default. Operators populate per deployment with real
 * catalog UUIDs (e.g. via a follow-up branch overriding this file).
 *
 * Until populated, the empty-state still renders the heading + inline
 * search + "Browse all datasets" link — just no suggestion cards. This
 * prevents broken-cards UX and avoids any 404 network noise on a fresh
 * install where suggestions have not yet been curated.
 */
export const SUGGESTED_DATASETS: SuggestedDataset[] = [];
