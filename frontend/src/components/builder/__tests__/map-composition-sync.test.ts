import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig } from '@/types/api';
import { applySublayerOverrides } from '@/lib/builder/basemap-style-mutation';
import {
  applyBasemapConfigToMap,
  reorderBasemapAboveData,
  reorderBasemapLabels,
  reorderDataLayers,
  syncLayersToMap,
  type SyncLayerInput,
} from '../map-sync';
import { applyMapBasemapAppearance, hasGlobeSpaceBackdrop, syncMapComposition } from '../map-composition-sync';

vi.mock('../map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../map-sync')>();
  return {
    ...actual,
    applyBasemapConfigToMap: vi.fn(),
    reorderBasemapAboveData: vi.fn(),
    reorderBasemapLabels: vi.fn(),
    reorderDataLayers: vi.fn(),
    syncLayersToMap: vi.fn(),
  };
});

vi.mock('@/lib/builder/basemap-style-mutation', () => ({
  applySublayerOverrides: vi.fn(),
}));

const syncLayersToMapMock = vi.mocked(syncLayersToMap);
const applyBasemapConfigToMapMock = vi.mocked(applyBasemapConfigToMap);
const applySublayerOverridesMock = vi.mocked(applySublayerOverrides);
const reorderBasemapLabelsMock = vi.mocked(reorderBasemapLabels);
const reorderDataLayersMock = vi.mocked(reorderDataLayers);
const reorderBasemapAboveDataMock = vi.mocked(reorderBasemapAboveData);

function map(styleLoaded = true) {
  return {
    isStyleLoaded: vi.fn(() => styleLoaded),
  } as unknown as MaplibreMap;
}

const ATMOSPHERE = ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0];

type Sky = Record<string, unknown> | undefined;

// Mirrors maplibre's Style.setSky closely enough to be worth testing against:
// the update check walks only the keys of the spec you hand it, and a write
// that changes none of them is dropped without touching the stored sky.
function skyMap(initialSky?: Sky) {
  let stored: Sky = initialSky;
  const setSky = vi.fn((sky: Sky) => {
    if (sky && stored) {
      const changed = Object.keys(sky).some(
        (key) => JSON.stringify(sky[key]) !== JSON.stringify(stored?.[key]),
      );
      if (!changed) return;
    }
    stored = sky;
  });
  return {
    map: {
      isStyleLoaded: vi.fn(() => true),
      setProjection: vi.fn(),
      setMissingStyleImageResolver: vi.fn(),
      setSky,
      getSky: vi.fn(() => stored),
    } as unknown as MaplibreMap,
    setSky,
    sky: () => stored,
    reload: (next: Sky) => { stored = next; },
  };
}

// A map holding a real container element, so the space backdrop can be read
// back the way the stylesheet selects it (feat(#1479)).
function containerMap() {
  const container = document.createElement('div');
  container.className = 'maplibregl-map';
  return {
    map: {
      isStyleLoaded: vi.fn(() => true),
      setProjection: vi.fn(),
      setMissingStyleImageResolver: vi.fn(),
      getContainer: vi.fn(() => container),
    } as unknown as MaplibreMap,
    container,
  };
}

function layer(id = 'layer-1'): SyncLayerInput {
  return {
    id,
    dataset_id: `dataset-${id}`,
    dataset_table_name: `table_${id}`,
    dataset_geometry_type: 'LINESTRING',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
  };
}

