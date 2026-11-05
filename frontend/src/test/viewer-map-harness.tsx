// A ViewerMap test harness: a fake MapLibre map and the hooks and modules
// ViewerMap reads. Import it before ViewerMap, since it registers the mocks.
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';

type FakeMap = {
  isStyleLoaded: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getPaintProperty: ReturnType<typeof vi.fn>;
  getLayoutProperty: ReturnType<typeof vi.fn>;
  getFilter: ReturnType<typeof vi.fn>;
  addImage: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  moveLayer: ReturnType<typeof vi.fn>;
  removeSource: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  setMissingStyleImageResolver: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  setFilter: ReturnType<typeof vi.fn>;
  addLayer: ReturnType<typeof vi.fn>;
  addSource: ReturnType<typeof vi.fn>;
  removeLayer: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  setLayerZoomRange: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

type TestToken =
  | { kind: 'vector'; token: string }
  | { kind: 'raster'; tile_url: string };

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const sources = new Map<string, { type: string }>();
  const layout = new Map<string, unknown>();
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  const fakeMap: FakeMap = {
    // Default: style NOT loaded — forces the idle-retry path.
    isStyleLoaded: vi.fn(() => false),
    on: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      handlers.get(event)?.delete(handler);
    }),
    once: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    setTransformRequest: vi.fn(),
    // Return truthy for every layer id so adapter.syncVisibility actually
    // dispatches setLayoutProperty when the diff applies.
    getLayer: vi.fn(() => ({ id: 'x' })),
    getPaintProperty: vi.fn(() => undefined),
    getLayoutProperty: vi.fn((layerId: string, property: string) => layout.get(`${layerId}\0${property}`)),
    getFilter: vi.fn(() => undefined),
    addImage: vi.fn(),
    getSource: vi.fn((sourceId: string) => sources.get(sourceId) ?? null),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    moveLayer: vi.fn(),
    removeSource: vi.fn(),
    setTerrain: vi.fn(),
    setMissingStyleImageResolver: vi.fn(),
    setLayoutProperty: vi.fn((layerId: string, property: string, value: unknown) => {
      layout.set(`${layerId}\0${property}`, value);
    }),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn((sourceId: string, spec: { type: string }) => {
      sources.set(sourceId, { type: spec.type });
    }),
    removeLayer: vi.fn(),
    triggerRepaint: vi.fn(),
    setLayerZoomRange: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };
  return {
    fakeMap,
    handlers,
    reset: () => {
      handlers.clear();
      sources.clear();
      layout.clear();
      Object.values(fakeMap).forEach((v) => {
        if (typeof v === 'function' && 'mockClear' in v) (v as ReturnType<typeof vi.fn>).mockClear();
      });
      fakeMap.isStyleLoaded.mockReturnValue(false);
      fakeMap.getLayer.mockReturnValue({ id: 'x' });
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: FakeMap }) => void }) => {
      React.useEffect(() => { onLoad?.({ target: mapState.fakeMap }); }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
    FullscreenControl: () => null,
    AttributionControl: () => null,
    TerrainControl: () => null,
    Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  };
});

const tileConfigState = vi.hoisted(() => ({
  data: {
    cdn_base_url: null,
    mvt_source_layer_prefix: 'data',
  } as {
    cdn_base_url: string | null;
    mvt_source_layer_prefix: string | null;
  } | null,
}));

const tokenState = vi.hoisted(() => ({
  data: new Map<string, TestToken>([['dataset-pt', { kind: 'vector', token: 't' }]]),
}));

const terrainState = vi.hoisted(() => ({
  ready: false,
  expected: false,
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: tileConfigState.data }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  // Provide a token so the main sync effect's token gate doesn't short-circuit.
  useViewerTokens: () => ({ tokenMap: tokenState.data }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: terrainState.ready, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => terrainState.expected,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return { ...actual, applyBasemapConfigToMap: vi.fn(), syncLayersToMap: vi.fn() };
});
vi.mock('@/components/builder/map-composition-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-composition-sync')>();
  return {
    ...actual,
    syncMapComposition: vi.fn(({ map, layers, managedSourcesRef }) => {
      if (layers.length === 0) return;
      if (layers.every((layer: { is_dem?: boolean; style_config?: { render_mode?: string } | null }) => (
        layer.is_dem === true && layer.style_config?.render_mode === 'terrain'
      ))) return;
      const sourceId = 'viewer-source-points';
      if (!map.getSource(sourceId)) map.addSource(sourceId, { type: 'vector' });
      managedSourcesRef.current = new Set([sourceId]);
    }),
  };
});
vi.mock('@/lib/builder/basemap-style-mutation', () => ({ applySublayerOverrides: vi.fn() }));

export const LAYER: SharedLayerResponse = {
  id: 'pt-layer',
  dataset_id: 'dataset-pt',
  dataset_name: 'Points',
  display_name: 'Points',
  table_name: 'points',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  show_in_legend: true,
  opacity: 1,
  paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
};


/** The hoisted state the mocks read, which a module cannot export directly. */
export const viewerHarness = { mapState, tileConfigState, tokenState, terrainState };
