/**
 * Every save rewrites center/zoom/bearing/pitch from the live map, so a moved
 * camera is a pending change: it enables Save (`hasUnsavedChanges`). A camera
 * move alone doesn't ask before leaving (`hasUnsavedEdits` stays false); any
 * other edit still does.
 *
 * These tests drive the real hooks (useBuilderLayers + useBuilderSave wired the
 * way MapBuilderPage wires them) through a map mock that emits `moveend`, so
 * they exercise the actual signal rather than the wiring.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render as renderComponent, renderHook } from '@testing-library/react';
import { useEffect, useRef, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { createElement, type ReactNode } from 'react';
import { queryKeys } from '@/lib/query-keys';
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
type BlockerArgs = { currentLocation: { pathname: string }; nextLocation: { pathname: string } };
let blockerPredicate: ((args: BlockerArgs) => boolean) | null = null;
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useBlocker: (predicate: (args: BlockerArgs) => boolean) => {
      blockerPredicate = predicate;
      return mockBlocker;
    },
  };
});

/** Save state and both leave prompts: the in-app navigation blocker and beforeunload. */
function expectLeaveGuard(
  state: { hasUnsavedChanges: boolean; hasUnsavedEdits: boolean; saveStatus: string },
  { saveEnabled, asksBeforeLeaving }: { saveEnabled: boolean; asksBeforeLeaving: boolean },
) {
  const unload = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(unload);
  const blocked = !!blockerPredicate?.({
    currentLocation: { pathname: '/maps/map-1' },
    nextLocation: { pathname: '/maps' },
  });
  expect({
    saveEnabled: state.hasUnsavedChanges,
    saveStatus: state.saveStatus,
    edits: state.hasUnsavedEdits,
    blocked,
    beforeUnload: unload.defaultPrevented,
  }).toEqual({
    saveEnabled,
    saveStatus: saveEnabled ? 'unsaved' : 'saved',
    edits: asksBeforeLeaving,
    blocked: asksBeforeLeaving,
    beforeUnload: asksBeforeLeaving,
  });
}

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

  /** A programmatic jump: maplibre fires moveend synchronously for duration 0. */
  function jumpTo(next: Partial<Camera>) {
    Object.assign(camera, next);
    handlers.get('moveend')?.forEach((handler) => handler());
  }

  /** Move the camera and settle, exactly as a drag-pan or wheel-zoom does. */
  function moveTo(next: Partial<Camera>) {
    act(() => { jumpTo(next); });
  }

  return { map, moveTo, jumpTo, camera };
}

/* ── Harness: the two hooks wired as MapBuilderPage wires them ─────────── */

/**
 * MapBuilderPage reads mapData from the map-detail query, so the harness has to
 * as well: the save path publishes the camera it persisted into that cache, and
 * a plain prop would not see it. This is useQuery minus the fetching.
 */
function useCachedMap(client: QueryClient, mapId: string): MapResponse | undefined {
  const key = queryKeys.maps.detail(mapId);
  const [data, setData] = useState(() => client.getQueryData<MapResponse>(key));
  useEffect(() => {
    setData(client.getQueryData<MapResponse>(queryKeys.maps.detail(mapId)));
    return client.getQueryCache().subscribe(() => {
      setData(client.getQueryData<MapResponse>(queryKeys.maps.detail(mapId)));
    });
  }, [client, mapId]);
  return data;
}

function useCombinedBuilder(
  client: QueryClient,
  mapId: string,
  map: MaplibreMap | null,
) {
  const mapData = useCachedMap(client, mapId) as MapResponse;
  const mapInstanceRef = useRef<MaplibreMap | null>(map);
  mapInstanceRef.current = map;
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });

  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    mapId,
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3],
    { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4],
    saveBaselineSyncRef,
    map,
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
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(queryKeys.maps.detail(initialMapData.id), initialMapData);
  let mapId = initialMapData.id;

  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client },
      createElement(MemoryRouter, null, children),
    );
  }

  const hook = renderHook(() => useCombinedBuilder(client, mapId, map), { wrapper: Wrapper });

  /** In-app navigation to another map: this hook and the MapGL instance stay mounted. */
  function setMapData(next: MapResponse) {
    client.setQueryData(queryKeys.maps.detail(next.id), next);
    mapId = next.id;
    act(() => { hook.rerender(); });
  }
  return { hook, moveTo, setMapData, client };
}

