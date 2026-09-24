import type { RasterTileToken, TileToken, VectorTileToken } from '@/api/tiles';
import type { RenderContext } from '@/components/builder/layer-description';
import { VIEWER_PREFIX } from '@/components/viewer/viewer-query-layer-ids';
import type { MapLayerResponse } from '@/types/api';
import { SAVED_LAYERS } from './saved-layers';

export const FIXTURE_ORIGIN = 'https://maps.example.test';

/** A signed tile token for a saved layer's dataset, of the kind its record type gets. */
export function fixtureToken(layer: MapLayerResponse): TileToken {
  const sig = `sig-${layer.dataset_id}`;
  const scope = `scope-${layer.dataset_id}`;
  if (layer.dataset_record_type === 'raster_dataset') {
    return {
      kind: 'raster',
      tile_url: `/raster-tiles/${layer.dataset_id}/tiles/{z}/{x}/{y}.png?sig=${sig}&exp=2000000000&scope=${scope}`,
      sig,
      exp: 2000000000,
      scope,
      expires_in: 900,
      bounds: [-74.1, 40.6, -73.8, 40.9],
      minzoom: 0,
      maxzoom: 19,
      tile_size: 256,
      format: 'png',
    } satisfies RasterTileToken;
  }
  return { kind: 'vector', sig, exp: 2000000000, scope, expires_in: 900 } satisfies VectorTileToken;
}

/** A token for every shared fixture's dataset. */
export const FIXTURE_TOKENS: ReadonlyMap<string, TileToken> = new Map(
  Object.values(SAVED_LAYERS).map((layer) => [layer.dataset_id, fixtureToken(layer)]),
);

const boundedClusterData = new Map<string, GeoJSON.FeatureCollection>([
  [SAVED_LAYERS.boundedCluster.id, { type: 'FeatureCollection', features: [] }],
]);

const shared = {
  origin: FIXTURE_ORIGIN,
  tileBaseUrl: undefined,
  sourceLayerPrefix: 'data',
  tokens: FIXTURE_TOKENS,
};

/** The builder and viewer render contexts, before and after the bounded cluster's GeoJSON loads. */
export const RENDER_CONTEXTS = {
  builder: { ...shared, idPrefix: '', boundedGeoJson: new Map() },
  builderWithClusterData: { ...shared, idPrefix: '', boundedGeoJson: boundedClusterData },
  viewer: { ...shared, idPrefix: VIEWER_PREFIX, boundedGeoJson: new Map() },
  viewerWithClusterData: { ...shared, idPrefix: VIEWER_PREFIX, boundedGeoJson: boundedClusterData },
} satisfies Record<string, RenderContext>;
