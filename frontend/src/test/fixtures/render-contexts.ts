import type { RenderContext } from '@/components/builder/layer-description';
import { VIEWER_PREFIX } from '@/components/viewer/viewer-query-layer-ids';
import { SAVED_LAYERS } from './saved-layers';

const boundedClusterData = new Map<string, GeoJSON.FeatureCollection>([
  [SAVED_LAYERS.boundedCluster.id, { type: 'FeatureCollection', features: [] }],
]);

/** The builder and viewer render contexts, before and after the bounded cluster's GeoJSON loads. */
export const RENDER_CONTEXTS = {
  builder: { idPrefix: '', boundedGeoJson: new Map() },
  builderWithClusterData: { idPrefix: '', boundedGeoJson: boundedClusterData },
  viewer: { idPrefix: VIEWER_PREFIX, boundedGeoJson: new Map() },
  viewerWithClusterData: { idPrefix: VIEWER_PREFIX, boundedGeoJson: boundedClusterData },
} satisfies Record<string, RenderContext>;
