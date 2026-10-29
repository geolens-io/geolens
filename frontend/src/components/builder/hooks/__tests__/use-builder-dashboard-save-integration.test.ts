/**
 * A dashboard edit must survive the saved dashboard changing under it: an
 * edit made while a save is in flight, and the whole edit when a save stores
 * the layers but not the dashboard. Wires useBuilderLayers and useBuilderSave
 * together as MapBuilderPage does.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useRef } from 'react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import { useBuilderSave, __resetThumbnailDebounceForTests, type SaveBaselineSync } from '@/components/builder/hooks/use-builder-save';
import { makeBuilderLayer, makeBuilderMap } from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

const mockUpdateMapMutateAsync = vi.fn();
const mockPatchMapLayersMutateAsync = vi.fn();

vi.mock('@/hooks/use-maps', () => ({
  useUpdateMap: () => ({ mutateAsync: mockUpdateMapMutateAsync, isPending: false }),
  usePatchMapLayers: () => ({ mutateAsync: mockPatchMapLayersMutateAsync, isPending: false }),
  useDuplicateMap: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledPlugins: () => ({ data: null, isLoading: false }),
  useTileConfig: () => ({ data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' } }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({ edition: 'community', features: [], isEnterprise: false, isLoading: false }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

vi.mock('@/api/maps', () => ({
  getMap: vi.fn(),
  uploadThumbnail: vi.fn(() => Promise.resolve()),
  uploadOgImage: vi.fn(() => Promise.resolve()),
}));

const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useBlocker: () => mockBlocker };
});

function useCombinedBuilder(mapData: MapResponse) {
  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    'map-1',
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3],
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4],
    saveBaselineSyncRef,
  );
  const save = useBuilderSave({
    mapId: 'map-1',
    localLayers: layers.localLayers,
    groupMeta: layers.groupMeta,
    localBasemap: layers.localBasemap,
    showBasemapLabels: layers.showBasemapLabels,
    basemapConfig: layers.basemapConfig,
    terrainConfig: layers.localTerrainConfig,
    localName: layers.localName,
    localDescription: layers.localDescription,
    legendTitle: layers.localLegendTitle,
    dockNotes: '',
    dashboard: layers.dashboard,
    savedDashboard: layers.savedDashboard,
    dashboardEdited: layers.dashboardEdited,
    onDashboardSave: layers.beginDashboardSave,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasUnsavedEdits: layers.hasUnsavedEdits,
    hasThumbnail: true,
    saveBaselineSyncRef,
    saveFence: layers.saveFence,
  });
  return { ...layers, ...save };
}

const columns = [{ name: 'kind', type: 'text' }];
const layerA = makeBuilderLayer({
  id: '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34',
  dataset_record_type: 'vector_dataset',
  dataset_column_info: columns,
});
const layerB = makeBuilderLayer({
  id: '2d9f4a6b-5e3c-4a0d-9b8f-7c4e9a3d1f56',
  dataset_id: 'ds-2',
  sort_order: 1,
  dataset_record_type: 'vector_dataset',
  dataset_column_info: columns,
});
const widget = (id: string, layerId: string, title?: string) => ({
  id,
  type: 'indicator' as const,
  v: 1 as const,
  layer_id: layerId,
  scope: 'layer' as const,
  ...(title ? { title } : {}),
  config: { stat: 'count' as const, column: null },
});
const onA = widget('6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11', layerA.id);
const onB = widget('9a2b4c6d-1e3f-4a5b-8c7d-0e1f2a3b4c5d', layerB.id);

function mapWith(layers: typeof layerA[], panel: 'right' | 'bottom', widgets: unknown[]): MapResponse {
  return { ...makeBuilderMap(layers), dashboard_config: { version: 1, panel, widgets } } as MapResponse;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('Builder dashboard edits across a save', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetThumbnailDebounceForTests();
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
  });

  it('keeps an edit made between sending the save and its response', async () => {
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), {
      initialProps: { mapData: mapWith([layerA], 'right', [onA]) },
    });
    act(() => result.current.handleDashboardChange({ ...result.current.dashboard, panel: 'bottom' }));

    const put = deferred<unknown>();
    mockUpdateMapMutateAsync.mockReturnValueOnce(put.promise);
    let saving!: Promise<void>;
    act(() => {
      saving = result.current.handleSave();
    });
    // Edited while the PUT is in flight.
    act(() =>
      result.current.handleDashboardChange({
        ...result.current.dashboard,
        widgets: [{ ...onA, title: 'Later' }],
      }),
    );
    await act(async () => {
      put.resolve({ id: 'map-1' });
      await saving;
    });
    // The refetch brings back what the save sent.
    rerender({ mapData: mapWith([layerA], 'bottom', [onA]) });

    expect(result.current.dashboard.widgets[0].title).toBe('Later');
    expect(result.current.hasUnsavedChanges).toBe(true);
    // The response was our own save, not another editor's change.
    const { toast } = await import('sonner');
    expect(toast.warning).not.toHaveBeenCalled();

    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    const resent = mockUpdateMapMutateAsync.mock.calls[1][0].data.dashboard_config;
    expect(resent.widgets[0].title).toBe('Later');
  });

  it('takes another editor\'s dashboard over an edit that was put back, and never sends the old one', async () => {
    const { toast } = await import('sonner');
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), {
      initialProps: { mapData: mapWith([layerA, layerB], 'right', [onA]) },
    });
    act(() => result.current.handleDashboardChange({ ...result.current.dashboard, panel: 'bottom' }));
    act(() => result.current.handleDashboardChange({ ...result.current.dashboard, panel: 'right' }));
    expect(result.current.dashboardEdited).toBe(false);

    // Another editor added a widget.
    rerender({ mapData: mapWith([layerA, layerB], 'right', [onA, onB]) });
    expect(result.current.dashboard.widgets.map((w) => w.id)).toEqual([onA.id, onB.id]);
    expect(toast.warning).not.toHaveBeenCalled();

    act(() => result.current.handlePaintChange(layerA.id, { 'fill-color': '#123456' }));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data).not.toHaveProperty('dashboard_config');
  });

  it('settles a bottom dashboard emptied and saved, which the server stores as none', async () => {
    const { toast } = await import('sonner');
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), {
      initialProps: { mapData: mapWith([layerA], 'bottom', [onA]) },
    });
    act(() => result.current.handleDashboardChange({ ...result.current.dashboard, widgets: [] }));

    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.dashboard_config).toBeNull();
    // The refetch: no dashboard at all.
    rerender({ mapData: { ...mapWith([layerA], 'right', []), dashboard_config: null } as MapResponse });

    expect(toast.warning).not.toHaveBeenCalled();
    expect(result.current.dashboardEdited).toBe(false);

    act(() => result.current.handlePaintChange(layerA.id, { 'fill-color': '#123456' }));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[1][0].data).not.toHaveProperty('dashboard_config');
  });

  it('settles a save that dropped the widget of a layer removed before it', async () => {
    const { toast } = await import('sonner');
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), {
      initialProps: { mapData: mapWith([layerA, layerB], 'right', [onA, onB]) },
    });
    act(() =>
      result.current.handleDashboardChange({
        ...result.current.dashboard,
        widgets: [{ ...onA, title: 'Renamed' }, onB],
      }),
    );
    act(() => result.current.handleRemove(layerB.id));

    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.dashboard_config.widgets.map((w: { id: string }) => w.id)).toEqual([onA.id]);
    // The refetch: layer B and its widget are gone.
    rerender({ mapData: mapWith([layerA], 'right', [{ ...onA, title: 'Renamed' }]) });

    expect(toast.warning).not.toHaveBeenCalled();
    expect(result.current.dashboardEdited).toBe(false);
    expect(result.current.dashboard.widgets.map((w) => w.id)).toEqual([onA.id]);

    act(() => result.current.handlePaintChange(layerA.id, { 'fill-color': '#123456' }));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[1][0].data).not.toHaveProperty('dashboard_config');
  });

  it('keeps an edit made during a save, without the widget of a layer removed before it', async () => {
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), {
      initialProps: { mapData: mapWith([layerA, layerB], 'right', [onA, onB]) },
    });
    act(() => result.current.handleDashboardChange({ ...result.current.dashboard, panel: 'bottom' }));
    act(() => result.current.handleRemove(layerB.id));

    const put = deferred<unknown>();
    mockUpdateMapMutateAsync.mockReturnValueOnce(put.promise);
    let saving!: Promise<void>;
    act(() => {
      saving = result.current.handleSave();
    });
    act(() =>
      result.current.handleDashboardChange({ ...result.current.dashboard, widgets: [{ ...onA, title: 'Later' }, onB] }),
    );
    await act(async () => {
      put.resolve({ id: 'map-1' });
      await saving;
    });
    rerender({ mapData: mapWith([layerA], 'bottom', [onA]) });

    expect(result.current.dashboardEdited).toBe(true);
    // Still open, and without the removed layer's widget.
    expect(result.current.dashboard.widgets.map((w) => w.id)).toEqual([onA.id]);
    expect(result.current.dashboard.widgets[0].title).toBe('Later');
  });

  it('keeps the dashboard edit when the layers saved and the dashboard did not', async () => {
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), {
      initialProps: { mapData: mapWith([layerA, layerB], 'right', [onA, onB]) },
    });
    act(() => {
      result.current.handlePaintChange(layerA.id, { 'fill-color': '#123456' });
      result.current.handleDashboardChange({ ...result.current.dashboard, panel: 'bottom' });
    });
    mockUpdateMapMutateAsync.mockRejectedValueOnce(new Error('network down'));

    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalled();
    // The refetch after the layer PATCH: layer B is gone and its widget with it.
    rerender({ mapData: mapWith([layerA], 'right', [onA]) });

    expect(result.current.dashboard.panel).toBe('bottom');
    expect(result.current.hasUnsavedChanges).toBe(true);
  });
});
