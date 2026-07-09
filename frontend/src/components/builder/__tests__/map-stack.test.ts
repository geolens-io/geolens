import { describe, expect, it } from 'vitest';
import {
  MAP_STACK_GROUP_ORDER,
  buildMapStack,
  computeDisambiguationLabels,
  flattenMapStack,
  isLayerHiddenFromMapAudience,
  resolveTerrainSourceLayer,
  type MapStackGroup,
  type MapStackMapInput,
} from '../map-stack';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from './fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse, StyleConfig } from '@/types/api';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return makeBuilderLayer({
    dataset_name: 'Dataset',
    dataset_geometry_type: 'POLYGON',
    dataset_table_name: 'dataset',
    dataset_record_type: 'vector_dataset',
    ...overrides,
  });
}

function makeMap(overrides: Partial<MapStackMapInput> = {}): MapStackMapInput {
  const { layers = [], ...mapOverrides } = overrides;
  return makeBuilderMap(
    layers,
    {
      basemap_label: 'Positron',
      ...mapOverrides,
    } as Partial<MapResponse>,
  );
}

function group(groups: MapStackGroup[], id: MapStackGroup['id']) {
  return groups.find((item) => item.id === id);
}

describe('buildMapStack', () => {
  it('returns all stack groups and separates DEM terrain from visual relief', () => {
    const terrainLayer = makeLayer({
      id: 'dem-terrain',
      dataset_id: 'dem-1',
      dataset_name: 'Canyon DEM',
      dataset_geometry_type: null,
      dataset_table_name: 'canyon_dem',
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
      is_dem: true,
      dem_vertical_units: 'meters',
      sort_order: 0,
      style_config: { render_mode: 'terrain' } as unknown as StyleConfig,
    });
    const demLayer = makeLayer({
      id: 'dem-hillshade',
      dataset_id: 'dem-1',
      dataset_name: 'Canyon DEM',
      dataset_geometry_type: null,
      dataset_table_name: 'canyon_dem',
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
      is_dem: true,
      dem_vertical_units: 'meters',
      sort_order: 1,
      style_config: { render_mode: 'hillshade' } as StyleConfig,
    });
    const dataLayer = makeLayer({
      id: 'trails',
      dataset_id: 'trails-1',
      dataset_name: 'Trails',
      dataset_geometry_type: 'LINESTRING',
      dataset_table_name: 'trails',
      sort_order: 2,
    });

    const groups = buildMapStack(makeMap({
      terrain_config: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2.5 },
      layers: [terrainLayer, demLayer, dataLayer],
    }));
    const entries = flattenMapStack(groups);

    expect(groups.map((item) => item.id)).toEqual(MAP_STACK_GROUP_ORDER);

    const terrain = entries.find((entry) => entry.id === 'relief:terrain');
    expect(terrain).toMatchObject({
      groupId: 'relief',
      role: 'surface-terrain',
      title: 'Canyon DEM',
      visible: true,
    });
    expect(terrain?.metadata.terrain).toEqual({
      enabled: true,
      exaggeration: 2.5,
      sourceDatasetId: 'dem-1',
      sourceLayerId: 'dem-terrain',
      sourceStatus: 'active',
      verticalUnits: 'meters',
    });

    const relief = entries.find((entry) => entry.id === 'relief:dem-hillshade');
    expect(relief).toMatchObject({
      groupId: 'relief',
      role: 'relief-hillshade',
      title: 'Canyon DEM',
      orderLabel: 'Relief 1 of 1',
    });

    expect(group(groups, 'data')?.entries.map((entry) => entry.id)).toEqual(['data:trails']);
    expect(group(groups, 'surface')?.entries.map((entry) => entry.id)).toEqual(['surface:background']);
    expect(terrain!.order).toBeLessThan(relief!.order);
    expect(relief!.order).toBeLessThan(entries.find((entry) => entry.id === 'basemap:preset:positron')!.order);
    expect(entries.find((entry) => entry.id === 'data:trails')!.order).toBeGreaterThan(relief!.order);
  });

  it('does not mark stale terrain config active when the source DEM is not in Terrain mode', () => {
    const demLayer = makeLayer({
      id: 'dem-hillshade',
      dataset_id: 'dem-1',
      dataset_name: 'Canyon DEM',
      dataset_geometry_type: null,
      dataset_table_name: 'canyon_dem',
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
      is_dem: true,
      style_config: { render_mode: 'hillshade' } as StyleConfig,
    });

    const entries = flattenMapStack(buildMapStack(makeMap({
      terrain_config: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2 },
      layers: [demLayer],
    })));

    const terrain = entries.find((entry) => entry.id === 'relief:terrain');
    expect(terrain?.visible).toBe(false);
    expect(terrain?.metadata.terrain?.enabled).toBe(false);
    expect(terrain?.metadata.terrain?.sourceStatus).toBe('disabled');
  });

  it('computes stable order labels and metadata for duplicates, hidden layers, legend state, and labels', () => {
    const topLayer = makeLayer({
      id: 'counties-a',
      dataset_id: 'counties',
      dataset_name: 'Counties',
      display_name: 'Counties',
      sort_order: 0,
      visible: false,
      show_in_legend: false,
      label_config: { column: 'name' },
    });
    const bottomLayer = makeLayer({
      id: 'counties-b',
      dataset_id: 'counties',
      dataset_name: 'Counties',
      display_name: 'Counties',
      sort_order: 1,
      label_config: { column: 'name' },
    });

    const groups = buildMapStack(makeMap({ layers: [topLayer, bottomLayer] }));
    const entries = flattenMapStack(groups);
    const topData = entries.find((entry) => entry.id === 'data:counties-a');
    const bottomData = entries.find((entry) => entry.id === 'data:counties-b');

    expect(group(groups, 'data')?.entries.map((entry) => entry.id)).toEqual([
      'data:counties-b',
      'data:counties-a',
    ]);
    expect(topData).toMatchObject({
      orderLabel: 'Data 1 of 2 (top)',
      visible: false,
      metadata: {
        layerVisible: false,
        legendVisible: false,
        labelColumn: 'name',
        duplicate: {
          datasetKey: 'counties',
          datasetOccurrence: 1,
          datasetCount: 2,
          disambiguationLabel: 'Copy 1 of 2',
        },
      },
    });
    expect(topData?.badges.map((badge) => badge.label)).toEqual(
      expect.arrayContaining(['POLYGON', 'Hidden', 'Legend hidden', 'Labels', 'Copy 1 of 2']),
    );
    expect(bottomData).toMatchObject({
      orderLabel: 'Data 2 of 2 (bottom)',
      metadata: {
        duplicate: {
          datasetOccurrence: 2,
          disambiguationLabel: 'Copy 2 of 2',
        },
      },
    });

    expect(group(groups, 'labels')?.entries.map((entry) => entry.id)).toEqual([
      'labels:basemap',
      'labels:data:counties-b',
      'labels:data:counties-a',
    ]);
    expect(entries.find((entry) => entry.id === 'labels:data:counties-a')).toMatchObject({
      orderLabel: 'Data labels 2 of 2 (top)',
      visible: false,
      metadata: {
        labelColumn: 'name',
      },
    });
  });

  it('badges point symbol render mode separately from feature labels', () => {
    const layer = makeLayer({
      id: 'places',
      dataset_geometry_type: 'POINT',
      style_config: { render_mode: 'symbol' } as StyleConfig,
      label_config: { column: 'name' },
    });

    const entries = flattenMapStack(buildMapStack(makeMap({ layers: [layer] })));
    const data = entries.find((entry) => entry.id === 'data:places');

    expect(data?.badges.map((badge) => badge.label)).toEqual(
      expect.arrayContaining(['Symbols', 'Labels']),
    );
  });

  it('marks unsupported vector layers and missing terrain sources for stack row state', () => {
    const unsupportedLayer = makeLayer({
      id: 'unsupported-layer',
      dataset_geometry_type: null,
      layer_type: 'vector_geolens',
      dataset_record_type: 'vector_dataset',
    });

    const groups = buildMapStack(makeMap({
      terrain_config: { enabled: true, source_dataset_id: 'missing-dem', exaggeration: 3 },
      layers: [unsupportedLayer],
    }));
    const entries = flattenMapStack(groups);

    expect(entries.find((entry) => entry.id === 'data:unsupported-layer')?.badges)
      .toContainEqual({ label: 'Unsupported', tone: 'warning' });
    expect(entries.find((entry) => entry.id === 'relief:terrain')?.badges)
      .toContainEqual({ label: 'Missing source', tone: 'warning' });
  });

  it('distinguishes bounded, server-side, and fallback cluster rows', () => {
    const bounded = makeLayer({
      id: 'bounded-cluster',
      dataset_geometry_type: 'POINT',
      dataset_feature_count: 250,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    });
    const server = makeLayer({
      id: 'server-cluster',
      dataset_geometry_type: 'POINT',
      dataset_feature_count: 25_000,
      sort_order: 1,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    });
    const fallback = makeLayer({
      id: 'fallback-cluster',
      dataset_geometry_type: 'POINT',
      dataset_feature_count: null,
      sort_order: 2,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    });

    const entries = flattenMapStack(buildMapStack(makeMap({ layers: [bounded, server, fallback] })));

    expect(entries.find((entry) => entry.id === 'data:bounded-cluster')).toMatchObject({
      badges: expect.arrayContaining([{ label: 'Bounded cluster', tone: 'success' }]),
      metadata: { clusterSource: { kind: 'bounded-geojson', status: 'eligible' } },
    });
    expect(entries.find((entry) => entry.id === 'data:server-cluster')).toMatchObject({
      badges: expect.arrayContaining([{ label: 'Server cluster', tone: 'info' }]),
      metadata: { clusterSource: { kind: 'server-tile', status: 'too-many-features' } },
    });
    expect(entries.find((entry) => entry.id === 'data:fallback-cluster')).toMatchObject({
      badges: expect.arrayContaining([{ label: 'Point fallback', tone: 'warning' }]),
      metadata: { clusterSource: { kind: 'fallback', status: 'missing-count' } },
    });
  });

  it('sorts copied layer inputs without mutating the persisted layer array', () => {
    const first = makeLayer({ id: 'first', sort_order: 2 });
    const second = makeLayer({ id: 'second', sort_order: 1 });
    const layers = [first, second];

    const groups = buildMapStack(makeMap({ layers }));

    expect(layers.map((layer) => layer.id)).toEqual(['first', 'second']);
    expect(group(groups, 'data')?.entries.map((entry) => entry.id)).toEqual([
      'data:first',
      'data:second',
    ]);
    expect(flattenMapStack(groups).find((entry) => entry.id === 'data:second')?.orderLabel)
      .toBe('Data 1 of 2 (top)');
  });

  it('builds a complete stack from existing saved-map fields without new backend fields', () => {
    const groups = buildMapStack(makeMap({
      basemap_style: 'satellite',
      basemap_label: 'Satellite',
      show_basemap_labels: false,
      terrain_config: null,
      layers: [
        makeLayer({
          id: 'parcels',
          dataset_id: 'parcels',
          dataset_name: 'Parcels',
          dataset_geometry_type: 'POLYGON',
          sort_order: 0,
        }),
      ],
    }));

    expect(groups.map((item) => item.id)).toEqual(MAP_STACK_GROUP_ORDER);
    expect(group(groups, 'surface')?.entries.map((entry) => entry.id)).toEqual(['surface:background']);
    expect(group(groups, 'basemap')?.entries[0]).toMatchObject({
      id: 'basemap:preset:satellite',
      title: 'Satellite',
      metadata: {
        basemap: {
          style: 'satellite',
          sublayer: 'preset',
          futureControl: false,
        },
      },
    });
    expect(group(groups, 'data')?.entries.map((entry) => entry.id)).toEqual(['data:parcels']);
    expect(flattenMapStack(groups).find((entry) => entry.id === 'labels:basemap')).toMatchObject({
      visible: false,
      metadata: {
        basemap: {
          labelsVisible: false,
        },
      },
    });
  });

  it('keeps legacy terrain config useful when the saved DEM source is unavailable', () => {
    const groups = buildMapStack(makeMap({
      terrain_config: { enabled: true, source_dataset_id: 'missing-dem', exaggeration: 3 },
      layers: [],
    }));

    const terrain = flattenMapStack(groups).find((entry) => entry.id === 'relief:terrain');
    expect(terrain).toMatchObject({
      role: 'surface-terrain',
      title: 'Terrain source missing',
      visible: false,
      metadata: {
        terrain: {
          enabled: false,
          exaggeration: 3,
          sourceDatasetId: 'missing-dem',
          sourceLayerId: null,
          sourceStatus: 'missing',
          verticalUnits: null,
        },
      },
    });
    expect(terrain?.badges.map((badge) => badge.label)).toContain('Missing source');
  });

  it('defaults omitted basemap-label state to visible for older or shared payloads', () => {
    const groups = buildMapStack({
      basemap_style: 'positron',
      terrain_config: null,
      layers: [],
    });

    expect(flattenMapStack(groups).find((entry) => entry.id === 'labels:basemap')).toMatchObject({
      visible: true,
      metadata: {
        basemap: {
          labelsVisible: true,
        },
      },
    });
  });

  it('reflects basemap_config metadata in preset and label entries', () => {
    const groups = buildMapStack(makeMap({
      basemap_config: {
        label_mode: 'subtle',
        road_visibility: 'hidden',
        boundary_visibility: 'full',
        building_visibility: false,
        land_water_tone: 'muted',
        relief_contrast: 'soft',
      },
    }));

    expect(group(groups, 'basemap')?.entries[0]).toMatchObject({
      badges: expect.arrayContaining([
        expect.objectContaining({ label: 'muted' }),
      ]),
      metadata: {
        basemap: {
          config: expect.objectContaining({
            label_mode: 'subtle',
            road_visibility: 'hidden',
          }),
        },
      },
    });
    expect(flattenMapStack(groups).find((entry) => entry.id === 'labels:basemap')).toMatchObject({
      visible: true,
      subtitle: 'Subtle labels',
      metadata: {
        basemap: {
          labelsVisible: true,
          config: expect.objectContaining({ label_mode: 'subtle' }),
        },
      },
    });
  });
});