beforeEach(() => {
  vi.clearAllMocks();
  blockerPredicate = null;
  __resetThumbnailDebounceForTests();
  mockUpdateMapMutateAsync.mockResolvedValue({});
  mockPatchMapLayersMutateAsync.mockResolvedValue({});
});

describe('an unsaved camera move is unsaved work', () => {
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

  // A map with null center components (new, or legacy) is still saved with a
  // camera, so movement on one is unsaved work like anywhere else. What keeps
  // it clean untouched is the entry camera, not the absence of a stored view.
  describe('a map with no stored view', () => {
    const WORLD: Camera = { lng: 0, lat: 20, zoom: 2 };
    const centerless = () => savedMap({ center_lng: null, center_lat: null, zoom: null }, WORLD);

    it('dirties when the camera moves after entry', () => {
      const { hook, moveTo } = render(centerless(), WORLD);

      moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });

      expect(hook.result.current.hasUnsavedChanges).toBe(true);
    });

    it('stays clean when only the entry view settles', () => {
      const { hook, moveTo } = render(centerless(), WORLD);

      moveTo({});

      expect(hook.result.current.hasUnsavedChanges).toBe(false);
    });
  });

  it('keeps the flag when a layer revert leaves the camera panned', () => {
    // requestCleanRecheck is the banner Revert path; it must not report clean
    // while the stored view is still out of date.
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4 });
    act(() => { hook.result.current.requestCleanRecheck(); });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });
});

describe('leaving with an unsaved camera', () => {
  it('enables Save but does not ask before leaving after a pan alone', () => {
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4 });

    expectLeaveGuard(hook.result.current, { saveEnabled: true, asksBeforeLeaving: false });
  });

  it('asks before leaving after a pan and a style change', () => {
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4 });
    act(() => { hook.result.current.handleOpacityChange('layer-1', 0.25); });

    expectLeaveGuard(hook.result.current, { saveEnabled: true, asksBeforeLeaving: true });
  });

  it('keeps asking when the camera returns to the saved view after an edit', () => {
    const { hook, moveTo } = render(savedMap());

    act(() => { hook.result.current.handleOpacityChange('layer-1', 0.25); });
    moveTo({ lng: -71.1, lat: 42.4 });
    moveTo({ lng: SAVED.lng, lat: SAVED.lat });

    expectLeaveGuard(hook.result.current, { saveEnabled: true, asksBeforeLeaving: true });
  });

  it('stops asking but keeps Save once a reverted edit leaves only the pan', () => {
    const { hook, moveTo } = render(savedMap());
    const savedName = hook.result.current.localName;

    act(() => {
      hook.result.current.setLocalName('Renamed');
      hook.result.current.markDirty();
    });
    moveTo({ lng: -71.1, lat: 42.4 });
    expectLeaveGuard(hook.result.current, { saveEnabled: true, asksBeforeLeaving: true });

    act(() => { hook.result.current.setLocalName(savedName); });
    act(() => { hook.result.current.requestCleanRecheck(); });

    expectLeaveGuard(hook.result.current, { saveEnabled: true, asksBeforeLeaving: false });
  });
});

