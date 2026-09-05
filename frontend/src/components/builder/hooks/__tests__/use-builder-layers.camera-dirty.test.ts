/**
 * fix(#1854): every save rewrote center/zoom/bearing/pitch from the live map,
 * but nothing in the builder's clean check looked at the camera. A pan or zoom
 * therefore left `hasUnsavedChanges` false, so there was no navigation
 * blocker, no beforeunload, and the new view was lost on navigate-away, while
 * any unrelated save silently replaced the stored home view.
 *
 * These tests drive the real hooks (useBuilderLayers + useBuilderSave wired the
 * way MapBuilderPage wires them) through a map mock that emits `moveend`, so
 * they exercise the actual signal rather than the wiring.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useRef } from 'react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  useBuilderSave,
  __resetThumbnailDebounceForTests,
  type SaveBaselineSync,
} from '@/components/builder/hooks/use-builder-save';
import {
  makeBuilderLayer,
  makeBuilderMap,
  makeMapLibreMock,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

/* ── Mocks (mirrors use-builder-layers-save-integration.test.ts) ───────── */

const mockUpdateMapMutateAsync = vi.fn();
const mockPatchMapLayersMutateAsync = vi.fn();
const mockDuplicateMapMutateAsync = vi.fn();

vi.mock('@/hooks/use-maps', () => ({
  useUpdateMap: () => ({ mutateAsync: mockUpdateMapMutateAsync, isPending: false }),
  usePatchMapLayers: () => ({ mutateAsync: mockPatchMapLayersMutateAsync, isPending: false }),
  useDuplicateMap: () => ({ mutateAsync: mockDuplicateMapMutateAsync, isPending: false }),
  useAddLayer: () => ({ mutate: vi.fn() }),
  useRemoveLayer: () => ({ mutate: vi.fn() }),
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
  bulkDeleteLayersApi: vi.fn(),
  getMap: vi.fn(),
  uploadThumbnail: vi.fn(() => Promise.resolve()),
  uploadOgImage: vi.fn(() => Promise.resolve()),
}));

// useUnsavedGuard's useBlocker needs a Data Router; the shared renderHook
// wrapper provides MemoryRouter, so stub it as the sibling suites do.
const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useBlocker: () => mockBlocker };
});

/* ── A map mock whose camera moves and whose `moveend` actually fires ──── */

interface Camera {
  lng: number;
  lat: number;
  zoom: number;
  bearing?: number;
  pitch?: number;
}

function makeMovableMap(initial: Camera) {
  const handlers = new Map<string, Set<() => void>>();
  const camera = { bearing: 0, pitch: 0, ...initial };

  const map = {
    ...makeMapLibreMock(),
    getCenter: () => ({ lng: camera.lng, lat: camera.lat }),
    getZoom: () => camera.zoom,
    getBearing: () => camera.bearing,
    getPitch: () => camera.pitch,
    on: (event: string, handler: () => void) => {
      if (!handlers.has(event)) handlers.set(event, new Set());
      handlers.get(event)!.add(handler);
    },
    off: (event: string, handler: () => void) => {
      handlers.get(event)?.delete(handler);
    },
  } as unknown as MaplibreMap;

  /** Move the camera and settle, exactly as a drag-pan or wheel-zoom does. */
  function moveTo(next: Partial<Camera>) {
    Object.assign(camera, next);
    act(() => {
      handlers.get('moveend')?.forEach((handler) => handler());
    });
  }

  return { map, moveTo, camera };
}

/* ── Harness: the two hooks wired as MapBuilderPage wires them ─────────── */

function useCombinedBuilder(mapData: MapResponse, map: MaplibreMap) {
  const mapInstanceRef = useRef<MaplibreMap | null>(map);
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });

  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    mapData.id,
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3],
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4],
    saveBaselineSyncRef,
    map,
  );

  const save = useBuilderSave({
    mapId: mapData.id,
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
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasThumbnail: true,
    saveBaselineSyncRef,
  });

  return { ...layers, ...save };
}

const SAVED: Camera = { lng: -73.9, lat: 40.7, zoom: 10, bearing: 0, pitch: 0 };

function savedMap(overrides: Partial<MapResponse> = {}, camera: Camera = SAVED): MapResponse {
  return {
    ...makeBuilderMap([makeBuilderLayer({ id: 'layer-1' })]),
    center_lng: camera.lng,
    center_lat: camera.lat,
    zoom: camera.zoom,
    bearing: camera.bearing ?? 0,
    pitch: camera.pitch ?? 0,
    ...overrides,
  } as MapResponse;
}

function render(initialMapData: MapResponse, startCamera: Camera = SAVED) {
  const { map, moveTo } = makeMovableMap(startCamera);
  let mapData = initialMapData;
  const hook = renderHook(() => useCombinedBuilder(mapData, map));
  /** Stands in for the map-detail refetch a save invalidates. */
  function setMapData(next: MapResponse) {
    mapData = next;
    act(() => { hook.rerender(); });
  }
  return { hook, moveTo, setMapData };
}

beforeEach(() => {
  vi.clearAllMocks();
  __resetThumbnailDebounceForTests();
  mockUpdateMapMutateAsync.mockResolvedValue({});
  mockPatchMapLayersMutateAsync.mockResolvedValue({});
});