describe('computeDisambiguationLabels', () => {
  it('badges duplicates that share a display name', () => {
    const labels = computeDisambiguationLabels([
      makeLayer({ id: 'a', display_name: 'Counties' }),
      makeLayer({ id: 'b', display_name: 'Counties' }),
    ]);
    expect(labels.get('a')).toBe('Copy 1 of 2');
    expect(labels.get('b')).toBe('Copy 2 of 2');
  });

  it('does not badge differently-named layers off the same dataset (line + casing)', () => {
    const labels = computeDisambiguationLabels([
      makeLayer({ id: 'route', dataset_id: 'routes', display_name: 'Climbing routes' }),
      makeLayer({ id: 'casing', dataset_id: 'routes', display_name: 'Route casing' }),
    ]);
    expect(labels.get('route')).toBeNull();
    expect(labels.get('casing')).toBeNull();
  });
});

// fix(#430 V-17): audience-visibility mismatch detection.
describe('isLayerHiddenFromMapAudience', () => {
  it('never flags a private map — it has no audience beyond the owner/grantees', () => {
    expect(
      isLayerHiddenFromMapAudience({ dataset_visibility: 'private', dataset_status: 'draft' }, 'private'),
    ).toBe(false);
  });

  it('flags a private dataset layer on a public map', () => {
    expect(
      isLayerHiddenFromMapAudience({ dataset_visibility: 'private', dataset_status: 'published' }, 'public'),
    ).toBe(true);
  });

  it('flags an unpublished dataset layer on a shared (internal) map', () => {
    expect(
      isLayerHiddenFromMapAudience({ dataset_visibility: 'public', dataset_status: 'draft' }, 'internal'),
    ).toBe(true);
  });

  it('does not flag a public+published dataset layer on a public map', () => {
    expect(
      isLayerHiddenFromMapAudience({ dataset_visibility: 'public', dataset_status: 'published' }, 'public'),
    ).toBe(false);
  });

  it('is conservative when both signal fields are absent — no false positive', () => {
    expect(
      isLayerHiddenFromMapAudience({ dataset_visibility: undefined, dataset_status: undefined }, 'public'),
    ).toBe(false);
  });
});

