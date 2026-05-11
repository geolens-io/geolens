import { describe, expect, it } from 'vitest';
import {
  MAP_STACK_GROUP_ORDER,
  buildMapStack,
  flattenMapStack,
  type MapStackGroup,
  type MapStackMapInput,
} from '../map-stack';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Dataset',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POLYGON',
    dataset_table_name: overrides.dataset_table_name ?? 'dataset',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_3d: overrides.is_3d ?? false,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

function makeMap(overrides: Partial<MapStackMapInput> = {}): MapStackMapInput {
  return {
    basemap_style: overrides.basemap_style ?? 'positron',
    show_basemap_labels: overrides.show_basemap_labels ?? true,
    terrain_config: overrides.terrain_config ?? null,
    layers: overrides.layers ?? [],
    widgets: overrides.widgets ?? null,
  };
}

function group(groups: MapStackGroup[], id: MapStackGroup['id']) {
  return groups.find((item) => item.id === id);
}

describe('buildMapStack', () => {
  it('returns all stack groups and separates DEM terrain from visual relief', () => {
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
      sort_order: 0,
      style_config: { render_mode: 'hillshade' } as StyleConfig,
    });
    const dataLayer = makeLayer({
      id: 'trails',
      dataset_id: 'trails-1',
      dataset_name: 'Trails',
      dataset_geometry_type: 'LINESTRING',
      dataset_table_name: 'trails',
      sort_order: 1,
    });

    const groups = buildMapStack(makeMap({
      terrain_config: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2.5 },
      layers: [demLayer, dataLayer],
    }));
    const entries = flattenMapStack(groups);

    expect(groups.map((item) => item.id)).toEqual(MAP_STACK_GROUP_ORDER);

    const terrain = entries.find((entry) => entry.id === 'surface:terrain');
    expect(terrain).toMatchObject({
      groupId: 'surface',
      role: 'surface-terrain',
      title: 'Canyon DEM',
      visible: true,
    });
    expect(terrain?.metadata.terrain).toEqual({
      enabled: true,
      exaggeration: 2.5,
      sourceDatasetId: 'dem-1',
      sourceLayerId: 'dem-hillshade',
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
    expect(terrain!.order).toBeLessThan(relief!.order);
    expect(relief!.order).toBeLessThan(entries.find((entry) => entry.id === 'basemap:preset:positron')!.order);
    expect(entries.find((entry) => entry.id === 'data:trails')!.order).toBeGreaterThan(relief!.order);
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
      metadata: {
        basemap: {
          style: 'satellite',
          sublayer: 'preset',
          futureControl: true,
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

    const terrain = flattenMapStack(groups).find((entry) => entry.id === 'surface:terrain');
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
});
