import type { MapLayerResponse } from '@/types/api';

// ux(#720): analysis needs a VECTOR dataset. `!is_dem` alone let ordinary
// raster layers (COG orthophotos, Sentinel scenes) through — they carry a
// dataset_id, so the panel offered them and auto-selected the first one, and
// every Preview 422'd.
//
// Keyed on dataset_record_type, NOT layer_type (fix(#720 review)). layer_type
// selects a RENDERER and the API validates it against nothing — MapLayerInput
// accepts any supported value and add_layer persists it, defaulting to
// 'vector_geolens'. So a raster dataset can carry the vector default, which is
// how getLayerCapabilities (which keys on layer_type) would misclassify it, and
// a vector dataset overridden to the raster renderer would be hidden even
// though the analysis endpoint accepts it. record_type is what the data IS.
//
// geometry_type is required on top of that: it is the precondition
// _load_vector_dataset enforces server-side, so a vector dataset missing one
// would 422 just the same. Testing it ALONE was the original bug — it happened
// to work only because every raster dataset currently stores NULL there, an
// incidental property of the ingest path rather than an invariant.
//
// ux(#772): extracted from AnalysisPanel.tsx so the stack-row kebab can gate
// its "Analyze this layer" entry on the same predicate without statically
// importing the lazy-loaded panel chunk.
const RASTER_RECORD_TYPES = new Set(['raster_dataset', 'vrt_dataset']);
export const isAnalysableLayer = (l: MapLayerResponse) =>
  !!l.dataset_id &&
  !l.is_dem &&
  !RASTER_RECORD_TYPES.has((l.dataset_record_type ?? '').toLowerCase()) &&
  !!l.dataset_geometry_type;
