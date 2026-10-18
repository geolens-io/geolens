import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import type { MapLayerResponse } from '@/types/api';

// Analysis needs a vector dataset. `!is_dem` alone let ordinary raster layers
// (COG orthophotos, Sentinel scenes) through: they carry a dataset_id, so the
// panel offered and auto-selected one and every Preview 422'd.
//
// Keyed on dataset_record_type, not layer_type. layer_type selects a renderer
// and the API validates it against nothing (MapLayerInput accepts any supported
// value and add_layer defaults it to 'vector_geolens'), so a raster dataset can
// carry the vector default, which getLayerCapabilities (keyed on layer_type)
// would misclassify, and a vector dataset overridden to the raster renderer
// would be hidden though the analysis endpoint accepts it. record_type is what
// the data is.
//
// geometry_type is required on top: it is the precondition
// _load_vector_dataset enforces server-side, so a vector dataset missing one
// would 422 too. Testing it alone worked only because every raster dataset
// currently stores NULL there, an incidental property of the ingest path.
//
// Extracted from AnalysisPanel.tsx so the stack-row kebab can gate "Analyze this
// layer" on the same predicate without statically importing the lazy-loaded
// panel chunk.
//
// A folder-group row is built as a copy of its first child, so it carries that
// child's dataset_id and geometry type; it is a container, not a dataset.
const RASTER_RECORD_TYPES = new Set(['raster_dataset', 'vrt_dataset']);
export const isAnalysableLayer = (l: MapLayerResponse) =>
  !isFolderGroupLayer(l) &&
  !!l.dataset_id &&
  !l.is_dem &&
  !RASTER_RECORD_TYPES.has((l.dataset_record_type ?? '').toLowerCase()) &&
  !!l.dataset_geometry_type;
