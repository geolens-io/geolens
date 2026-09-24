import type { RecordType } from '@/types/api';

/** What the catalog serves for a dataset of one record type. */
export interface RecordTypeCapabilities {
  /** A PostGIS table backs feature reads and writes, OGC items, export, rows and column changes. */
  featureTable: boolean;
  /** How the dataset renders as a map layer; null when it cannot be one. */
  mapLayerType: 'vector_geolens' | 'raster_geolens' | null;
  /** Which tiles the dataset serves; null when it has none. */
  tileToken: 'vector' | 'raster' | null;
}

const VECTOR: RecordTypeCapabilities = {
  featureTable: true,
  mapLayerType: 'vector_geolens',
  tileToken: 'vector',
};

const RASTER: RecordTypeCapabilities = {
  featureTable: false,
  mapLayerType: 'raster_geolens',
  tileToken: 'raster',
};

const UNSUPPORTED: RecordTypeCapabilities = {
  featureTable: false,
  mapLayerType: null,
  tileToken: null,
};

/**
 * The frontend copy of `_CAPABILITIES` in backend/app/core/record_types.py,
 * pinned to it through `record-type-capabilities.cases.json`.
 */
export const RECORD_TYPE_CAPABILITIES: Record<RecordType, RecordTypeCapabilities> = {
  vector_dataset: VECTOR,
  raster_dataset: RASTER,
  vrt_dataset: RASTER,
  map: VECTOR,
  service: VECTOR,
  collection: VECTOR,
  table: VECTOR,
  tiles3d_dataset: UNSUPPORTED,
};

/** Capabilities of `recordType`; an unknown or missing value has none. */
export function recordTypeCapabilities(
  recordType: string | null | undefined,
): RecordTypeCapabilities {
  if (!recordType || !Object.prototype.hasOwnProperty.call(RECORD_TYPE_CAPABILITIES, recordType)) {
    return UNSUPPORTED;
  }
  return RECORD_TYPE_CAPABILITIES[recordType as RecordType];
}
