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
import { applyMapBasemapAppearance, syncMapComposition } from '../map-composition-sync';

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
    let stored: unknown = styleSky;
    const setSky = vi.fn((sky: unknown) => { stored = sky; });
    const getSky = vi.fn(() => stored);
    const target = {
      isStyleLoaded: vi.fn(() => true), setProjection: vi.fn(), setSky, getSky,
    } as unknown as MaplibreMap;
    const globe = { projection: 'globe' } as MapBasemapConfig;
    const atmosphere = ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0];

    applyMapBasemapAppearance({ map: target, basemapConfig: globe });
    expect(setSky).toHaveBeenLastCalledWith({ ...styleSky, 'atmosphere-blend': atmosphere });

    // Mercator hands the basemap its own sky back instead of clearing it.
    applyMapBasemapAppearance({ map: target, basemapConfig: null });
    expect(setSky).toHaveBeenLastCalledWith(styleSky);

    // A basemap swap brings a different sky; that one becomes what we preserve.
    stored = { 'sky-color': '#222222' };
    applyMapBasemapAppearance({ map: target, basemapConfig: globe });
    expect(setSky).toHaveBeenLastCalledWith({ 'sky-color': '#222222', 'atmosphere-blend': atmosphere });
    applyMapBasemapAppearance({ map: target, basemapConfig: null });
    expect(setSky).toHaveBeenLastCalledWith({ 'sky-color': '#222222' });
  });

  it('still resets after maplibre drops a no-op sky write (fix(#1474))', () => {
    // maplibre skips the assignment when the spec you pass changes nothing, so
    // what we believe is on the map has to be read back rather than assumed.
    let stored: Record<string, unknown> | undefined;
    const setSky = vi.fn((sky?: Record<string, unknown>) => {
      const unchanged = sky && stored
        && Object.keys(sky).every((k) => JSON.stringify(sky[k]) === JSON.stringify(stored?.[k]));
      if (!unchanged) stored = sky;
    });
    const target = {
      isStyleLoaded: vi.fn(() => true),
      setProjection: vi.fn(),
      setSky,
      getSky: vi.fn(() => stored),
    } as unknown as MaplibreMap;
    const globe = { projection: 'globe' } as MapBasemapConfig;

    applyMapBasemapAppearance({ map: target, basemapConfig: globe });
    applyMapBasemapAppearance({ map: target, basemapConfig: globe });
    applyMapBasemapAppearance({ map: target, basemapConfig: null });

    expect(setSky).toHaveBeenLastCalledWith(undefined);
    expect(stored).toBeUndefined();
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
