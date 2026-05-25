import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import {
  buildDuplicateRenderingInput,
  useBuilderLayers,
} from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
  makeMapLibreMock,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse } from '@/types/api';

const makeMockLayer = makeBuilderLayer;
const makeMapData = makeBuilderMap;

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: React.RefObject<MaplibreMap | null> = { current: null } as React.RefObject<MaplibreMap | null>,
) {
  const addLayerMutate = vi.fn();
  const removeLayerMutate = vi.fn();
  const addLayerMutation = { mutate: addLayerMutate } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: removeLayerMutate } as unknown as Parameters<typeof useBuilderLayers>[4];

  const hook = renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      addLayerMutation,
      removeLayerMutation,
    ),
  );

  return { ...hook, addLayerMutate, removeLayerMutate };
}

type MaplibreMap = import('maplibre-gl').Map;

describe('useBuilderLayers', () => {
  it('initializes localLayers from mapData on first render', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);
    expect(result.current.localLayers).toHaveLength(1);
    expect(result.current.localLayers[0].id).toBe('layer-1');
    expect(result.current.savedLayerBaseline).toEqual([layer]);
  });

  it('initializes localTerrainConfig from mapData', () => {
    const mapData = {
      ...makeMapData(),
      terrain_config: {
        enabled: true,
        source_dataset_id: 'dem-1',
        exaggeration: 1.5,
      },
    };

    const { result } = renderBuilderLayers(mapData);

    expect(result.current.localTerrainConfig).toEqual({
      enabled: true,
      source_dataset_id: 'dem-1',
      exaggeration: 1.5,
    });
  });

  it('refreshes savedLayerBaseline from API layer refetches when clean', () => {
    let mapData = makeMapData([makeMockLayer({ id: 'layer-1' })]);
    const mapRef = { current: null } as React.RefObject<MaplibreMap | null>;
    const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
    const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];
    const { result, rerender } = renderHook(() =>
      useBuilderLayers(mapData, mapRef, 'map-1', addLayerMutation, removeLayerMutation),
    );

    mapData = makeMapData([makeMockLayer({ id: 'layer-2', dataset_id: 'ds-2' })]);
    rerender();

    expect(result.current.localLayers[0].id).toBe('layer-2');
    expect(result.current.savedLayerBaseline[0].id).toBe('layer-2');
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

  it('handleOpacityChange does NOT mark dirty for nonexistent layer id', () => {
    const layer = makeMockLayer();
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleOpacityChange('nonexistent-id', 0.5);
    });

    expect(result.current.hasUnsavedChanges).toBe(false);
    expect(result.current.localLayers[0].opacity).toBe(1);
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

  it('handleRenderAsChange applies existing-field patches without writing is_3d', () => {
    const layer = makeMockLayer({
      dataset_geometry_type: 'POLYGON',
      dataset_column_info: [{ name: 'height_m', type: 'double' }],
      paint: { 'fill-color': '#2255aa' },
    });
    const mapData = makeMapData([layer]);
    const { result } = renderBuilderLayers(mapData);

    act(() => {
      result.current.handleRenderAsChange('layer-1', 'extrusion-3d');
    });

    const updated = result.current.localLayers[0];
    expect(updated.layer_type).toBe('vector_geolens');
    expect(updated.style_config?.builder).toEqual(expect.objectContaining({
      heightColumn: 'height_m',
      heightScale: 1,
      extrusionMinZoom: 14,
      extrusionOpacity: 0.85,
    }));
    expect(JSON.stringify(updated)).not.toContain('is_3d');
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('buildDuplicateRenderingInput creates a sibling layer with copied style fields and next sort order', () => {
    const layer = makeMockLayer({
      id: 'layer-1',
      dataset_id: 'ds-1',
      display_name: 'Population fill',
      sort_order: 1,
      opacity: 0.7,
      paint: { 'fill-color': '#2255aa' },
      layout: { _minzoom: 4 },
      style_config: { builder: { strokeDisabled: true } } as MapLayerResponse['style_config'],
      show_in_legend: false,
    });

    expect(buildDuplicateRenderingInput(layer, [makeMockLayer({ id: 'lower', sort_order: 0 }), layer]))
      .toEqual(expect.objectContaining({
        dataset_id: 'ds-1',
        sort_order: 2,
        display_name: 'Population fill rendering',
        opacity: 0.7,
        paint: { 'fill-color': '#2255aa' },
        layout: { _minzoom: 4 },
        style_config: { builder: { strokeDisabled: true } },
        layer_type: 'vector_geolens',
        show_in_legend: false,
      }));
  });

  it('handleDuplicateRendering selects and briefly highlights the new rendering', () => {
    vi.useFakeTimers();
    try {
      const layer = makeMockLayer({
        id: 'layer-1',
        dataset_id: 'ds-1',
        display_name: 'Population fill',
        sort_order: 0,
      });
      const duplicate = makeMockLayer({
        id: 'layer-duplicate',
        dataset_id: 'ds-1',
        display_name: 'Population fill rendering',
        sort_order: 1,
      });
      const { result, addLayerMutate } = renderBuilderLayers(makeMapData([layer]));

      act(() => {
        result.current.handleDuplicateRendering('layer-1');
      });

      expect(addLayerMutate).toHaveBeenCalledOnce();
      const [, { onSuccess }] = addLayerMutate.mock.calls[0];

      act(() => {
        onSuccess(duplicate);
      });

      expect(result.current.localLayers.map((candidate) => candidate.id)).toContain('layer-duplicate');
      expect(result.current.expandedLayerId).toBe('layer-duplicate');
      expect(result.current.activeEditorTab).toBe('style');
      expect(result.current.freshLayerId).toBe('layer-duplicate');

      act(() => {
        vi.advanceTimersByTime(201);
      });

      expect(result.current.freshLayerId).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('dispatchLayerAction routes persisted remove through the server mutation', () => {
    const layer = makeMockLayer({ id: 'layer-1' });
    const { result, removeLayerMutate } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.dispatchLayerAction({
        type: 'remove_layer',
        source: 'manual',
        layerId: 'layer-1',
        persistence: 'server',
      });
    });

    expect(result.current.localLayers).toHaveLength(0);
    expect(removeLayerMutate).toHaveBeenCalledWith(
      { mapId: 'map-1', layerId: 'layer-1' },
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
  });

  it('chatLayerActions remove uses the draft-only local remove path', () => {
    const layer = makeMockLayer({ id: 'layer-1' });
    const { result, removeLayerMutate } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.chatLayerActions.onRemove('layer-1');
    });

    expect(result.current.localLayers).toHaveLength(0);
    expect(result.current.hasUnsavedChanges).toBe(true);
    expect(removeLayerMutate).not.toHaveBeenCalled();
  });

  it('chatLayerActions style updates dispatch through the layer action boundary', () => {
    const layer = makeMockLayer({ id: 'layer-1', paint: { 'line-color': '#111111' } });
    const { result } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.chatLayerActions.onPaintChange('layer-1', { 'line-color': '#14532d' });
    });

    expect(result.current.localLayers[0].paint).toEqual({ 'line-color': '#14532d' });
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

  describe('handleZoomToLayer', () => {
    function createMockMap() {
      return makeMapLibreMock();
    }

    function setupZoom(bbox: number[] | null, layerId = 'layer-1') {
      const mockMap = createMockMap();
      const mapRef = { current: mockMap } as React.RefObject<MaplibreMap | null>;
      const layer = makeMockLayer({ dataset_extent_bbox: bbox });
      const { result } = renderBuilderLayers(makeMapData([layer]), mapRef);
      return { mockMap, result, layerId };
    }

    it('calls fitBounds with valid bbox', () => {
      const { mockMap, result } = setupZoom([-75.15, 40.63, -74.14, 41.14]);
      act(() => { result.current.handleZoomToLayer('layer-1'); });
      expect(mockMap.fitBounds).toHaveBeenCalledWith(
        [[-75.15, 40.63], [-74.14, 41.14]],
        { padding: 40, maxZoom: 18 },
      );
    });

    it('handles zero-extent bbox for point geometries', () => {
      const { mockMap, result } = setupZoom([10, 20, 10, 20]);
      act(() => { result.current.handleZoomToLayer('layer-1'); });
      expect(mockMap.fitBounds).toHaveBeenCalledWith(
        [[10, 20], [10, 20]],
        { padding: 40, maxZoom: 18 },
      );
    });

    it.each([
      ['null bbox', null],
      ['NaN values', [NaN, 40, -74, 41]],
      ['inverted ranges', [-74, 41, -75, 40]],
    ])('skips when bbox has %s', (_label, bbox) => {
      const { mockMap, result } = setupZoom(bbox as number[] | null);
      act(() => { result.current.handleZoomToLayer('layer-1'); });
      expect(mockMap.fitBounds).not.toHaveBeenCalled();
    });

    it('skips for unknown layer id', () => {
      const { mockMap, result } = setupZoom([-75, 40, -74, 41]);
      act(() => { result.current.handleZoomToLayer('nonexistent'); });
      expect(mockMap.fitBounds).not.toHaveBeenCalled();
    });

    it('skips when map instance is null', () => {
      const mapRef = { current: null } as React.RefObject<MaplibreMap | null>;
      const layer = makeMockLayer({ dataset_extent_bbox: [-75, 40, -74, 41] });
      const { result } = renderBuilderLayers(makeMapData([layer]), mapRef);
      act(() => { result.current.handleZoomToLayer('layer-1'); });
    });
  });

  // Regression: KISS-2 / PERF-N2 — handlers must keep a stable identity across
  // unrelated state mutations so React.memo() on LayerItem actually skips
  // re-renders. A regression here (reverting useCallback) would silently tank
  // perf on maps with many layers.
  describe('handler identity stability (KISS-2 / PERF-N2)', () => {
    it('keeps layer handlers stable across layer mutations', () => {
      const layer = makeMockLayer({ id: 'layer-1' });
      const { result } = renderBuilderLayers(makeMapData([layer]));

      const initial = {
        handleToggleVisibility: result.current.handleToggleVisibility,
        handlePaintChange: result.current.handlePaintChange,
        handleOpacityChange: result.current.handleOpacityChange,
        handleLayoutChange: result.current.handleLayoutChange,
        handleStyleConfigChange: result.current.handleStyleConfigChange,
        handleFilterChange: result.current.handleFilterChange,
        handleLabelChange: result.current.handleLabelChange,
        handleMoveUp: result.current.handleMoveUp,
        handleMoveDown: result.current.handleMoveDown,
        handleReorder: result.current.handleReorder,
        handleDisplayNameChange: result.current.handleDisplayNameChange,
        handleToggleExpand: result.current.handleToggleExpand,
        handleTabChange: result.current.handleTabChange,
        handleZoomToLayer: result.current.handleZoomToLayer,
        handleRemove: result.current.handleRemove,
        handleAddDataset: result.current.handleAddDataset,
        handleAiRemoveLayer: result.current.handleAiRemoveLayer,
        handleToggleLegend: result.current.handleToggleLegend,
        handleRenderModeChange: result.current.handleRenderModeChange,
        handleRenderAsChange: result.current.handleRenderAsChange,
        handleDuplicateRendering: result.current.handleDuplicateRendering,
        dispatchLayerAction: result.current.dispatchLayerAction,
      };

      // Trigger a state mutation that would invalidate non-memoized closures.
      act(() => {
        result.current.handleDisplayNameChange('layer-1', 'Renamed');
      });

      // After the state update, every handler should still have the same
      // reference (useCallback returning a stable identity). If this fails,
      // someone has likely dropped useCallback or added unstable deps.
      for (const [name, initialFn] of Object.entries(initial)) {
        expect(
          result.current[name as keyof typeof initial],
          `${name} identity changed after state update`,
        ).toBe(initialFn);
      }
    });
  });
});

// BSR-18 handleAddDataset tests live in the dedicated file:
// use-builder-layers.add-dataset.test.ts
// (isolated to avoid OOM when running alongside the heavy hook render)