describe('a map that fits its layers as it loads', () => {
  // MapBuilderPage keys BuilderMap by map id, so every map, the first one or
  // one reached by in-page navigation, gets a fresh instance. Its load event
  // makes BuilderMap ready and hands the page the instance in one render, and
  // BuilderMap (a child) fits a map with no saved view in an effect. The page's
  // entry-camera effect runs after the child's, so the fitted view is the entry
  // view and opening the map leaves it clean.
  const WORLD: Camera = { lng: 0, lat: 20, zoom: 2 };
  const FITTED: Camera = { lng: -73.95, lat: 40.75, zoom: 11.5 };
  const withoutView = (id: string) =>
    savedMap({ id, center_lng: null, center_lat: null, zoom: null }, WORLD);

  function renderBuilder(maps: MapResponse[]) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    for (const data of maps) client.setQueryData(queryKeys.maps.detail(data.id), data);
    const page = {} as {
      latest: ReturnType<typeof useCombinedBuilder>;
      show: (mapId: string) => void;
      load: () => void;
      moveTo: (next: Partial<Camera>) => void;
      camera: () => Camera;
    };

    /** Stands in for BuilderMap: a new map per mount, fitted on load when there is no saved view. */
    function FakeBuilderMap({ data, onMapRef }: { data: MapResponse; onMapRef: (map: MaplibreMap | null) => void }) {
      const hasView = data.center_lng != null && data.center_lat != null;
      const [movable] = useState(() =>
        makeMovableMap(hasView ? { lng: data.center_lng!, lat: data.center_lat!, zoom: data.zoom! } : WORLD),
      );
      const [ready, setReady] = useState(false);
      useEffect(() => {
        page.load = () => {
          setReady(true);
          onMapRef(movable.map);
        };
        page.moveTo = movable.moveTo;
        page.camera = () => ({ ...movable.camera });
      });
      useEffect(() => {
        if (ready && !hasView) movable.jumpTo(FITTED);
      }, [ready, hasView, movable]);
      useEffect(() => () => onMapRef(null), [onMapRef]);
      return null;
    }

    function Page() {
      const [mapId, setMapId] = useState(maps[0].id);
      const [instance, setInstance] = useState<MaplibreMap | null>(null);
      const state = useCombinedBuilder(client, mapId, instance);
      useEffect(() => { page.latest = state; });
      useEffect(() => {
        page.show = (next) => setMapId(next);
      }, []);
      const data = maps.find((m) => m.id === mapId)!;
      return createElement(FakeBuilderMap, { key: mapId, data, onMapRef: setInstance });
    }

    renderComponent(
      createElement(QueryClientProvider, { client }, createElement(MemoryRouter, null, createElement(Page))),
    );
    return page;
  }

  const expectClean = (page: ReturnType<typeof renderBuilder>) =>
    expectLeaveGuard(page.latest, { saveEnabled: false, asksBeforeLeaving: false });

  it('stays clean after the first fit', () => {
    const page = renderBuilder([withoutView('map-1')]);

    act(() => { page.load(); });
    // maplibre's resize() and tile settles fire moveend without moving.
    page.moveTo({});

    expect(page.camera()).toMatchObject(FITTED);
    expectClean(page);

    page.moveTo({ lng: -71.1, lat: 42.4 });
    expect(page.latest.hasUnsavedChanges).toBe(true);
  });

  it('fits and stays clean after in-page navigation from a map with a saved view', () => {
    const page = renderBuilder([savedMap(), withoutView('map-2')]);
    act(() => { page.load(); });
    page.moveTo({});
    expectClean(page);

    act(() => { page.show('map-2'); });
    act(() => { page.load(); });
    page.moveTo({});

    expect(page.latest.layersMapId).toBe('map-2');
    expect(page.camera()).toMatchObject(FITTED);
    expectClean(page);

    page.moveTo({ lng: -71.1, lat: 42.4 });
    expectLeaveGuard(page.latest, { saveEnabled: true, asksBeforeLeaving: false });
  });
});

describe('the dirty check mirrors the persisted precision', () => {
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

  it('stays dirty when the camera returns to the pre-save view', async () => {
    // useUpdateMap only invalidates the detail query, so mapData would keep the
    // pre-save camera until the refetch lands, and forever if it fails. Moving
    // back to that stale position must not read as clean.
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    await act(async () => { await hook.result.current.handleSave(); });
    expect(hook.result.current.hasUnsavedChanges).toBe(false);

    moveTo({ lng: SAVED.lng, lat: SAVED.lat, zoom: SAVED.zoom });

    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });

  it('clears the flag on save and re-dirties on the next pan', async () => {
    const { hook, moveTo } = render(savedMap());

    moveTo({ lng: -71.1, lat: 42.4, zoom: 14 });
    expect(hook.result.current.hasUnsavedChanges).toBe(true);

    await act(async () => { await hook.result.current.handleSave(); });
    expect(hook.result.current.hasUnsavedChanges).toBe(false);

    moveTo({ lng: -70.2, lat: 43.6 });
    expect(hook.result.current.hasUnsavedChanges).toBe(true);
  });
});

describe('a camera sample belongs to the map it was taken on', () => {
  // A direct /maps/:id navigation keeps this hook mounted. When one map
  // instance spans the switch, the previous map's view is still on screen, and
  // it is nobody's edit on the map now being shown.
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
