import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
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

vi.mock('@/api/maps', () => ({
  uploadThumbnail: vi.fn(),
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

function createMockMap() {
  return {
    getCenter: vi.fn(() => ({ lng: -73.9, lat: 40.7 })),
    getZoom: vi.fn(() => 10),
    getBearing: vi.fn(() => 0),
    getPitch: vi.fn(() => 0),
    triggerRepaint: vi.fn(),
    once: vi.fn(),
    off: vi.fn(),
    loaded: vi.fn(() => true),
    getCanvas: vi.fn(() => ({
      width: 800,
      height: 600,
      toBlob: vi.fn(),
    })),
  };
}

interface SaveState {
  mapId: string | undefined;
  localLayers: MapLayerResponse[];
  localBasemap: string;
  localName: string;
  localDescription: string;
  mapInstanceRef: React.RefObject<ReturnType<typeof createMockMap> | null>;
  setHasUnsavedChanges: (v: boolean) => void;
  hasUnsavedChanges: boolean;
}

function makeSaveState(overrides: Partial<SaveState> = {}): SaveState {
  return {
    mapId: 'map-1',
    localLayers: [],
    localBasemap: 'carto-positron',
    localName: 'Test Map',
    localDescription: 'A test',
    mapInstanceRef: { current: createMockMap() },
    setHasUnsavedChanges: vi.fn(),
    hasUnsavedChanges: false,
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
    expect(payload.data.basemap_style).toBe('carto-positron');
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

  it('handleExportPNG triggers map repaint and registers idle callback', () => {
    const mockMap = createMockMap();
    const state = makeSaveState({ mapInstanceRef: { current: mockMap } });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { result } = renderHook(() => useBuilderSave(state as any));

    act(() => {
      result.current.handleExportPNG();
    });

    expect(mockMap.triggerRepaint).toHaveBeenCalled();
    expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
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
});
