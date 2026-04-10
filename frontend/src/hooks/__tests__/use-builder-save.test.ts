import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderSave } from '@/hooks/use-builder-save';
import type { MapLayerResponse } from '@/types/api';

/* ── Mocks ─────────────────────────────────────────── */

const mockMutate = vi.fn();
const mockMutateAsync = vi.fn();

vi.mock('@/hooks/use-maps', () => ({
  useUpdateMap: () => ({
    mutate: mockMutate,
    isPending: false,
  }),
  useDuplicateMap: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
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

interface SaveState {
  mapId: string | undefined;
  localLayers: MapLayerResponse[];
  localBasemap: string;
  showBasemapLabels: boolean;
  localName: string;
  localDescription: string;
  mapInstanceRef: React.RefObject<ReturnType<typeof createMockMap> | null>;
  setHasUnsavedChanges: (v: boolean) => void;
  hasUnsavedChanges: boolean;
  hasThumbnail?: boolean;
}

function makeSaveState(overrides: Partial<SaveState> = {}): SaveState {
  return {
    mapId: 'map-1',
    localLayers: [],
    localBasemap: 'openfreemap-positron',
    showBasemapLabels: true,
    localName: 'Test Map',
    localDescription: 'A test',
    mapInstanceRef: { current: createMockMap() },
    setHasUnsavedChanges: vi.fn(),
    hasUnsavedChanges: false,
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

/* ── Tests ─────────────────────────────────────────── */

describe('useBuilderSave', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('handleSave calls updateMap.mutate with correct payload', () => {
    const state = makeSaveState();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    act(() => {
      result.current.handleSave();
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const [payload] = mockMutate.mock.calls[0];
    expect(payload.id).toBe('map-1');
    expect(payload.data.name).toBe('Test Map');
    expect(payload.data.basemap_style).toBe('openfreemap-positron');
    expect(payload.data.center_lng).toBe(-73.9);
    expect(payload.data.center_lat).toBe(40.7);
    expect(payload.data.zoom).toBe(10);
    expect(payload.data.layers).toEqual([]);
  });

  it('handleSave is a no-op when mapId is undefined', () => {
    const state = makeSaveState({ mapId: undefined });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    act(() => {
      result.current.handleSave();
    });

    expect(mockMutate).not.toHaveBeenCalled();
  });

  it('handleFork calls duplicateMutation.mutateAsync and navigates on success', async () => {
    mockMutateAsync.mockResolvedValue({ id: 'new-map-1', excluded_layer_count: 0 });
    const state = makeSaveState();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    await act(async () => {
      await result.current.handleFork();
    });

    expect(mockMutateAsync).toHaveBeenCalledWith('map-1');
    // toast.success should be called for successful fork
    const { toast } = await import('sonner');
    expect(toast.success).toHaveBeenCalled();
  });

  it('handleFork shows warning toast when excluded_layer_count > 0', async () => {
    mockMutateAsync.mockResolvedValue({ id: 'new-map-2', excluded_layer_count: 3 });
    const state = makeSaveState();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    await act(async () => {
      await result.current.handleFork();
    });

    const { toast } = await import('sonner');
    expect(toast.warning).toHaveBeenCalled();
  });

  it('handleExportPNG captures immediately when map is loaded', () => {
    const mockMap = createMockMap({ loaded: true });
    const state = makeSaveState({ mapInstanceRef: { current: mockMap } });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    act(() => {
      result.current.handleExportPNG();
    });

    expect(mockMap.getCanvas).toHaveBeenCalled();
    expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));
  });

  it('Ctrl+S keydown calls handleSave', () => {
    const state = makeSaveState();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useBuilderSave(state as any));

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true }),
      );
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it('returns blocker from hook', () => {
    const state = makeSaveState();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    expect(result.current.blocker).toBeDefined();
    expect(result.current.blocker.state).toBe('unblocked');
  });

  it('adds beforeunload listener when hasUnsavedChanges is true', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const state = makeSaveState({ hasUnsavedChanges: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { unmount } = renderHook(() => useBuilderSave(state as any));

    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it('does not add beforeunload listener when hasUnsavedChanges is false', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');

    const state = makeSaveState({ hasUnsavedChanges: false });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderHook(() => useBuilderSave(state as any));

    const beforeUnloadCalls = addSpy.mock.calls.filter(
      ([event]) => event === 'beforeunload',
    );
    expect(beforeUnloadCalls).toHaveLength(0);

    addSpy.mockRestore();
  });

  it('isSaving reflects updateMap.isPending state', () => {
    const state = makeSaveState();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

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

    function triggerSaveSuccess(mockMap: ReturnType<typeof createMockMap>) {
      const state = makeSaveState({ mapInstanceRef: { current: mockMap } });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const { result } = renderHook(() => useBuilderSave(state as any));
      act(() => { result.current.handleSave(); });
      // Call the onSuccess callback
      const [, opts] = mockMutate.mock.calls[0];
      act(() => { opts.onSuccess(); });
      return result;
    }

    it('captures immediately when map is already loaded', () => {
      const mockMap = createMockMap({ loaded: true });
      triggerSaveSuccess(mockMap);

      expect(mockMap.getCanvas).toHaveBeenCalled();
      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));
    });

    it('defers capture via idle event when map is not loaded', () => {
      const mockMap = createMockMap({ loaded: false });
      triggerSaveSuccess(mockMap);

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
      // Not captured yet
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Simulate idle event
      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;
      act(() => { idleCallback(); });

      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
    });

    it('timeout captures and removes idle listener when idle never fires', () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      triggerSaveSuccess(mockMap);

      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Advance past 3s timeout
      act(() => { vi.advanceTimersByTime(3000); });

      expect(mockMap.off).toHaveBeenCalledWith('idle', expect.any(Function));
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('idle event clears timeout to prevent double-capture', () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      triggerSaveSuccess(mockMap);

      // Simulate idle event fires quickly
      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;
      act(() => { idleCallback(); });

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
      const state = makeSaveState({ mapInstanceRef: { current: mockMap } });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const { result } = renderHook(() => useBuilderSave(state as any));

      act(() => { result.current.handleExportPNG(); });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });
  });

  describe('maybeAutoCaptureThumbnail', () => {
    it('waits for visible layer sources before capturing a missing thumbnail', () => {
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
        mapInstanceRef: { current: mockMap },
      });

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const { result } = renderHook(() => useBuilderSave(state as any));

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

      expect(mockUploadThumbnail).toHaveBeenCalledWith(
        'map-1',
        expect.stringContaining('data:image/jpeg'),
      );

      createElementSpy.mockRestore();
      vi.useRealTimers();
    });
  });
});
