import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/hooks/use-builder-layers';
import type { MapLayerResponse, MapResponse } from '@/types/api';

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    sort_order: 0,
    filter: null,
    display_name: null,
    layer_type: 'vector_geolens',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    dataset_record_type: undefined,
    label_config: null,
    style_config: null,
    ...overrides,
  };
}

function makeMapData(layers: MapLayerResponse[] = []): MapResponse {
  return {
    id: 'map-1',
    name: 'Test Map',
    description: null,
    center_lng: 0,
    center_lat: 0,
    zoom: 2,
    bearing: 0,
    pitch: 0,
    basemap_style: 'positron',
    visibility: 'private',
    thumbnail: null,
    created_by: null,
    created_by_username: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    layers,
    layer_count: layers.length,
    forked_from_id: null,
    forked_from_name: null,
  };
}

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: React.RefObject<MaplibreMap | null> = { current: null } as React.RefObject<MaplibreMap | null>,
) {
  const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
  const searchParams = new URLSearchParams();
  const setSearchParams = vi.fn() as unknown as Parameters<typeof useBuilderLayers>[6];

  return renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      addLayerMutation,
      removeLayerMutation,
      searchParams,
      setSearchParams,
    ),
  );
}

type MaplibreMap = import('maplibre-gl').Map;

describe('useBuilderLayers', () => {
  it('initializes localLayers from mapData on first render', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);
    expect(result.current.localLayers).toHaveLength(1);
    expect(result.current.localLayers[0].id).toBe('layer-1');
  });

  it('handleToggleVisibility flips visible and marks dirty', () => {
    const layer = makeMockLayer({ visible: true });
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleToggleVisibility('layer-1');
    });

    expect(result.current.localLayers[0].visible).toBe(false);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('handleToggleVisibility with explicit value', () => {
    const layer = makeMockLayer({ visible: true });
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleToggleVisibility('layer-1', false);
    });

    expect(result.current.localLayers[0].visible).toBe(false);
  });

  it('handleMoveUp swaps layers and updates sort_order', () => {
    const layer1 = makeMockLayer({ id: 'layer-1', sort_order: 0 });
    const layer2 = makeMockLayer({ id: 'layer-2', sort_order: 1 });
    const mapData = makeMapData([layer1, layer2]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleMoveUp('layer-2');
    });

    expect(result.current.localLayers[0].id).toBe('layer-2');
    expect(result.current.localLayers[1].id).toBe('layer-1');
    expect(result.current.localLayers[0].sort_order).toBe(0);
    expect(result.current.localLayers[1].sort_order).toBe(1);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('handleMoveDown swaps layers and updates sort_order', () => {
    const layer1 = makeMockLayer({ id: 'layer-1', sort_order: 0 });
    const layer2 = makeMockLayer({ id: 'layer-2', sort_order: 1 });
    const mapData = makeMapData([layer1, layer2]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleMoveDown('layer-1');
    });

    expect(result.current.localLayers[0].id).toBe('layer-2');
    expect(result.current.localLayers[1].id).toBe('layer-1');
    expect(result.current.localLayers[0].sort_order).toBe(0);
    expect(result.current.localLayers[1].sort_order).toBe(1);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('handleFilterChange updates filter in local state and marks dirty', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleFilterChange('layer-1', ['==', 'type', 'park']);
    });

    expect(result.current.localLayers[0].filter).toEqual(['==', 'type', 'park']);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('handleOpacityChange updates opacity and marks dirty', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleOpacityChange('layer-1', 0.5);
    });

    expect(result.current.localLayers[0].opacity).toBe(0.5);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('handlePaintChange updates paint and marks dirty', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handlePaintChange('layer-1', { 'fill-color': '#ff0000' });
    });

    expect(result.current.localLayers[0].paint).toEqual({ 'fill-color': '#ff0000' });
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('handleToggleExpand sets expandedLayerId and defaults to style tab', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleToggleExpand('layer-1');
    });

    expect(result.current.expandedLayerId).toBe('layer-1');
    expect(result.current.activeEditorTab).toBe('style');
  });

  it('handleToggleExpand on same layer collapses', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleToggleExpand('layer-1');
    });
    act(() => {
      result.current.handleToggleExpand('layer-1');
    });

    expect(result.current.expandedLayerId).toBeNull();
  });

  it('handleDisplayNameChange updates display_name', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleDisplayNameChange('layer-1', 'Custom Name');
    });

    expect(result.current.localLayers[0].display_name).toBe('Custom Name');
    expect(result.current.hasUnsavedChanges).toBe(true);
  });
});
