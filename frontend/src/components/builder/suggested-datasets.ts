/**
 * Hand-curated suggested datasets (BSR-19).
 *
 * Replace placeholder IDs with real catalog UUIDs per deployment.
 * Cards whose IDs 404 are silently hidden — no broken UI.
 *
 * This module MUST NOT import from any backend module or perform any runtime I/O.
 * It is a pure client-side constant used by EmptyStackState to populate the
 * suggested dataset list when the layer stack is empty.
 */

export interface SuggestedDataset {
  id: string;
  name: string;
  record_type: 'vector_dataset' | 'raster_dataset' | 'vrt_dataset';
  geometry_type?: string;
  feature_count?: number;
  crs?: string;
}

export const SUGGESTED_DATASETS: SuggestedDataset[] = [
  {
    id: '__placeholder-1',
    name: 'World Countries',
    record_type: 'vector_dataset',
    geometry_type: 'MultiPolygon',
    feature_count: 195,
    crs: 'EPSG:4326',
  },
  {
    id: '__placeholder-2',
    name: 'World Cities',
    record_type: 'vector_dataset',
    geometry_type: 'Point',
    feature_count: 7343,
    crs: 'EPSG:4326',
  },
  {
    id: '__placeholder-3',
    name: 'Land Cover',
    record_type: 'raster_dataset',
    crs: 'EPSG:4326',
  },
  {
    id: '__placeholder-4',
    name: 'Elevation Model',
    record_type: 'raster_dataset',
    crs: 'EPSG:4326',
  },
];
