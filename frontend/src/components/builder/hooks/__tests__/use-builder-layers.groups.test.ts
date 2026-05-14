/**
 * use-builder-layers.groups.test.ts
 *
 * Phase 1035 — Tests for groupMeta state, handleToggleGroupExpand,
 * handleDEMTerrainBind, and folder-group handler mutations in useBuilderLayers.
 */
import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import {
  useBuilderLayers,
} from '@/components/builder/hooks/use-builder-layers';
import type { MapLayerResponse, MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

function makeMockLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'ds-1',
    dataset_name: overrides.dataset_name ?? 'Test',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'Polygon',
    dataset_table_name: overrides.dataset_table_name ?? 'test_table',
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    sort_order: overrides.sort_order ?? 0,
    filter: overrides.filter ?? null,
    display_name: overrides.display_name ?? null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_extent_bbox: overrides.dataset_extent_bbox ?? null,
    dataset_column_info: overrides.dataset_column_info ?? null,
    dataset_feature_count: overrides.dataset_feature_count ?? null,
    dataset_sample_values: overrides.dataset_sample_values ?? null,
    dataset_record_type: overrides.dataset_record_type ?? undefined,
    label_config: overrides.label_config ?? null,
    style_config: overrides.style_config ?? null,
    popup_config: overrides.popup_config ?? null,
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    is_3d: overrides.is_3d ?? false,
    ...overrides,
  };
}

function makeMapData(
  layers: MapLayerResponse[] = [],
  extras: Record<string, unknown> = {},
): MapResponse {
  return {
    id: 'map-1',
    name: 'Test Map',
    description: null,
    notes: null,
    center_lng: 0,
    center_lat: 0,
    zoom: 2,
    bearing: 0,
    pitch: 0,
    basemap_style: 'positron',
    show_basemap_labels: true,
    basemap_config: null,
    terrain_config: null,
    visibility: 'private',
    thumbnail_url: null,
    created_by: null,
    created_by_username: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    layers,
    layer_count: layers.length,
    forked_from_id: null,
    forked_from_name: null,
    ...extras,
  } as MapResponse;
}

function renderBuilderLayers(
  mapData: MapResponse | undefined,
  mapRef: React.RefObject<MaplibreMap | null> = { current: null } as React.RefObject<MaplibreMap | null>,
) {
  const addLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3];
  const removeLayerMutation = { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4];

  return renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      addLayerMutation,
      removeLayerMutation,
    ),
  );
}

