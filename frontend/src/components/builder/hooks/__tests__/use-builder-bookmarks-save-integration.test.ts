/**
 * Bookmark edits mark the map dirty, put back they read as clean, and a save
 * sends them only when they changed. Wires useBuilderLayers and useBuilderSave
 * together as MapBuilderPage does.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import { useBuilderSave, __resetThumbnailDebounceForTests, type SaveBaselineSync } from '@/components/builder/hooks/use-builder-save';
import { makeBuilderLayer, makeBuilderMap } from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapBookmark, MapResponse } from '@/types/api';

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

function useCombinedBuilder(mapData: MapResponse, mapId = 'map-1') {
  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    mapId,
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3],
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4],
    saveBaselineSyncRef,
  );
  const save = useBuilderSave({
    mapId,
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
    bookmarks: layers.bookmarks,
    bookmarksEdited: layers.bookmarksEdited,
    onBookmarksSave: layers.beginBookmarksSave,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasUnsavedEdits: layers.hasUnsavedEdits,
    hasThumbnail: true,
    saveBaselineSyncRef,
    remapLayerIds: layers.remapLayerIds,
    saveFence: layers.saveFence,
  });
  return { ...layers, ...save };
}

const a: MapBookmark = { name: 'A', extent: [0, 0, 1, 1] };
const b: MapBookmark = { name: 'B', extent: [2, 2, 3, 3], bearing: 30 };

function mapWith(bookmarks: MapBookmark[]): MapResponse {
  return { ...makeBuilderMap([makeBuilderLayer({ dataset_record_type: 'vector_dataset' })]), bookmarks } as MapResponse;
}

describe('Builder bookmarks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetThumbnailDebounceForTests();
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
  });

  it('loads the saved list and reads clean until it changes', () => {
    const { result } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    expect(result.current.bookmarks).toEqual([a]);
    expect(result.current.hasUnsavedChanges).toBe(false);

    act(() => result.current.handleBookmarksChange([a, b]));
    expect(result.current.hasUnsavedChanges).toBe(true);
    expect(result.current.bookmarksEdited).toBe(true);
  });

  it('reads clean again when the saved list is put back', async () => {
    const { result } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([a, b]));
    act(() => result.current.handleBookmarksChange([{ ...a }]));
    await waitFor(() => expect(result.current.hasUnsavedChanges).toBe(false));
    expect(result.current.bookmarksEdited).toBe(false);
  });

  it('sends the list with a save, and leaves it out when unchanged', async () => {
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handlePaintChange(result.current.localLayers[0].id, { 'fill-color': '#123456' }));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data).not.toHaveProperty('bookmarks');

    act(() => result.current.handleBookmarksChange([b, a]));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[1][0].data.bookmarks).toEqual([b, a]);

    // The refetch returns what was saved, so the edit is spent.
    rerender({ mapData: mapWith([b, a]) });
    expect(result.current.bookmarksEdited).toBe(false);
    expect(result.current.bookmarks).toEqual([b, a]);
  });

  it('takes a saved list for its own edit though the server answers unset rotation and tilt as null', async () => {
    const asStored = (list: MapBookmark[]) => list.map((item) => ({ bearing: null, pitch: null, ...item }));
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([]) } });
    act(() => result.current.handleBookmarksChange([a]));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    rerender({ mapData: mapWith(asStored([a])) });
    expect(result.current.bookmarksEdited).toBe(false);

    // Another editor's bookmark shows, and a later save doesn't send the old list over it.
    rerender({ mapData: mapWith(asStored([a, b])) });
    expect(result.current.bookmarks.map((item) => item.name)).toEqual(['A', 'B']);
    act(() => result.current.handlePaintChange(result.current.localLayers[0].id, { 'fill-color': '#654321' }));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.lastCall![0].data).not.toHaveProperty('bookmarks');
  });

  it('drops an edit that was put back, so a later change from elsewhere shows', () => {
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([{ ...a, name: 'Renamed' }]));
    act(() => result.current.handleBookmarksChange([{ ...a }]));
    rerender({ mapData: mapWith([a, b]) });
    expect(result.current.bookmarks).toEqual([a, b]);
    expect(result.current.bookmarksEdited).toBe(false);
  });

  it('drops an unsaved edit when the builder shows another map', () => {
    const { result, rerender } = renderHook(({ mapData, mapId }) => useCombinedBuilder(mapData, mapId), {
      initialProps: { mapData: mapWith([a]), mapId: 'map-1' },
    });
    act(() => result.current.handleBookmarksChange([a, b]));
    rerender({ mapData: { ...mapWith([]), id: 'map-2' } as MapResponse, mapId: 'map-2' });
    expect(result.current.bookmarks).toEqual([]);
    rerender({ mapData: mapWith([a]), mapId: 'map-1' });
    expect(result.current.bookmarks).toEqual([a]);
    expect(result.current.bookmarksEdited).toBe(false);
  });

  it('keeps a bookmark deleted while the save that adds it is still going', async () => {
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([a, b]));
    let finish: (value: unknown) => void = () => {};
    mockUpdateMapMutateAsync.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    let saving: Promise<unknown> = Promise.resolve();
    act(() => {
      saving = result.current.handleSave();
    });
    await waitFor(() => expect(mockUpdateMapMutateAsync).toHaveBeenCalledOnce());

    // Back to the list as it was before the save, which is not what the save stores.
    act(() => result.current.handleBookmarksChange([a]));
    expect(result.current.bookmarksEdited).toBe(true);
    await act(async () => {
      finish({ id: 'map-1' });
      await saving;
    });
    rerender({ mapData: mapWith([a, b]) });
    expect(result.current.bookmarks).toEqual([a]);
    expect(result.current.bookmarksEdited).toBe(true);
    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('keeps an edit that matches a list saved elsewhere while its own save is still going', async () => {
    const c: MapBookmark = { name: 'C', extent: [4, 4, 5, 5] };
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([a, b]));
    let finish: (value: unknown) => void = () => {};
    mockUpdateMapMutateAsync.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    let saving: Promise<unknown> = Promise.resolve();
    act(() => {
      saving = result.current.handleSave();
    });
    await waitFor(() => expect(mockUpdateMapMutateAsync).toHaveBeenCalledOnce());
    act(() => result.current.handleBookmarksChange([a, c]));

    // Someone else's save of the same list arrives before this save is answered.
    rerender({ mapData: mapWith([a, c]) });
    expect(result.current.bookmarksEdited).toBe(true);

    await act(async () => {
      finish({ id: 'map-1' });
      await saving;
    });
    rerender({ mapData: mapWith([a, b]) });
    expect(result.current.bookmarks).toEqual([a, c]);
    expect(result.current.bookmarksEdited).toBe(true);
  });

  it('shows what the saved list holds after its save, another editor\'s addition included', async () => {
    const c: MapBookmark = { name: 'C', extent: [4, 4, 5, 5] };
    const { result, rerender } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([a, b]));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    // Saved, and shown as saved until the list comes back.
    expect(result.current.bookmarks).toEqual([a, b]);
    expect(result.current.bookmarksEdited).toBe(false);

    rerender({ mapData: mapWith([a, b, c]) });
    expect(result.current.bookmarks).toEqual([a, b, c]);
    expect(result.current.bookmarksEdited).toBe(false);
  });

  it('measures edits against the saved list again after a save fails', async () => {
    const { result } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([a, b]));
    mockUpdateMapMutateAsync.mockRejectedValueOnce(new Error('offline'));
    await act(async () => {
      await result.current.handleSave();
    });
    expect(result.current.bookmarksEdited).toBe(true);
    act(() => result.current.handleBookmarksChange([a]));
    expect(result.current.bookmarksEdited).toBe(false);
  });

  it('sends an emptied list so the server clears it', async () => {
    const { result } = renderHook(({ mapData }) => useCombinedBuilder(mapData), { initialProps: { mapData: mapWith([a]) } });
    act(() => result.current.handleBookmarksChange([]));
    mockUpdateMapMutateAsync.mockResolvedValueOnce({ id: 'map-1' });
    await act(async () => {
      await result.current.handleSave();
    });
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.bookmarks).toEqual([]);
  });
});
