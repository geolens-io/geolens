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
    bookmarks: layers.bookmarks,
    bookmarksEdited: layers.bookmarksEdited,
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
