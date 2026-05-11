import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { act } from '@testing-library/react';
import { renderHook as baseRenderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import { renderHook } from '@/test/test-utils';
import { buildLayerDiff, useBuilderSave } from '@/components/builder/hooks/use-builder-save';
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
      const mockMap = createMockMap({ loaded: true });
      await triggerSaveSuccess(mockMap);

      // PERF-08 (Phase 274): doCapture registers `once('render', ...)` then
      // calls triggerRepaint(); fire the render callback to simulate the
      // next animation frame.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockMap.getCanvas).toHaveBeenCalled();
      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));
    });

    it('defers capture via idle event when map is not loaded', async () => {
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

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
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
    });

    it('timeout captures and removes idle listener when idle never fires', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

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
        sources.set('source-layer-1', { type: 'vector' });
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
  });
});