describe('useBuilderLayers — group_meta / groupMeta', () => {

  // Test 1: toggle expands
  // Per CR-02 (commit 116fe289), toggle-expand is treated as a UI-only
  // affordance and does NOT mark the map as dirty — `group_meta` is not
  // persisted to the backend schema yet, so a false "unsaved" badge on
  // expand/collapse was misleading and was removed. Once `group_meta`
  // joins the API payload, restore the hasUnsavedChanges assertion below.
  it('handleToggleGroupExpand toggles groupMeta.basemap.expanded between true/false (UI-only; does NOT mark unsaved)', () => {
    const { result } = renderBuilderLayers(makeMapData());
    expect(result.current.groupMeta['basemap']).toBeUndefined();

    act(() => {
      result.current.handleToggleGroupExpand('basemap');
    });
    expect(result.current.groupMeta['basemap']?.expanded).toBe(true);
    // UI-only toggle — must NOT dirty the map
    expect(result.current.hasUnsavedChanges).toBe(false);

    act(() => {
      result.current.handleToggleGroupExpand('basemap');
    });
    expect(result.current.groupMeta['basemap']?.expanded).toBe(false);
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  // Test 2: toggle creates new entry when key not present
  it('handleToggleGroupExpand creates entry { expanded: true } when groupMeta has no key', () => {
    const { result } = renderBuilderLayers(makeMapData());

    act(() => {
      result.current.handleToggleGroupExpand('g1');
    });
    expect(result.current.groupMeta['g1']).toEqual({ expanded: true });
  });

  // Test 3: DEM terrain bind sets localTerrainConfig and marks unsaved
  it('handleDEMTerrainBind sets localTerrainConfig with enabled=true, source_dataset_id, and previous exaggeration', () => {
    const layer = makeMockLayer({ id: 'dem-layer-1', dataset_id: 'dem-ds-1', is_dem: true });
    const { result } = renderBuilderLayers(makeMapData([layer], {
      terrain_config: { enabled: false, source_dataset_id: null, exaggeration: 2.5 },
    }));

    act(() => {
      result.current.handleDEMTerrainBind('dem-layer-1');
    });

    expect(result.current.localTerrainConfig).toEqual({
      enabled: true,
      source_dataset_id: 'dem-ds-1',
      exaggeration: 2.5,
    });
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  // Test 4: DEM terrain bind no-op for nonexistent layer
  it('handleDEMTerrainBind is a no-op when layerId does not match any layer', () => {
    const { result } = renderBuilderLayers(makeMapData([]));
    const initialTerrainConfig = result.current.localTerrainConfig;

    act(() => {
      result.current.handleDEMTerrainBind('nonexistent-id');
    });

    expect(result.current.localTerrainConfig).toBe(initialTerrainConfig);
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  // Test 5: groupMeta initializes from mapData.group_meta
  it('hook initializes groupMeta from mapData.group_meta when present', () => {
    const mapData = makeMapData([], {
      group_meta: { 'basemap': { expanded: true }, 'folder1': { expanded: false } },
    });

    const { result } = renderBuilderLayers(mapData);

    expect(result.current.groupMeta).toEqual({
      'basemap': { expanded: true },
      'folder1': { expanded: false },
    });
  });

  // Test 5b: groupMeta defaults to empty when mapData has no group_meta
  it('hook initializes groupMeta to empty record when mapData has no group_meta', () => {
    const { result } = renderBuilderLayers(makeMapData([]));
    expect(result.current.groupMeta).toEqual({});
  });
});

describe('useBuilderLayers — folder group handlers', () => {

  // Test 6: handleCreateGroupWithLayer creates a group row and moves the target layer
  it('handleCreateGroupWithLayer creates a new folder group and nests the target layer', () => {
    const layer = makeMockLayer({ id: 'layer-1', sort_order: 0 });
    const { result } = renderBuilderLayers(makeMapData([layer]));

    act(() => {
      result.current.handleCreateGroupWithLayer('layer-1');
    });

    // A new group row should appear in localLayers
    const layers = result.current.localLayers;
    const groupRows = layers.filter((l) =>
      (l as { layer_type?: string }).layer_type === 'group:folder'
    );
    expect(groupRows.length).toBeGreaterThanOrEqual(1);
    expect(result.current.hasUnsavedChanges).toBe(true);

    // The target layer should still be present
    const targetLayer = layers.find((l) => l.id === 'layer-1');
    expect(targetLayer).toBeDefined();
  });

  // Test 7: handleRenameGroup updates display_name and marks unsaved
  it('handleRenameGroup updates the group display_name and marks dirty', () => {
    // Cast to MapLayerResponse since layer_type 'group:folder' is frontend-only (GroupedLayer)
    const groupLayer = { ...makeMockLayer({ id: 'group-1', display_name: 'Old Name' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupLayer]));

    act(() => {
      result.current.handleRenameGroup('group-1', 'New Name');
    });

    const updated = result.current.localLayers.find((l) => l.id === 'group-1');
    expect(updated?.display_name).toBe('New Name');
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  // Test 7b: handleRenameGroup with empty string is a no-op (silent revert)
  it('handleRenameGroup with empty string is a no-op (silent revert)', () => {
    const groupLayer = { ...makeMockLayer({ id: 'group-1', display_name: 'Keep This' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupLayer]));
    const changedBefore = result.current.hasUnsavedChanges;

    act(() => {
      result.current.handleRenameGroup('group-1', '   ');
    });

    const updated = result.current.localLayers.find((l) => l.id === 'group-1');
    expect(updated?.display_name).toBe('Keep This');
    expect(result.current.hasUnsavedChanges).toBe(changedBefore);
  });

  // Test 8: handleUngroup removes the group container but keeps its children
  it('handleUngroup removes the group container and promotes children in place', () => {
    const groupLayer = { ...makeMockLayer({ id: 'group-1' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const childLayer = makeMockLayer({
      id: 'child-1',
      sort_order: 1,
    });
    // Attach parent_group_id to child via cast
    const childWithGroup = { ...childLayer, parent_group_id: 'group-1' } as unknown as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupLayer, childWithGroup]));

    act(() => {
      result.current.handleUngroup('group-1');
    });

    // Group container removed
    const groupRow = result.current.localLayers.find((l) => l.id === 'group-1');
    expect(groupRow).toBeUndefined();
    // Child still present
    const child = result.current.localLayers.find((l) => l.id === 'child-1');
    expect(child).toBeDefined();
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  // Test 9: handleDeleteGroup removes the group and all children
  it('handleDeleteGroup removes group container and all children with matching parent_group_id', () => {
    const groupLayer = { ...makeMockLayer({ id: 'group-1' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const childLayer = { ...makeMockLayer({ id: 'child-1' }), parent_group_id: 'group-1' } as unknown as MapLayerResponse;
    const otherLayer = makeMockLayer({ id: 'other-layer' });
    const { result } = renderBuilderLayers(makeMapData([groupLayer, childLayer, otherLayer]));

    act(() => {
      result.current.handleDeleteGroup('group-1');
    });

    const remaining = result.current.localLayers;
    expect(remaining.find((l) => l.id === 'group-1')).toBeUndefined();
    expect(remaining.find((l) => l.id === 'child-1')).toBeUndefined();
    expect(remaining.find((l) => l.id === 'other-layer')).toBeDefined();
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  // Test 10: handleMoveLayerOutOfGroup clears parent_group_id and marks dirty
  it('handleMoveLayerOutOfGroup clears parent_group_id from the target layer', () => {
    const groupLayer = { ...makeMockLayer({ id: 'group-1' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const childLayer = { ...makeMockLayer({ id: 'child-1' }), parent_group_id: 'group-1' } as unknown as MapLayerResponse;
    const { result } = renderBuilderLayers(makeMapData([groupLayer, childLayer]));

    act(() => {
      result.current.handleMoveLayerOutOfGroup('child-1');
    });

    const moved = result.current.localLayers.find((l) => l.id === 'child-1') as MapLayerResponse & { parent_group_id?: string | null };
    expect(moved).toBeDefined();
    expect(moved?.parent_group_id == null).toBe(true);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });
});