describe('map composition sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('syncs layers before applying basemap appearance and caller callbacks', () => {
    const callOrder: string[] = [];
    syncLayersToMapMock.mockImplementation(() => { callOrder.push('layers'); });
    reorderBasemapLabelsMock.mockImplementation(() => { callOrder.push('labels'); });
    applyBasemapConfigToMapMock.mockImplementation(() => { callOrder.push('basemap-config'); });
    applySublayerOverridesMock.mockImplementation(() => { callOrder.push('sublayer-overrides'); });
    reorderDataLayersMock.mockImplementation(() => { callOrder.push('data-restack'); });
    reorderBasemapAboveDataMock.mockImplementation(() => { callOrder.push('basemap-position'); });

    const basemapConfig: MapBasemapConfig = {
      label_mode: 'subtle',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      relief_contrast: null,
      basemap_position: 'top',
      sublayer_overrides: {
        road: { opacity: 0.5 },
      },
    };
    const layers = [layer('roads')];
    const tokenMap = new Map();
    const managedSourcesRef = { current: new Set<string>() };
    const orderKeyRef = { current: '' };

    syncMapComposition({
      map: map(),
      layers,
      tokenMap,
      tileBaseUrl: '/tiles',
      managedSourcesRef,
      orderKeyRef,
      syncOptions: { idPrefix: 'viewer-', showBasemapLabels: false },
      basemapConfig,
      showBasemapLabels: false,
      afterSync: () => { callOrder.push('after'); },
    });

    expect(syncLayersToMapMock).toHaveBeenCalledWith(
      expect.anything(),
      layers,
      tokenMap,
      '/tiles',
      managedSourcesRef,
      orderKeyRef,
      undefined,
      { idPrefix: 'viewer-', showBasemapLabels: false, basemapPosition: 'top' },
    );
    expect(applyBasemapConfigToMapMock).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig,
      false,
      'viewer-source-',
    );
    expect(applySublayerOverridesMock).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig.sublayer_overrides,
      'viewer-source-',
      1, // builder-audit #338 CORR-01: master opacity (config.opacity undefined → 1)
    );
    expect(reorderDataLayersMock).toHaveBeenCalledWith(expect.anything(), layers, 'viewer-');
    expect(callOrder).toEqual([
      'layers',
      'labels',
      'basemap-config',
      'sublayer-overrides',
      'data-restack',
      'basemap-position',
      'after',
    ]);
  });

  it('applies the saved projection with the basemap appearance (feat(#845))', () => {
    const setProjection = vi.fn();
    const target = { isStyleLoaded: vi.fn(() => true), setProjection } as unknown as MaplibreMap;

    applyMapBasemapAppearance({
      map: target,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
      idPrefix: 'viewer-',
    });
    expect(setProjection).toHaveBeenCalledWith({ type: 'globe' });

    // No saved projection → explicit mercator, so a globe→mercator edit resets.
    applyMapBasemapAppearance({ map: target, basemapConfig: null, idPrefix: 'viewer-' });
    expect(setProjection).toHaveBeenLastCalledWith({ type: 'mercator' });

    // setProjection is attempted even while isStyleLoaded() is false — it
    // only needs the style parsed, and gating on idle left a saved globe map
    // visibly in mercator during slow tile loads (Codex P2 round 2 on #848).
    setProjection.mockClear();
    applyMapBasemapAppearance({
      map: { isStyleLoaded: vi.fn(() => false), setProjection } as unknown as MaplibreMap,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(setProjection).toHaveBeenCalledWith({ type: 'globe' });
  });

  it('retries an unparsed-style projection on style.load and cancels stale retries (feat(#845))', () => {
    // A style that is not parsed yet makes setProjection throw.
    let styleParsed = false;
    const setProjection = vi.fn(() => {
      if (!styleParsed) throw new Error('Style is not done loading');
    });
    const once = vi.fn();
    const off = vi.fn();
    const loading = { isStyleLoaded: vi.fn(() => false), setProjection, once, off } as unknown as MaplibreMap;

    applyMapBasemapAppearance({
      map: loading,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(once).toHaveBeenCalledWith('style.load', expect.any(Function));
    const globeRetry = once.mock.calls[0][1] as () => void;

    // A newer application cancels the stale retry, so a projection change
    // during the load window can't be reverted (Codex P2 round 1 on #848).
    applyMapBasemapAppearance({
      map: loading,
      basemapConfig: { projection: 'mercator' } as MapBasemapConfig,
    });
    expect(off).toHaveBeenCalledWith('style.load', globeRetry);

    // Once the style parses, the latest retry applies the latest value.
    styleParsed = true;
    setProjection.mockClear();
    (once.mock.calls[1][1] as () => void)();
    expect(setProjection).toHaveBeenCalledTimes(1);
    expect(setProjection).toHaveBeenCalledWith({ type: 'mercator' });
  });

  it('applies the globe atmosphere with the projection and resets it on mercator (feat(#1473))', () => {
    const setProjection = vi.fn();
    const setSky = vi.fn();
    const target = { isStyleLoaded: vi.fn(() => true), setProjection, setSky } as unknown as MaplibreMap;

    applyMapBasemapAppearance({
      map: target,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
      idPrefix: 'viewer-',
    });
    expect(setSky).toHaveBeenCalledWith({
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0],
    });

    // Mercator resets with `undefined`, the branch maplibre reads as "no sky".
    // An empty object is a silent no-op there and would strand the globe sky.
    applyMapBasemapAppearance({ map: target, basemapConfig: null, idPrefix: 'viewer-' });
    expect(setSky).toHaveBeenLastCalledWith(undefined);

    // Sky is attempted on the same not-yet-idle path as the projection.
    setSky.mockClear();
    applyMapBasemapAppearance({
      map: { isStyleLoaded: vi.fn(() => false), setProjection, setSky } as unknown as MaplibreMap,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(setSky).toHaveBeenCalledWith(
      expect.objectContaining({ 'atmosphere-blend': expect.anything() }),
    );
  });

  it('layers the atmosphere over a style-provided sky and restores it (fix(#1474))', () => {
    const styleSky = { 'sky-color': '#0b1026', 'horizon-color': '#7ba0c0' };
    const target = skyMap(styleSky);
    const globe = { projection: 'globe' } as MapBasemapConfig;

    applyMapBasemapAppearance({ map: target.map, basemapConfig: globe });
    expect(target.setSky).toHaveBeenLastCalledWith({ ...styleSky, 'atmosphere-blend': ATMOSPHERE });

    // Mercator hands the basemap its own sky back instead of clearing it, and
    // names atmosphere-blend so maplibre cannot drop the write as a no-op. 0.8
    // is the spec default, which is what this style already evaluated it to.
    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });
    expect(target.setSky).toHaveBeenLastCalledWith({ ...styleSky, 'atmosphere-blend': 0.8 });
    expect(target.sky()).toEqual({ ...styleSky, 'atmosphere-blend': 0.8 });

    // A basemap swap brings a different sky; that one becomes what we preserve.
    target.reload({ 'sky-color': '#222222' });
    applyMapBasemapAppearance({ map: target.map, basemapConfig: globe });
    expect(target.setSky).toHaveBeenLastCalledWith({ 'sky-color': '#222222', 'atmosphere-blend': ATMOSPHERE });
    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });
    expect(target.sky()).toEqual({ 'sky-color': '#222222', 'atmosphere-blend': 0.8 });
  });

  it('restores a style-provided atmosphere-blend verbatim (fix(#1474))', () => {
    const styleSky = { 'sky-color': '#000000', 'atmosphere-blend': 0.3 };
    const target = skyMap(styleSky);

    applyMapBasemapAppearance({
      map: target.map,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(target.sky()).toEqual({ 'sky-color': '#000000', 'atmosphere-blend': ATMOSPHERE });

    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });
    expect(target.sky()).toEqual(styleSky);
  });

  it('still resets after maplibre drops a no-op sky write (fix(#1474))', () => {
    // maplibre skips the assignment when the spec changes nothing, so what we
    // believe is on the map has to be read back rather than assumed.
    const target = skyMap();
    const globe = { projection: 'globe' } as MapBasemapConfig;

    applyMapBasemapAppearance({ map: target.map, basemapConfig: globe });
    applyMapBasemapAppearance({ map: target.map, basemapConfig: globe });
    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });

    expect(target.setSky).toHaveBeenLastCalledWith(undefined);
    expect(target.sky()).toBeUndefined();
  });

  it('retries the globe sky on style.load with the projection (feat(#1473))', () => {
    // The projection throws first on an unparsed style, so the sky never runs
    // until the retry — proving it rides the same deferral.
    let styleParsed = false;
    const setProjection = vi.fn(() => {
      if (!styleParsed) throw new Error('Style is not done loading');
    });
    const setSky = vi.fn();
    const once = vi.fn();
    const off = vi.fn();
    const loading = {
      isStyleLoaded: vi.fn(() => false), setProjection, setSky, once, off,
    } as unknown as MaplibreMap;

    applyMapBasemapAppearance({
      map: loading,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(setSky).not.toHaveBeenCalled();

    styleParsed = true;
    (once.mock.calls[0][1] as () => void)();
    expect(setSky).toHaveBeenCalledWith(
      expect.objectContaining({ 'atmosphere-blend': expect.anything() }),
    );

    // A sky call that is itself the one to throw defers the same way.
    let skyParsed = false;
    const throwingSky = vi.fn(() => {
      if (!skyParsed) throw new Error('Style is not done loading');
    });
    const skyOnce = vi.fn();
    const skyLoading = {
      isStyleLoaded: vi.fn(() => false),
      setProjection: vi.fn(),
      setMissingStyleImageResolver: vi.fn(),
      setSky: throwingSky,
      once: skyOnce,
      off: vi.fn(),
    } as unknown as MaplibreMap;

    applyMapBasemapAppearance({
      map: skyLoading,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(skyOnce).toHaveBeenCalledWith('style.load', expect.any(Function));

    skyParsed = true;
    throwingSky.mockClear();
    (skyOnce.mock.calls[0][1] as () => void)();
    expect(throwingSky).toHaveBeenCalledWith(
      expect.objectContaining({ 'atmosphere-blend': expect.anything() }),
    );
  });

  it('marks the container for globe and unmarks it on mercator (feat(#1479))', () => {
    const target = containerMap();

    applyMapBasemapAppearance({
      map: target.map,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(target.container.getAttribute('data-globe-space')).toBe('true');

    // Both ways of saying mercator have to strip it: an explicit projection and
    // a config that never mentioned one.
    applyMapBasemapAppearance({
      map: target.map,
      basemapConfig: { projection: 'mercator' } as MapBasemapConfig,
    });
    expect(target.container.hasAttribute('data-globe-space')).toBe(false);

    applyMapBasemapAppearance({
      map: target.map,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });
    expect(target.container.hasAttribute('data-globe-space')).toBe(false);
  });

  it('leaves the marker off a container it never set (feat(#1479))', () => {
    // Reverting a map that was never a globe must not invent the attribute,
    // and removeAttribute on an absent attribute must stay silent.
    const target = containerMap();
    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });
    expect(target.container.hasAttribute('data-globe-space')).toBe(false);
  });

  it('keeps one surface\'s backdrop out of the other (feat(#1479))', () => {
    const builder = containerMap();
    const viewer = containerMap();

    applyMapBasemapAppearance({
      map: builder.map,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    applyMapBasemapAppearance({
      map: viewer.map,
      basemapConfig: null,
      idPrefix: 'viewer-',
    });

    expect(builder.container.getAttribute('data-globe-space')).toBe('true');
    expect(viewer.container.hasAttribute('data-globe-space')).toBe(false);

    // And the reverse, so neither surface is merely winning by ordering.
    applyMapBasemapAppearance({ map: builder.map, basemapConfig: null });
    applyMapBasemapAppearance({
      map: viewer.map,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
      idPrefix: 'viewer-',
    });
    expect(builder.container.hasAttribute('data-globe-space')).toBe(false);
    expect(viewer.container.getAttribute('data-globe-space')).toBe('true');
  });

  it('does not wait for a parsed style to update the backdrop (feat(#1479))', () => {
    // The backdrop is DOM, not style state. Riding the projection's retry
    // would strand it behind any setProjection throw — the whole style.load
    // window on the way in, and forever if the throw had another cause.
    const container = document.createElement('div');
    const unparsed = {
      isStyleLoaded: vi.fn(() => false),
      setProjection: vi.fn(() => { throw new Error('Style is not done loading'); }),
      getContainer: vi.fn(() => container),
      once: vi.fn(),
      off: vi.fn(),
    } as unknown as MaplibreMap;

    applyMapBasemapAppearance({
      map: unparsed,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(container.getAttribute('data-globe-space')).toBe('true');

    applyMapBasemapAppearance({ map: unparsed, basemapConfig: null });
    expect(container.hasAttribute('data-globe-space')).toBe(false);
  });

  it('reports the backdrop to capture paths through hasGlobeSpaceBackdrop (fix(#1479))', () => {
    // Image captures read this instead of re-deriving globeness, so it has to
    // track the marker exactly — including for a map that cannot be marked.
    const target = containerMap();
    expect(hasGlobeSpaceBackdrop(target.map)).toBe(false);

    applyMapBasemapAppearance({
      map: target.map,
      basemapConfig: { projection: 'globe' } as MapBasemapConfig,
    });
    expect(hasGlobeSpaceBackdrop(target.map)).toBe(true);

    applyMapBasemapAppearance({ map: target.map, basemapConfig: null });
    expect(hasGlobeSpaceBackdrop(target.map)).toBe(false);

    expect(hasGlobeSpaceBackdrop(map())).toBe(false);
  });

  it('tolerates a map with no container (feat(#1479))', () => {
    expect(() =>
      applyMapBasemapAppearance({
        map: map(),
        basemapConfig: { projection: 'globe' } as MapBasemapConfig,
      }),
    ).not.toThrow();
  });

  it('lets sublayer override retry logic handle unloaded styles', () => {
    const basemapConfig: MapBasemapConfig = {
      label_mode: 'full',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      relief_contrast: null,
      sublayer_overrides: {
        label: { opacity: 0.4 },
      },
    };

    applyMapBasemapAppearance({
      map: map(false),
      basemapConfig,
      idPrefix: 'viewer-',
    });

    expect(applySublayerOverridesMock).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig.sublayer_overrides,
      'viewer-source-',
      1, // builder-audit #338 CORR-01: master opacity (config.opacity undefined → 1)
    );
    expect(applyBasemapConfigToMapMock).not.toHaveBeenCalled();
    expect(reorderBasemapLabelsMock).not.toHaveBeenCalled();
    expect(reorderDataLayersMock).not.toHaveBeenCalled();
    expect(reorderBasemapAboveDataMock).not.toHaveBeenCalled();
  });
});
