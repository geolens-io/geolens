import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { act } from '@testing-library/react';
import { renderHook as baseRenderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import { renderHook } from '@/test/test-utils';
import { buildLayerDiff, useBuilderSave, __resetThumbnailDebounceForTests } from '@/components/builder/hooks/use-builder-save';
import { useWidgetStore } from '@/stores/map-widget-store';
import type { MapLayerResponse } from '@/types/api';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';

/* ── Mocks ─────────────────────────────────────────── */

const mockMutate = vi.fn();
const mockUpdateMapMutateAsync = vi.fn();
const mockPatchMapLayersMutateAsync = vi.fn();
const mockDuplicateMapMutateAsync = vi.fn();
const mockEnabledWidgets = vi.hoisted(() => ({
  value: null as string[] | null | undefined,
}));

vi.mock('@/hooks/use-maps', () => ({
  useUpdateMap: () => ({
    mutate: mockMutate,
    mutateAsync: mockUpdateMapMutateAsync,
    isPending: false,
  }),
  usePatchMapLayers: () => ({
    mutateAsync: mockPatchMapLayersMutateAsync,
    isPending: false,
  }),
  useDuplicateMap: () => ({
    mutateAsync: mockDuplicateMapMutateAsync,
    isPending: false,
  }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledWidgets: () => ({ data: mockEnabledWidgets.value }),
}));

const mockUploadThumbnail = vi.fn((..._args: unknown[]) => Promise.resolve());
vi.mock('@/api/maps', () => ({
  uploadThumbnail: (...args: unknown[]) => mockUploadThumbnail(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useBlocker: () => mockBlocker,
  };
});

/* ── Helpers ───────────────────────────────────────── */

function createMockCanvas() {
  return {
    width: 800,
    height: 600,
    toBlob: vi.fn((cb: (b: Blob | null) => void) => cb(new Blob(['png'], { type: 'image/png' }))),
    toDataURL: vi.fn(() => 'data:image/jpeg;base64,abc'),
    getContext: vi.fn(() => ({ drawImage: vi.fn() })),
  };
}

function createMockMap(overrides: { loaded?: boolean } = {}) {
  return {
    getCenter: vi.fn(() => ({ lng: -73.9, lat: 40.7 })),
    getZoom: vi.fn(() => 10),
    getBearing: vi.fn(() => 0),
    getPitch: vi.fn(() => 0),
    getSource: vi.fn<(sourceId: string) => unknown>(() => undefined),
    triggerRepaint: vi.fn(),
    once: vi.fn(),
    off: vi.fn(),
    loaded: vi.fn(() => overrides.loaded ?? true),
    getCanvas: vi.fn(() => createMockCanvas()),
  };
}

/** PERF-08 (Phase 274): doCapture and handleExportPNG now register
 *  `map.once('render', ...)` and call `map.triggerRepaint()` instead of
 *  reading the canvas synchronously. Tests must locate the registered
 *  render callback and invoke it to simulate the next render frame. */
function fireRenderCallback(mockMap: ReturnType<typeof createMockMap>): void {
  const renderCall = mockMap.once.mock.calls.find(
    (c: unknown[]) => c[0] === 'render',
  );
  if (!renderCall) return;
  const cb = renderCall[1] as () => void;
  cb();
}

/** The real SaveState accepted by useBuilderSave. */
type SaveState = Parameters<typeof useBuilderSave>[0];

/**
 * Test factory that returns a fully-typed SaveState with sensible defaults.
 * Mock map instances are cast once here so call sites stay `as any`-free.
 */
function makeSaveState(overrides: Partial<SaveState> = {}): SaveState {
  return {
    mapId: 'map-1',
    localLayers: [],
    localBasemap: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    terrainConfig: null,
    localName: 'Test Map',
    localDescription: 'A test',
    dockNotes: '',
    mapInstanceRef: { current: createMockMap() } as unknown as SaveState['mapInstanceRef'],
    setHasUnsavedChanges: vi.fn(),
    hasUnsavedChanges: false,
    hasThumbnail: true,
    ...overrides,
  };
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Layer 1',
    dataset_geometry_type: 'MULTIPOLYGON',
    dataset_table_name: 'layer_1',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    filter: null,
    label_config: null,
    style_config: null,
    show_in_legend: true,
    ...overrides,
  };
}

function renderHookWithQueryClient(state: SaveState, queryClient: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        TooltipProvider,
        null,
        createElement(MemoryRouter, null, children),
      ),
    );
  }

  return baseRenderHook(() => useBuilderSave(state), { wrapper: Wrapper });
}

