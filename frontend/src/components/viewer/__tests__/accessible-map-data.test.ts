import { describe, expect, it } from 'vitest';
import type { MapGeoJSONFeature } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';
import { toAccessibleMapFeatures } from '../accessible-map-data';

function makeLayer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Roads',
    display_name: 'Public roads',
    table_name: 'roads',
    geometry_type: 'LINESTRING',
    column_info: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: { enabled: true, expression: '{name}', visible_fields: ['name', 'speed'] },
    style_config: null,
    tile_url: '',
    ...overrides,
  };
}

function makeFeature(overrides: Partial<MapGeoJSONFeature> = {}): MapGeoJSONFeature {
  return {
    type: 'Feature',
    id: 7,
    geometry: {
      type: 'LineString',
      coordinates: [[-76.5, 39.1], [-75.2, 40.4]],
    },
    properties: {
      name: 'Market Street',
      speed: 25,
      geometry: 'must stay hidden',
      _internal: 'must stay hidden',
      secret: 'not allowlisted',
    },
    source: 'viewer-source-layer-1',
    sourceLayer: 'roads',
    state: {},
    layer: {
      id: 'viewer-layer-layer-1',
      type: 'line',
      source: 'viewer-source-layer-1',
    },
    ...overrides,
  } as MapGeoJSONFeature;
}

describe('toAccessibleMapFeatures', () => {
  it('provides a de-duplicated geometry and public-attribute alternative', () => {
    const layer = makeLayer();
    const feature = makeFeature();
    const result = toAccessibleMapFeatures(
      [feature, feature],
      (mapLayerId) => mapLayerId === 'viewer-layer-layer-1' ? layer : null,
    );

    expect(result).toEqual({
      total: 1,
      truncated: false,
      features: [{
        key: 'viewer-source-layer-1:roads:7',
        layerName: 'Public roads',
        title: 'Market Street',
        clusterCount: null,
        geometryType: 'LineString',
        bounds: [-76.5, 39.1, -75.2, 40.4],
        properties: [['name', 'Market Street'], ['speed', 25]],
      }],
    });
  });

  it('excludes basemap/unmanaged features and honors disabled popups', () => {
    const disabledLayer = makeLayer({
      popup_config: { enabled: false, expression: null, visible_fields: null },
    });
    const result = toAccessibleMapFeatures(
      [makeFeature(), makeFeature({ layer: { id: 'basemap-road', type: 'line', source: 'basemap' } })],
      (mapLayerId) => mapLayerId === 'viewer-layer-layer-1' ? disabledLayer : null,
    );

    expect(result.features).toHaveLength(1);
    expect(result.features[0].properties).toEqual([]);
  });

  it('caps the DOM-facing result while reporting the full unique count', () => {
    const layer = makeLayer();
    const features = Array.from({ length: 4 }, (_, id) => makeFeature({ id }));
    const result = toAccessibleMapFeatures(features, () => layer, 2);

    expect(result.features).toHaveLength(2);
    expect(result.total).toBe(4);
    expect(result.truncated).toBe(true);
  });

  it('merges tile-split geometry fragments into one complete extent', () => {
    const layer = makeLayer();
    const westFragment = makeFeature({
      geometry: { type: 'LineString', coordinates: [[-76.5, 39.1], [-76, 39.5]] },
    });
    const eastFragment = makeFeature({
      geometry: { type: 'LineString', coordinates: [[-76, 39.5], [-75.2, 40.4]] },
    });

    const result = toAccessibleMapFeatures([westFragment, eastFragment], () => layer);

    expect(result.total).toBe(1);
    expect(result.features[0].bounds).toEqual([-76.5, 39.1, -75.2, 40.4]);
  });

  it('keeps the aggregate count for rendered clusters outside popup allowlists', () => {
    const layer = makeLayer({
      column_info: [{ name: 'name', type: 'text' }],
      popup_config: { enabled: true, expression: null, visible_fields: ['name'] },
    });
    const cluster = makeFeature({
      properties: { point_count: 314, point_count_abbreviated: '314' },
      geometry: { type: 'Point', coordinates: [-76.5, 39.1] },
    });

    const result = toAccessibleMapFeatures([cluster], () => layer);

    expect(result.features[0].clusterCount).toBe(314);
    expect(result.features[0].properties).toEqual([]);
  });
});
