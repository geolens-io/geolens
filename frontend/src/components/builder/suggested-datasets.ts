/**
 * Hand-curated suggested datasets.
 *
 * Replace placeholder UUIDs with real catalog UUIDs per deployment. IDs must be
 * valid UUID v4 (8-4-4-4-12 hex). Cards whose IDs 404 are silently hidden, and
 * IDs that aren't valid UUIDs never fire an API call (no 422 noise).
 *
 * A pure client-side constant used by EmptyStackState: no backend imports, no
 * runtime I/O.
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
 * Ships empty by default; operators populate per deployment with real catalog
 * UUIDs.
 *
 * Until populated, the empty state still renders the heading, inline search and
 * "Browse all datasets" link, just no suggestion cards, which avoids broken
 * cards and 404 network noise on a fresh install.
 */
export const SUGGESTED_DATASETS: SuggestedDataset[] = [];