describe('resolveTerrainSourceLayer', () => {
  const dem = (overrides = {}) =>
    makeLayer({ id: 'dem', dataset_id: 'dem-1', is_dem: true, dataset_record_type: 'raster_dataset', ...overrides });

  it('resolves a hillshade-mode DEM as the terrain source (render_mode-agnostic)', () => {
    const layer = dem({ style_config: { render_mode: 'hillshade' } as unknown as StyleConfig });
    expect(resolveTerrainSourceLayer([layer], { source_dataset_id: 'dem-1' })?.id).toBe('dem');
  });

  it('resolves a terrain-mode DEM source too', () => {
    const layer = dem({ style_config: { render_mode: 'terrain' } as unknown as StyleConfig });
    expect(resolveTerrainSourceLayer([layer], { source_dataset_id: 'dem-1' })?.id).toBe('dem');
  });

  it('returns undefined when no terrain-capable DEM matches the source dataset', () => {
    const vector = makeLayer({ id: 'roads', dataset_id: 'dem-1', is_dem: false });
    expect(resolveTerrainSourceLayer([vector], { source_dataset_id: 'dem-1' })).toBeUndefined();
    expect(resolveTerrainSourceLayer([dem()], { source_dataset_id: 'other' })).toBeUndefined();
    expect(resolveTerrainSourceLayer([dem()], null)).toBeUndefined();
  });
});