/* ── Tests ─────────────────────────────────────────── */

describe('buildLayerDiff', () => {
  it('classifies added layers without baseline IDs', () => {
    const added = makeLayer({ id: 'new-layer', dataset_id: 'dataset-new', sort_order: 0 });

    const result = buildLayerDiff([], [added]);

    expect(result.unsupported).toBe(false);
    expect(result.diff.added).toEqual([
      expect.objectContaining({ dataset_id: 'dataset-new', sort_order: 0 }),
    ]);
    expect(result.diff.updated).toBeUndefined();
    expect(result.diff.removed).toBeUndefined();
  });

  it('classifies meaningful field updates by stable layer ID', () => {
    const baseline = makeLayer({ id: 'layer-1', paint: { 'fill-color': '#000000' } });
    const current = makeLayer({ id: 'layer-1', paint: { 'fill-color': '#ff0000' } });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([
      { id: 'layer-1', paint: { 'fill-color': '#ff0000' } },
    ]);
  });

  it('persists canonical paint after a stale property is cleared', () => {
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const baseline = makeLayer({
      id: 'layer-1',
      dataset_geometry_type: 'LineString',
      paint: { 'line-color': '#111827', 'line-width': 4, 'line-gradient': gradient },
    });
    const current = makeLayer({
      id: 'layer-1',
      dataset_geometry_type: 'LineString',
      paint: { 'line-color': '#f97316', 'line-width': 4 },
    });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([
      { id: 'layer-1', paint: { 'line-color': '#f97316', 'line-width': 4 } },
    ]);
    expect(result.diff.updated?.[0].paint).not.toHaveProperty('line-gradient');
    expect(result.diff.updated?.[0].paint).not.toHaveProperty('clear_paint');
  });

  it('classifies removed layers by stable layer ID', () => {
    const baseline = makeLayer({ id: 'layer-1' });

    const result = buildLayerDiff([baseline], []);

    expect(result.diff.removed).toEqual(['layer-1']);
  });

  it('classifies reordered layers by stable layer ID order', () => {
    const layer1 = makeLayer({ id: 'layer-1', sort_order: 0 });
    const layer2 = makeLayer({ id: 'layer-2', sort_order: 1 });
    const current1 = makeLayer({ id: 'layer-1', sort_order: 1 });
    const current2 = makeLayer({ id: 'layer-2', sort_order: 0 });

    const result = buildLayerDiff([layer1, layer2], [current2, current1]);

    expect(result.diff.order).toEqual(['layer-2', 'layer-1']);
  });

  it('returns an empty diff for no-op layers', () => {
    const baseline = makeLayer({ id: 'layer-1' });
    const current = makeLayer({ id: 'layer-1' });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff).toEqual({});
  });

  it('ignores dataset metadata changes that are not saved on map layers', () => {
    const baseline = makeLayer({ id: 'layer-1', dataset_name: 'Old name', dataset_feature_count: 10 });
    const current = makeLayer({ id: 'layer-1', dataset_name: 'New name', dataset_feature_count: 25 });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff).toEqual({});
  });
});

