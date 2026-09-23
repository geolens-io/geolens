// ViewerMap used to also run its own token-refresh effect, which looked up
// `viewer-source-<key>` — never matching the deduped `viewer-source-data-
// <table>` sources non-cluster vector layers share. It only ever found
// per-layer server-cluster sources, and re-signed those a second time on top
// of the reactive sync pass (which resigns both source kinds already). These
// tests exercise the real map-sync pipeline (no mocking of syncLayersToMap /
// syncMapComposition) so a token rotation's resign count is the real one.
import type { ReactNode } from 'react';
import { render, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import type { SharedLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

// buildSignedTileUrl/buildClusterTileUrl embed the token's `sig` so a rotated
// token (new sig) produces a URL the refresh guard treats as changed — the
// same signal production tile-utils encodes into the real signed URL.
vi.mock('@/lib/tile-utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/tile-utils')>();
  return {
    ...actual,
    buildSignedTileUrl: vi.fn(
      (table: string, token: { sig?: string } | null) => `/tiles/${table}/{z}/{x}/{y}.pbf?sig=${token?.sig ?? 'none'}`,
    ),
    buildClusterTileUrl: vi.fn(
      (table: string, token: { sig?: string } | null) => `/tiles/clusters/${table}/{z}/{x}/{y}.pbf?sig=${token?.sig ?? 'none'}`,
    ),
  };
});

type SourceRecord = { type: string; setTiles?: ReturnType<typeof vi.fn> };

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const sources = new Map<string, SourceRecord>();
  const layerIds = new Set<string>();
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  const fakeMap = {
    isStyleLoaded: vi.fn(() => true),
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
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: Array.from(layerIds).map((id) => ({ id })) })),
    queryRenderedFeatures: vi.fn(() => []),
    setMissingStyleImageResolver: vi.fn(),
    setTerrain: vi.fn(),
    triggerRepaint: vi.fn(),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
    // Vector sources get a real setTiles spy, mirroring MapLibre, so the
    // resync path under test (refreshVectorSourceTiles) has something to call.
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string }) => {
      sources.set(id, spec.type === 'vector' ? { type: spec.type, setTiles: vi.fn() } : { type: spec.type });
    }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    addLayer: vi.fn((layer: { id: string }) => { layerIds.add(layer.id); }),
    getLayer: vi.fn((id: string) => (layerIds.has(id) ? { id } : null)),
    removeLayer: vi.fn((id: string) => { layerIds.delete(id); }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    setFilter: vi.fn(),
    getFilter: vi.fn(() => null),
    refreshTiles: vi.fn(),
    hasImage: vi.fn(() => false),
    addImage: vi.fn(),
    removeImage: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };
  return {
    fakeMap,
    sources,
    reset: () => {
      handlers.clear();
      sources.clear();
      layerIds.clear();
      Object.values(fakeMap).forEach((v) => {
        if (typeof v === 'function' && 'mockClear' in v) (v as ReturnType<typeof vi.fn>).mockClear();
      });
      fakeMap.isStyleLoaded.mockReturnValue(true);
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: typeof mapState.fakeMap }) => void }) => {
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
  data: { cdn_base_url: null as string | null, mvt_source_layer_prefix: 'data' as string | null },
}));

const tokenState = vi.hoisted(() => ({ data: new Map<string, TileToken>() }));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: tileConfigState.data }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({ tokenMap: tokenState.data, refreshTokens: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => false,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/lib/builder/basemap-style-mutation', () => ({ applySublayerOverrides: vi.fn() }));

function makeVectorToken(sig: string): TileToken {
  return { kind: 'vector', sig, exp: 9999999999, scope: 'test', expires_in: 3600 };
}

// Non-cluster vector layer: dedupes onto viewer-source-data-parcels.
const PARCELS_LAYER: SharedLayerResponse = {
  id: 'parcels-layer',
  dataset_id: 'dataset-parcels',
  dataset_name: 'Parcels',
  display_name: 'Parcels',
  table_name: 'parcels',
  geometry_type: 'MultiPolygon',
  column_info: null,
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: { 'fill-color': '#2255aa' },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
};

// Server-cluster point layer (feature_count over the bounded-geojson limit):
// stays per-layer at viewer-source-sensors-layer.
const SENSORS_LAYER: SharedLayerResponse = {
  id: 'sensors-layer',
  dataset_id: 'dataset-sensors',
  dataset_name: 'Sensors',
  display_name: 'Sensors',
  table_name: 'sensors',
  geometry_type: 'Point',
  column_info: null,
  sort_order: 1,
  visible: true,
  opacity: 1,
  paint: { 'circle-color': '#aa5522', 'circle-radius': 6 },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: { render_mode: 'cluster' },
  tile_url: '',
  feature_count: 6000,
};

// Stable across both renders below — only tokenState.data (tokenMap's
// identity) changes between them. A fresh `layers`/`visibleLayers` literal on
// the rerender would itself be a new reference and retrigger the sync effect
// regardless of tokenMap, defeating the point of rotating only the token.
const LAYERS = [PARCELS_LAYER, SENSORS_LAYER];
const VISIBLE_LAYERS = new Set(['parcels-layer', 'sensors-layer']);
const INITIAL_VIEW_STATE = { center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 };

function viewerElement() {
  return (
    <ViewerMap
      layers={LAYERS}
      basemapStyle="openfreemap-positron"
      basemapConfig={null}
      showBasemapLabels={true}
      terrainConfig={null}
      initialViewState={INITIAL_VIEW_STATE}
      visibleLayers={VISIBLE_LAYERS}
    />
  );
}

/** Find the one vector source whose id contains `needle`, once both are created. */
async function findVectorSource(needle: string) {
  await waitFor(() => {
    const match = [...mapState.sources.entries()].find(([id]) => id.includes(needle));
    expect(match?.[1].setTiles).toBeTruthy();
  });
  const [, source] = [...mapState.sources.entries()].find(([id]) => id.includes(needle))!;
  return source;
}

describe('ViewerMap token rotation resigns each vector source once', () => {
  beforeEach(() => {
    mapState.reset();
    tileConfigState.data = { cdn_base_url: null, mvt_source_layer_prefix: 'data' };
    tokenState.data = new Map([
      ['dataset-parcels', makeVectorToken('sig-1')],
      ['dataset-sensors', makeVectorToken('sig-1')],
    ]);
  });

  it('re-signs the deduped viewer-source-data-<table> source exactly once', async () => {
    const { rerender } = render(viewerElement());
    const parcels = await findVectorSource('source-data-parcels');
    parcels.setTiles!.mockClear();

    tokenState.data = new Map([
      ['dataset-parcels', makeVectorToken('sig-2')],
      ['dataset-sensors', makeVectorToken('sig-2')],
    ]);
    rerender(viewerElement());

    await waitFor(() => expect(parcels.setTiles).toHaveBeenCalledTimes(1));
  });

  it('re-signs the server-cluster source exactly once (fails on origin/main: the deleted effect re-signs it a second time)', async () => {
    const { rerender } = render(viewerElement());
    const sensors = await findVectorSource('sensors-layer');
    sensors.setTiles!.mockClear();

    tokenState.data = new Map([
      ['dataset-parcels', makeVectorToken('sig-2')],
      ['dataset-sensors', makeVectorToken('sig-2')],
    ]);
    rerender(viewerElement());

    await waitFor(() => expect(sensors.setTiles).toHaveBeenCalled());
    expect(sensors.setTiles).toHaveBeenCalledTimes(1);
  });
});