describe('fix(#1854): an unsaved camera move is unsaved work', () => {
  it('marks the map dirty when the camera pans away from the saved view', () => {
    const { hook, moveTo } = render(savedMap());
    expect(hook.result.current.hasUnsavedChanges).toBe(false);

    moveTo({ lng: -71.1, lat: 42.4 });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });

  it('marks the map dirty on a zoom, a rotation and a tilt too', () => {
    for (const move of [{ zoom: 14 }, { bearing: 45 }, { pitch: 30 }]) {
      const { hook, moveTo } = render(savedMap());
      moveTo(move);
      expect(hook.result.current.hasUnsavedChanges).toBe(true);
    }
  });

  it('clears the flag when the camera returns to the saved view', () => {
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    expect(hook.result.current.hasUnsavedChanges).toBe(true);

    moveTo({ lng: SAVED.lng, lat: SAVED.lat, zoom: SAVED.zoom });
    expect(hook.result.current.hasUnsavedChanges).toBe(false);
  });

  it('stays clean after a pan on a map that has no saved view', () => {
    // A map with null center components opens at the world default, which no
    // save-time camera would match; comparing there makes every new map dirty
    // before the user has touched anything.
    const { hook, moveTo } = render(savedMap({ center_lng: null, center_lat: null, zoom: null }));

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });

    expect(hook.result.current.hasUnsavedChanges).toBe(false);
  });

  it('keeps the flag when a layer revert leaves the camera panned', () => {
    // requestCleanRecheck is the banner Revert path; it must not report clean
    // while the stored view is still out of date.
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4 });
    act(() => { hook.result.current.requestCleanRecheck(); });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });

  it('arms beforeunload for an unsaved camera move', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const { hook, moveTo } = render(savedMap());
    expect(addSpy.mock.calls.filter(([event]) => event === 'beforeunload')).toHaveLength(0);

    moveTo({ lng: -71.1, lat: 42.4 });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
    addSpy.mockRestore();
  });
});

describe('fix(#1854): the dirty check mirrors the persisted precision', () => {
  // The save payload and the clean check share ONE normalizer
  // (builder-camera.ts), so the comparison grid IS the persisted grid: noise
  // finer than the stored value cannot dirty, and anything the store would
  // keep does.
  it.each([
    ['noise below the persisted precision', 1e-9, false],
    ['a change the stored value would keep', 1e-4, true],
  ])('%s reports %s', (_name, delta, expectDirty) => {
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: SAVED.lng + (delta as number), lat: SAVED.lat + (delta as number) });

    expect(hook.result.current.hasUnsavedChanges).toBe(expectDirty);
  });

  it('persists exactly the camera the dirty check compared', async () => {
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.123456789, lat: 42.987654321, zoom: 12.3456789 });
    await act(async () => { await hook.result.current.handleSave(); });

    const payload = mockUpdateMapMutateAsync.mock.calls[0][0].data;
    expect(payload.center_lng).toBe(-71.123457);
    expect(payload.center_lat).toBe(42.987654);
    expect(payload.zoom).toBe(12.345679);
  });

  it('keeps the flag when the camera moves during an in-flight save', async () => {
    // editedDuringSave compares SAVE_SNAPSHOT_FIELDS and the plugin set, and
    // the camera is in neither: it is read off the map. Without it in the
    // comparison the save clears the flag for a view it never persisted, and a
    // refetch that fails leaves the map falsely clean.
    let release!: () => void;
    mockUpdateMapMutateAsync.mockImplementation(
      () => new Promise<void>((resolve) => { release = () => resolve(); }),
    );
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    let saving!: Promise<void>;
    await act(async () => {
      saving = hook.result.current.handleSave();
      await Promise.resolve();
    });

    moveTo({ lng: -70.2, lat: 43.6 });
    await act(async () => { release(); await saving; });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });

  it('clears the flag on save and re-dirties on the next pan', async () => {
    const { hook, moveTo, setMapData } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    expect(hook.result.current.hasUnsavedChanges).toBe(true);

    await act(async () => { await hook.result.current.handleSave(); });
    expect(hook.result.current.hasUnsavedChanges).toBe(false);

    // The save invalidates the map-detail query; the refetch brings back the
    // view that was just stored.
    setMapData(savedMap({}, { lng: -71.1, lat: 42.4, zoom: 14 }));
    expect(hook.result.current.hasUnsavedChanges).toBe(false);

    moveTo({ lng: -70.2, lat: 43.6 });
    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });
});

describe('fix(#1854): a camera sample belongs to the map it was taken on', () => {
  // A direct /maps/:id navigation keeps this hook and the MapGL instance
  // mounted, and nothing repositions the instance, so the previous map's view
  // is still on screen. It is nobody's edit on the map now being shown.
  const OTHER: Camera = { lng: 5.5, lat: 10.25, zoom: 6 };
  const otherMap = () => savedMap({ id: 'map-2' }, OTHER);

  it('goes clean when the map identity changes under a panned camera', () => {
    const { hook, moveTo, setMapData } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    expect(hook.result.current.hasUnsavedChanges).toBe(true);

    setMapData(otherMap());

    expect(hook.result.current.hasUnsavedChanges).toBe(false);
  });

  it('stays clean when the leftover view merely settles on the new map', () => {
    // maplibre's resize() fires movestart/move/moveend with no camera change,
    // so the switched-to map does get a sample of the previous map's position.
    const { hook, moveTo, setMapData } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    setMapData(otherMap());
    moveTo({});

    expect(hook.result.current.hasUnsavedChanges).toBe(false);
  });

  it('still dirties on a real pan made after the switch', () => {
    const { hook, moveTo, setMapData } = render(savedMap());

    setMapData(otherMap());
    moveTo({ lng: 12.5, lat: 41.9, zoom: 9 });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });
});