describe('useBuilderSave', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // SP-16: clear any pending debounced thumbnail captures from a prior test
    // so module-level state doesn't bleed across cases.
    __resetThumbnailDebounceForTests();
    mockEnabledWidgets.value = null;
    mockUpdateMapMutateAsync.mockImplementation(async (payload) => {
      mockMutate(payload);
      return { id: payload.id, layers: [] };
    });
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
    mockDuplicateMapMutateAsync.mockResolvedValue({ id: 'new-map-1', excluded_layer_count: 0 });
    useWidgetStore.getState().replace([]);
  });

  it('handleSave calls updateMap.mutate with correct payload', () => {
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const [payload] = mockMutate.mock.calls[0];
    expect(payload.id).toBe('map-1');
    expect(payload.data.name).toBe('Test Map');
    expect(payload.data.basemap_style).toBe('openfreemap-positron');
    expect(payload.data.basemap_config).toBeNull();
    expect(payload.data.terrain_config).toBeNull();
    expect(payload.data.center_lng).toBe(-73.9);
    expect(payload.data.center_lat).toBe(40.7);
    expect(payload.data.zoom).toBe(10);
    expect(payload.data.layers).toBeUndefined();
  });

  it('uses layer PATCH for meaningful layer changes and saves metadata separately', async () => {
    const baseline = makeLayer({ paint: { 'fill-color': '#000000' } });
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledWith({
      id: 'map-1',
      diff: { updated: [{ id: 'layer-1', paint: { 'fill-color': '#ff0000' } }] },
    });
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.not.objectContaining({ layers: expect.any(Array) }),
      }),
    );
    expect(state.setHasUnsavedChanges).toHaveBeenCalledWith(false);
  });

  it('persists terrain config in metadata saves without forcing layer replacement', async () => {
    const state = makeSaveState({
      terrainConfig: {
        enabled: true,
        source_dataset_id: 'dem-dataset-1',
        exaggeration: 1.8,
      },
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.objectContaining({
          terrain_config: {
            enabled: true,
            source_dataset_id: 'dem-dataset-1',
            exaggeration: 1.8,
          },
        }),
      }),
    );
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('saves duplicate renderings, basemap config, terrain config, and zoom range through existing fields', async () => {
    const layerA = makeLayer({
      id: 'layer-a',
      dataset_id: 'dataset-shared',
      display_name: 'Shared fill',
      sort_order: 0,
      layout: { _minzoom: 0, _maxzoom: 22 },
    });
    const layerB = makeLayer({
      id: 'layer-b',
      dataset_id: 'dataset-shared',
      display_name: 'Shared outline',
      sort_order: 1,
      paint: { 'fill-outline-color': '#111111' },
    });
    let state = makeSaveState({ localLayers: [layerA, layerB] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    state = makeSaveState({
      localLayers: [
        makeLayer({
          ...layerA,
          layout: { _minzoom: 3, _maxzoom: 17 },
        }),
        layerB,
      ],
      localBasemap: 'openfreemap-dark',
      showBasemapLabels: false,
      basemapConfig: {
        label_mode: 'hidden',
        road_visibility: 'subtle',
        boundary_visibility: 'hidden',
        building_visibility: false,
        land_water_tone: 'contrast',
        relief_contrast: 'strong',
      },
      terrainConfig: {
        enabled: true,
        source_dataset_id: 'dataset-dem',
        exaggeration: 2.25,
      },
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledWith({
      id: 'map-1',
      diff: {
        updated: [{ id: 'layer-a', layout: { _minzoom: 3, _maxzoom: 17 } }],
      },
    });
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.objectContaining({
          basemap_style: 'openfreemap-dark',
          show_basemap_labels: false,
          basemap_config: {
            label_mode: 'hidden',
            road_visibility: 'subtle',
            boundary_visibility: 'hidden',
            building_visibility: false,
            land_water_tone: 'contrast',
            relief_contrast: 'strong',
          },
          terrain_config: {
            enabled: true,
            source_dataset_id: 'dataset-dem',
            exaggeration: 2.25,
          },
        }),
      }),
    );
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('persists basemap_config.opacity when set via masterOpacity', async () => {
    const layer = makeLayer();
    let state = makeSaveState({ localLayers: [layer] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    state = makeSaveState({
      localLayers: [layer],
      basemapConfig: {
        label_mode: 'full',
        road_visibility: 'full',
        boundary_visibility: 'full',
        building_visibility: true,
        land_water_tone: 'default',
        relief_contrast: null,
        opacity: 0.55,
      },
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          basemap_config: expect.objectContaining({ opacity: 0.55 }),
        }),
      }),
    );
  });

  it('skips layer PATCH when the layer diff is empty', async () => {
    const layer = makeLayer();
    let state = makeSaveState({ localLayers: [layer] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({ localLayers: [layer], hasUnsavedChanges: true });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('falls back to full layer replacement when PATCH returns a structural error', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      new ApiError('Layer order references unknown or removed layers', 400, 'Layer order references unknown or removed layers'),
    );
    const baseline = makeLayer({ paint: { 'fill-color': '#000000' } });
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.objectContaining({
          layers: [expect.objectContaining({ dataset_id: 'dataset-1', paint: { 'fill-color': '#ff0000' } })],
        }),
      }),
    );
    expect(state.setHasUnsavedChanges).toHaveBeenCalledWith(false);
  });

  it('does not clear unsaved changes when save fails', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(new Error('network down'));
    const baseline = makeLayer({ paint: { 'fill-color': '#000000' } });
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(state.setHasUnsavedChanges).not.toHaveBeenCalledWith(false);
    expect(result.current.saveStatus).toBe('failed');
    expect(result.current.isSaveRetryable).toBe(true);
  });

  it('surfaces popupConfigInvalidNamed toast with dedupe id + extended duration for named layer (Test A)', async () => {
    const { toast } = await import('sonner');
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [
        makeLayer({
          display_name: 'My Test Layer',
          popup_config: { enabled: true, expression: '{{missing_column}}', visible_fields: null },
          dataset_column_info: [{ name: 'present_column', type: 'text' }],
        }),
      ],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    // t() mock returns the key; we verify the NEW key (not popupConfigInvalid) is used
    // and the toast options preserve dedupe id + extended duration
    expect(toast.error).toHaveBeenCalledWith(
      'toasts.popupConfigInvalidNamed',
      expect.objectContaining({ id: 'popup-config-invalid', duration: 6000 }),
    );
    expect(mockUpdateMapMutateAsync).not.toHaveBeenCalled();
    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
  });

  it('surfaces popupConfigInvalidNamed toast with fallback name when display_name is null (Test B)', async () => {
    const { toast } = await import('sonner');
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [
        makeLayer({
          display_name: null,
          popup_config: { enabled: true, expression: '{{missing_column}}', visible_fields: null },
          dataset_column_info: [{ name: 'present_column', type: 'text' }],
        }),
      ],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    // Same key, same options — fallback name path also goes through popupConfigInvalidNamed
    expect(toast.error).toHaveBeenCalledWith(
      'toasts.popupConfigInvalidNamed',
      expect.objectContaining({ id: 'popup-config-invalid', duration: 6000 }),
    );
    expect(mockUpdateMapMutateAsync).not.toHaveBeenCalled();
    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
  });

  it('allows save when popup is enabled but dataset_column_info is null (CR-01 regression)', async () => {
    // dataset_column_info is null (column metadata not yet fetched).
    // Pre-check must skip validation and let the server be the authoritative gate.
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [
        makeLayer({
          popup_config: { enabled: true, expression: '{{some_column}}', visible_fields: null },
          dataset_column_info: null,
        }),
      ],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    // Save must proceed — no blocking toast, mutation called
    const { toast } = await import('sonner');
    expect(toast.error).not.toHaveBeenCalledWith(
      'toasts.popupConfigInvalidNamed',
      expect.anything(),
    );
    expect(mockUpdateMapMutateAsync).toHaveBeenCalled();
  });

  it('routes backend 422 popup_config rejection to popupConfigBackendRejected toast (Test C)', async () => {
    const { toast } = await import('sonner');
    // Layer has no popup_config — bypasses frontend pre-check; save proceeds to API
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [makeLayer({ popup_config: null })],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    // Reject with a FastAPI 422 whose detail array tags popup_config
    mockUpdateMapMutateAsync.mockRejectedValueOnce(
      new ApiError('Unprocessable Entity', 422, [
        { loc: ['body', 'layers', 0, 'popup_config', 'expression'], msg: 'String should have at most 500 characters', type: 'string_too_long' },
      ]),
    );

    await act(async () => {
      await result.current.handleSave();
    });

    // t() mock returns the key; verify it is the popup-specific key, not saveFailed
    expect(toast.error).toHaveBeenCalledWith(
      'toasts.popupConfigBackendRejected',
      expect.anything(),
    );
    expect(result.current.saveStatus).toBe('failed');
  });

  it('routes non-popup ApiError (500) to generic saveFailed toast (Test D)', async () => {
    const { toast } = await import('sonner');
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [makeLayer({ popup_config: null })],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    mockUpdateMapMutateAsync.mockRejectedValueOnce(new ApiError('Server Error', 500, undefined));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(toast.error).toHaveBeenCalledWith('toasts.saveFailed');
    expect(result.current.saveStatus).toBe('failed');
  });

  it('omits widgets when active widgets match client defaults already saved as defaults', () => {
    useWidgetStore.getState().open('legend');
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.widgets).toBeUndefined();
  });

  it('sends widgets null when active widgets return to client defaults from explicit state', () => {
    useWidgetStore.getState().open('legend');
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    queryClient.setQueryData(queryKeys.maps.detail('map-1'), { widgets: [] });
    const state = makeSaveState();
    const { result } = renderHookWithQueryClient(state, queryClient);

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.widgets).toBeNull();
  });

  it('persists explicit widget state when it differs from client defaults', () => {
    useWidgetStore.getState().open('legend');
    useWidgetStore.getState().open('measurement');
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.widgets).toEqual(['legend', 'measurement']);
  });

  it('does not persist admin-disabled active widgets', () => {
    mockEnabledWidgets.value = ['legend'];
    useWidgetStore.getState().open('legend');
    useWidgetStore.getState().open('measurement');
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.widgets).toBeUndefined();
  });

  it('handleSave is a no-op when mapId is undefined', () => {
    const state = makeSaveState({ mapId: undefined });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    expect(mockMutate).not.toHaveBeenCalled();
  });

  it('handleFork calls duplicateMutation.mutateAsync and navigates on success', async () => {
    mockDuplicateMapMutateAsync.mockResolvedValue({ id: 'new-map-1', excluded_layer_count: 0 });
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleFork();
    });

    expect(mockDuplicateMapMutateAsync).toHaveBeenCalledWith('map-1');
    // toast.success should be called for successful fork
    const { toast } = await import('sonner');
    expect(toast.success).toHaveBeenCalled();
  });

  it('handleFork shows warning toast when excluded_layer_count > 0', async () => {
    mockDuplicateMapMutateAsync.mockResolvedValue({ id: 'new-map-2', excluded_layer_count: 3 });
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleFork();
    });

    const { toast } = await import('sonner');
    expect(toast.warning).toHaveBeenCalled();
  });

  it('handleExportPNG captures immediately when map is loaded', () => {
    const mockMap = createMockMap({ loaded: true });
    const state = makeSaveState({ mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'] });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleExportPNG();
    });

    // PERF-08 (Phase 274): export now registers `once('render', ...)` and
    // triggers a repaint instead of reading the canvas inline. Simulate the
    // render event firing so the canvas-read path runs.
    expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
    expect(mockMap.triggerRepaint).toHaveBeenCalled();
    act(() => { fireRenderCallback(mockMap); });

    expect(mockMap.getCanvas).toHaveBeenCalled();
    expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));
  });

  it('Ctrl+S keydown calls handleSave', () => {
    const state = makeSaveState();
    renderHook(() => useBuilderSave(state));

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true }),
      );
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it('returns blocker from hook', () => {
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    expect(result.current.blocker).toBeDefined();
    expect(result.current.blocker.state).toBe('unblocked');
  });

  it('adds beforeunload listener when hasUnsavedChanges is true', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const state = makeSaveState({ hasUnsavedChanges: true });
    const { unmount } = renderHook(() => useBuilderSave(state));

    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it('does not add beforeunload listener when hasUnsavedChanges is false', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');

    const state = makeSaveState({ hasUnsavedChanges: false });
    renderHook(() => useBuilderSave(state));

    const beforeUnloadCalls = addSpy.mock.calls.filter(
      ([event]) => event === 'beforeunload',
    );
    expect(beforeUnloadCalls).toHaveLength(0);

    addSpy.mockRestore();
  });

  it('isSaving reflects updateMap.isPending state', () => {
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    // Default mock returns isPending: false
    expect(result.current.isSaving).toBe(false);
  });

  describe('captureThumbnail (via handleSave onSuccess)', () => {
    const origCreateElement = document.createElement.bind(document);
    let createElementSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });
    });

    afterEach(() => {
      createElementSpy.mockRestore();
    });

    async function triggerSaveSuccess(mockMap: ReturnType<typeof createMockMap>) {
      const state = makeSaveState({ mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'] });
      const { result } = renderHook(() => useBuilderSave(state));
      await act(async () => { await result.current.handleSave(); });
      return result;
    }

    it('captures immediately when map is already loaded', async () => {
      // SP-16: captureThumbnail is now wrapped in a 500ms trailing
      // debounce; advance fake timers past the boundary to drive the
      // capture path that this test exercises.
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      await triggerSaveSuccess(mockMap);

      // Before the debounce boundary, no capture has been requested.
      expect(mockMap.once).not.toHaveBeenCalledWith('render', expect.any(Function));

      act(() => { vi.advanceTimersByTime(500); });

      // PERF-08 (Phase 274): doCapture registers `once('render', ...)` then
      // calls triggerRepaint(); fire the render callback to simulate the
      // next animation frame.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockMap.getCanvas).toHaveBeenCalled();
      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));

      vi.useRealTimers();
    });

    it('defers capture via idle event when map is not loaded', async () => {
      // SP-16: the 500ms debounce sits in front of whenMapIdle now;
      // advance past it to reach the idle-deferral path.
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

      act(() => { vi.advanceTimersByTime(500); });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
      // Not captured yet
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Simulate idle event — this registers `once('render', ...)` per PERF-08.
      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;
      act(() => { idleCallback(); });

      // Idle alone is not enough now; render frame has to fire.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();

      // The uploadThumbnail microtask resolves on real timers.
      vi.useRealTimers();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
    });

    it('timeout captures and removes idle listener when idle never fires', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

      // SP-16: clear the 500ms debounce first so the whenMapIdle safety
      // timer (which fires at +3000ms after the debounce flushes) becomes
      // observable.
      act(() => { vi.advanceTimersByTime(500); });
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Advance past 3s timeout — whenMapIdle's safety timer fires the
      // capture path, which now registers `once('render', ...)`.
      act(() => { vi.advanceTimersByTime(3000); });

      expect(mockMap.off).toHaveBeenCalledWith('idle', expect.any(Function));
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();

      // Simulate the render frame (PERF-08).
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('idle event clears timeout to prevent double-capture', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

      // SP-16: advance past the 500ms trailing debounce so the
      // whenMapIdle path runs and registers the idle listener.
      act(() => { vi.advanceTimersByTime(500); });

      // Simulate idle event fires quickly — this registers the render
      // listener (PERF-08) but does not yet capture.
      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;
      act(() => { idleCallback(); });

      // Fire the render frame to actually capture pixels.
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      // Advance past timeout — should NOT double-capture
      act(() => { vi.advanceTimersByTime(3000); });

      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });
  });

  // SP-16: trailing 500ms debounce around the captureThumbnail entry point.
  // Two back-to-back saves (or save + maybeAutoCaptureThumbnail) within
  // 500ms must collapse into exactly one capture → one PUT /thumbnail/.
  describe('SP-16 — captureThumbnail trailing debounce', () => {
    const origCreateElement = document.createElement.bind(document);
    let createElementSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });
    });

    afterEach(() => {
      createElementSpy.mockRestore();
    });

    function renderCallbackCount(mockMap: ReturnType<typeof createMockMap>): number {
      return mockMap.once.mock.calls.filter((c: unknown[]) => c[0] === 'render').length;
    }

    it('coalesces two saves within 500ms into a single capture (one render-frame registration)', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      const state = makeSaveState({
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });
      const { result } = renderHook(() => useBuilderSave(state));

      // Two back-to-back saves 100ms apart. The second save resets the
      // debounce timer; the trailing edge fires 500ms after that LATEST
      // call, i.e. at t = 100 + 500 = 600ms. Before then no capture (and
      // therefore no `once('render')` registration) should occur.
      await act(async () => { await result.current.handleSave(); });
      act(() => { vi.advanceTimersByTime(100); });
      await act(async () => { await result.current.handleSave(); });

      expect(renderCallbackCount(mockMap)).toBe(0);
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Advance to just before the 500ms trailing boundary from the second save.
      act(() => { vi.advanceTimersByTime(499); });
      expect(renderCallbackCount(mockMap)).toBe(0);

      // Cross the boundary — exactly one capture fires for the final state,
      // not two: the first save's debounced capture was cancelled by the second.
      act(() => { vi.advanceTimersByTime(1); });
      expect(renderCallbackCount(mockMap)).toBe(1);

      // Fire the single registered render frame to drive the upload.
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('a single save still results in exactly one capture after the 500ms window', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      const state = makeSaveState({
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });
      const { result } = renderHook(() => useBuilderSave(state));

      await act(async () => { await result.current.handleSave(); });

      // No capture before the trailing edge.
      expect(renderCallbackCount(mockMap)).toBe(0);
      act(() => { vi.advanceTimersByTime(499); });
      expect(renderCallbackCount(mockMap)).toBe(0);

      // At/after 500ms one capture fires.
      act(() => { vi.advanceTimersByTime(1); });
      expect(renderCallbackCount(mockMap)).toBe(1);

      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });
  });

  describe('handleExportPNG (idle handling)', () => {
    it('defers export via idle event when map is not loaded', () => {
      const mockMap = createMockMap({ loaded: false });
      const state = makeSaveState({ mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'] });
      const { result } = renderHook(() => useBuilderSave(state));

      act(() => { result.current.handleExportPNG(); });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });
  });

  describe('maybeAutoCaptureThumbnail', () => {
    it('waits for visible layer sources before capturing a missing thumbnail', async () => {
      vi.useFakeTimers();
      const origCreateElement = document.createElement.bind(document);
      const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });

      const sources = new Map<string, object>();
      const mockMap = createMockMap({ loaded: false });
      mockMap.getSource.mockImplementation((sourceId: string) => sources.get(sourceId));

      const state = makeSaveState({
        hasThumbnail: false,
        localLayers: [makeLayer()],
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });

      const { result } = renderHook(() => useBuilderSave(state));

      act(() => {
        result.current.maybeAutoCaptureThumbnail(mockMap as never);
      });

      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(1000);
      });

      expect(mockUploadThumbnail).not.toHaveBeenCalled();
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));

      act(() => {
        // CR-01 (Phase 1050-rev): waitForVisibleLayerSources now routes
        // through `getSourceIdForLayer`, so non-cluster vector layers with
        // a `dataset_table_name` resolve to the deduped
        // `source-data-${table}` key, not the legacy `source-${layer.id}`.
        sources.set('source-data-layer_1', { type: 'vector' });
        vi.advanceTimersByTime(100);
      });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;

      act(() => {
        idleCallback();
      });

      // PERF-08 (Phase 274): idle alone schedules the render listener; the
      // render frame must fire to actually upload pixels.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();

      // Use real timers briefly to let the uploadThumbnail microtask resolve.
      vi.useRealTimers();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockUploadThumbnail).toHaveBeenCalledWith(
        'map-1',
        expect.stringContaining('data:image/jpeg'),
      );

      createElementSpy.mockRestore();
    });

    // SF-07 (Phase 1050-04): in Vite dev StrictMode (and any case where the
    // ref-callback in MapBuilderPage fires twice for the same `map`), the
    // per-hook-instance `thumbCaptured` guard resets on remount, letting a
    // second auto-capture slip through after the first's debounce window has
    // already fired and the PUT has been issued. The fix tracks per-mapId
    // auto-capture initiation at module scope so a second hook instance for
    // the same map is idempotent.
    describe('SF-07 — single PUT per initial map mount', () => {
      const origCreateElement = document.createElement.bind(document);
      let createElementSpy: ReturnType<typeof vi.spyOn>;

      beforeEach(() => {
        createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
          if (tag === 'canvas') {
            return createMockCanvas() as unknown as HTMLCanvasElement;
          }
          return origCreateElement(tag, options);
        });
      });

      afterEach(() => {
        createElementSpy.mockRestore();
      });

      it('collapses two synchronous maybeAutoCaptureThumbnail calls into exactly one PUT', async () => {
        vi.useFakeTimers();
        const mockMap = createMockMap({ loaded: true });
        const state = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        const { result } = renderHook(() => useBuilderSave(state));

        act(() => {
          result.current.maybeAutoCaptureThumbnail(mockMap as never);
          result.current.maybeAutoCaptureThumbnail(mockMap as never);
        });

        act(() => { vi.advanceTimersByTime(500); });

        // Exactly one render-frame registration — the debounce collapses
        // both calls into one capture.
        const renderCalls = mockMap.once.mock.calls.filter((c: unknown[]) => c[0] === 'render');
        expect(renderCalls).toHaveLength(1);

        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);
      });

      it('survives a StrictMode-style hook remount (second hook instance for the same mapId does NOT fire a second PUT)', async () => {
        vi.useFakeTimers();
        const mockMap = createMockMap({ loaded: true });
        const state1 = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        // First hook instance fires auto-capture
        const { result: result1, unmount: unmount1 } = renderHook(() => useBuilderSave(state1));
        act(() => { result1.current.maybeAutoCaptureThumbnail(mockMap as never); });

        // Let the first capture's debounce settle and issue its PUT before remount.
        act(() => { vi.advanceTimersByTime(500); });
        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

        // Snapshot how many render-frame registrations have happened so we
        // can detect any extra ones from the second hook instance.
        const renderCallsAfterFirst = mockMap.once.mock.calls.filter(
          (c: unknown[]) => c[0] === 'render',
        ).length;

        // Simulate StrictMode unmount + remount of the hook (component-level
        // `thumbCaptured` ref resets), with a fresh second hook instance for
        // the SAME mapId being asked to auto-capture again.
        unmount1();
        const state2 = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });
        vi.useFakeTimers();
        const { result: result2 } = renderHook(() => useBuilderSave(state2));
        act(() => { result2.current.maybeAutoCaptureThumbnail(mockMap as never); });
        act(() => { vi.advanceTimersByTime(1000); });

        // Module-level guard must prevent a second capture for this mapId,
        // even though the new hook instance has a fresh thumbCaptured ref.
        // Verify via render-frame registrations (the deterministic signal
        // before the async fireRenderCallback step would otherwise lift the
        // PUT count).
        const renderCallsAfterSecond = mockMap.once.mock.calls.filter(
          (c: unknown[]) => c[0] === 'render',
        ).length;
        expect(renderCallsAfterSecond).toBe(renderCallsAfterFirst);

        vi.useRealTimers();
        await act(async () => { await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);
      });

      it('reset helper clears the module-level guard so a fresh test (or page) can auto-capture again', async () => {
        vi.useFakeTimers();
        const mockMap = createMockMap({ loaded: true });
        const state = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        const { result } = renderHook(() => useBuilderSave(state));
        act(() => { result.current.maybeAutoCaptureThumbnail(mockMap as never); });
        act(() => { vi.advanceTimersByTime(500); });
        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

        // After clearing the module-level guard, a fresh hook instance for
        // the same mapId may auto-capture again (mirrors the page-navigation
        // / new-session reload case where the in-memory module re-evaluates).
        __resetThumbnailDebounceForTests();

        vi.useFakeTimers();
        const { result: result2 } = renderHook(() => useBuilderSave(state));
        act(() => { result2.current.maybeAutoCaptureThumbnail(mockMap as never); });
        act(() => { vi.advanceTimersByTime(500); });
        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

        expect(mockUploadThumbnail).toHaveBeenCalledTimes(2);
      });
    });

    // CR-01 (Phase 1050-rev): regression — verify that the source-readiness
    // poll resolves on the dedupe-aware key (`source-data-{dataset_table_name}`)
    // and the render frame fires WITHOUT advancing past the 5000 ms deadline.
    // Before the fix, `waitForVisibleLayerSources` polled `source-{layer.id}`
    // (legacy key) and never found the deduped source, causing every
    // non-cluster vector auto-capture to wait the full 5s timeout.
    it('CR-01: resolves source-readiness on the deduped source id before the 5s deadline', async () => {
      vi.useFakeTimers();
      const origCreateElement = document.createElement.bind(document);
      const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });

      const sources = new Map<string, object>();
      const mockMap = createMockMap({ loaded: false });
      mockMap.getSource.mockImplementation((sourceId: string) => sources.get(sourceId));

      const state = makeSaveState({
        hasThumbnail: false,
        // dataset_table_name: 'shared_table' → dedupe key 'source-data-shared_table'
        localLayers: [makeLayer({ id: 'layer-99', dataset_table_name: 'shared_table' })],
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });

      const { result } = renderHook(() => useBuilderSave(state));

      act(() => {
        result.current.maybeAutoCaptureThumbnail(mockMap as never);
      });

      // Walk the trailing-edge debounce (500 ms) so `runCaptureNow` fires
      // and the source-readiness poll begins.
      act(() => { vi.advanceTimersByTime(500); });
      // No idle listener yet — source is not registered yet.
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));

      // Seed the deduped source key (NOT the legacy `source-${id}` key) and
      // advance 100 ms — the next poll tick should resolve immediately.
      act(() => {
        sources.set('source-data-shared_table', { type: 'vector' });
        vi.advanceTimersByTime(100);
      });

      // poll has resolved → idle listener registered well before the 5s mark
      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));

      // Sanity: legacy key was NEVER queried after fix
      const legacyKeyQueried = mockMap.getSource.mock.calls.some(
        (c: unknown[]) => c[0] === 'source-layer-99',
      );
      expect(legacyKeyQueried).toBe(false);

      createElementSpy.mockRestore();
      vi.useRealTimers();
    });
  });
});
