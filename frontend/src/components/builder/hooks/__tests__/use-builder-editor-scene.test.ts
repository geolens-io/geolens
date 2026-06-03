import { renderHook } from '@/test/test-utils';
import type { MapLayerResponse } from '@/types/api';
import {
  createSyntheticEditorLayer,
  deriveBuilderEditorScene,
  useBuilderEditorScene,
} from '../use-builder-editor-scene';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Layer 1',
    dataset_geometry_type: 'LINESTRING',
    dataset_table_name: 'layer_1',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Layer 1',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
  };
}

const BASEMAP_GROUP = {
  id: 'basemap-group',
  presetName: 'Positron',
  sublayers: [
    { id: 'basemap:road', name: 'Roads' },
    { id: 'basemap:label', name: 'Labels' },
  ],
};

describe('builder editor scene controller', () => {
  it('derives scene variants from expanded id and selected layer metadata', () => {
    expect(deriveBuilderEditorScene(null, null)).toBe('default');
    expect(deriveBuilderEditorScene('settings', null)).toBe('settings');
    expect(deriveBuilderEditorScene('basemap-group', null)).toBe('basemap-group');
    expect(deriveBuilderEditorScene('basemap:road', null)).toBe('basemap-sublayer');
    expect(deriveBuilderEditorScene('dem-layer', makeLayer({ is_dem: true }))).toBe('dem');
    expect(deriveBuilderEditorScene('layer-1', makeLayer())).toBe('default');
  });

  it('creates synthetic editor layers for basemap and settings scenes', () => {
    expect(createSyntheticEditorLayer({
      editorScene: 'settings',
      expandedLayerId: 'settings',
      basemapGroup: BASEMAP_GROUP,
    })).toMatchObject({
      id: 'settings',
      dataset_name: 'Settings',
      dataset_table_name: 'settings',
      sort_order: -1,
      show_in_legend: false,
    });

    expect(createSyntheticEditorLayer({
      editorScene: 'basemap-sublayer',
      expandedLayerId: 'basemap:road',
      basemapGroup: BASEMAP_GROUP,
    })).toMatchObject({
      id: 'basemap:road',
      dataset_name: 'Roads',
      dataset_table_name: 'basemap',
    });

    expect(createSyntheticEditorLayer({
      editorScene: 'basemap-group',
      expandedLayerId: 'basemap-group',
      basemapGroup: BASEMAP_GROUP,
    })).toMatchObject({
      id: 'basemap-group',
      dataset_name: 'Basemap · Positron',
      display_name: 'Basemap · Positron',
    });
  });

  it('returns real editor layer and saved baseline for normal layer editing', () => {
    const draft = makeLayer({ id: 'trail-layer', paint: { 'line-color': '#f97316' } });
    const saved = makeLayer({ id: 'trail-layer', paint: { 'line-color': '#0f766e' } });

    const { result } = renderHook(() => useBuilderEditorScene({
      expandedLayerId: 'trail-layer',
      localLayers: [draft],
      savedLayerBaseline: [saved],
      basemapGroup: BASEMAP_GROUP,
    }));

    expect(result.current.editorScene).toBe('default');
    expect(result.current.editingLayer).toBe(draft);
    expect(result.current.editorLayer).toBe(draft);
    expect(result.current.editingSavedLayer).toBe(saved);
    expect(result.current.isEditorOpen).toBe(true);
  });

  it('returns synthetic editor layer and no saved baseline for basemap/settings scenes', () => {
    const { result } = renderHook(() => useBuilderEditorScene({
      expandedLayerId: 'basemap:label',
      localLayers: [makeLayer()],
      savedLayerBaseline: [makeLayer()],
      basemapGroup: BASEMAP_GROUP,
    }));

    expect(result.current.editorScene).toBe('basemap-sublayer');
    expect(result.current.editingLayer).toBeNull();
    expect(result.current.editingSavedLayer).toBeUndefined();
    expect(result.current.editorLayer).toMatchObject({
      id: 'basemap:label',
      dataset_name: 'Labels',
    });
    expect(result.current.isEditorOpen).toBe(true);
  });
});
