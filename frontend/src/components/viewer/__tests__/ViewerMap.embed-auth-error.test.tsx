// B-006: the viewer's global map.on('error') handler swallowed
// every 4xx, so an expired/invalid embed token (X-Embed-Token) rendered blank
// layers with no user feedback. This spec proves an embed-token 401/403
// surfaces a deduped "access expired" toast, while a genuine no-data 404
// stays silent (regression guard).
import type { ReactNode } from 'react';
import { render, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import type { SharedLayerResponse } from '@/types/api';

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { toast } from 'sonner';

type FakeMap = {
  isStyleLoaded: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  moveLayer: ReturnType<typeof vi.fn>;
  removeSource: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  setFilter: ReturnType<typeof vi.fn>;
  addLayer: ReturnType<typeof vi.fn>;
  addSource: ReturnType<typeof vi.fn>;
  removeLayer: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  setLayerZoomRange: ReturnType<typeof vi.fn>;
  hasImage: ReturnType<typeof vi.fn>;
  addImage: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  const fakeMap: FakeMap = {
    // Style loaded so the initial sync effects run synchronously (no idle-retry needed here).
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
    getLayer: vi.fn(() => ({ id: 'x' })),
    getSource: vi.fn(() => null),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    moveLayer: vi.fn(),
    removeSource: vi.fn(),
    setTerrain: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn(),
    removeLayer: vi.fn(),
    triggerRepaint: vi.fn(),
    setLayerZoomRange: vi.fn(),
    hasImage: vi.fn(() => true),
    addImage: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };
  return {
    fakeMap,
    handlers,
    reset: () => {
      handlers.clear();
      Object.values(fakeMap).forEach((v) => {
        if (typeof v === 'function' && 'mockClear' in v) (v as ReturnType<typeof vi.fn>).mockClear();
      });
      fakeMap.isStyleLoaded.mockReturnValue(true);
      fakeMap.getLayer.mockReturnValue({ id: 'x' });
      fakeMap.hasImage.mockReturnValue(true);
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

// Mutable so WR-01b can simulate a deployment with a configured tile CDN
// (`cdn_base_url`) without re-declaring the whole mock per test.
const tileConfigState = vi.hoisted(() => ({ cdn_base_url: null as string | null }));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: tileConfigState }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  // Embed path doesn't depend on tokenMap, but keep it non-empty to mirror the sibling scaffold.
  useViewerTokens: () => ({ tokenMap: new Map([['dataset-pt', { kind: 'vector', token: 't' }]]) }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return { ...actual, applyBasemapConfigToMap: vi.fn(), syncLayersToMap: vi.fn() };
});
vi.mock('@/lib/builder/basemap-style-mutation', () => ({ applySublayerOverrides: vi.fn() }));

const LAYER: SharedLayerResponse = {
  id: 'pt-layer',
  dataset_id: 'dataset-pt',
  dataset_name: 'Points',
  display_name: 'Points',
  table_name: 'points',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
};

function renderEmbedViewer() {
  return render(
    <ViewerMap
      layers={[LAYER]}
      basemapStyle="openfreemap-positron"
      basemapConfig={null}
      showBasemapLabels={true}
      terrainConfig={null}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={new Set(['pt-layer'])}
      embedToken="embed-tok-123"
    />,
  );
}

describe('ViewerMap embed-token auth error (B-006)', () => {
  beforeEach(() => {
    mapState.reset();
    tileConfigState.cdn_base_url = null;
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
  });

  it('surfaces a deduped toast when an embed tile request returns 401', async () => {
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', { error: { status: 401 } });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: expect.any(String) }),
    );
  });

  it('surfaces a deduped toast when an embed tile request returns 403', async () => {
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', { error: { status: 403 } });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: expect.any(String) }),
    );
  });

  it('stays quiet on a no-data 404 (regression guard)', async () => {
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', { error: { status: 404 } });

    expect(toast.error).not.toHaveBeenCalled();
  });

  // WR-01: transformRequest attaches X-Embed-Token to every request the map
  // makes, including third-party basemap CDN fetches — a 401/403 from one of
  // those hosts is not an embed-token problem and must not misfire the toast.
  it('stays quiet on a 401 from a third-party basemap CDN host', async () => {
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', {
      error: { status: 401, url: 'https://tiles.openfreemap.org/styles/positron/sprite.json' },
    });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it('surfaces the toast on a 401 from the first-party tile/api URL', async () => {
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', {
      error: { status: 401, url: `${window.location.origin}/api/tiles/collection.mvt` },
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: expect.any(String) }),
    );
  });

  // WR-01a: a protocol-relative URL (`//host/path`) starts with `/` but is
  // NOT a same-origin relative path — it must still be origin-checked rather
  // than short-circuited to first-party.
  it('stays quiet on a 401 from a protocol-relative third-party CDN URL', async () => {
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', {
      error: { status: 401, url: '//tiles.openfreemap.org/styles/positron/sprite.json' },
    });

    expect(toast.error).not.toHaveBeenCalled();
  });

  // WR-01b: when the deployment configures a tile CDN (`cdn_base_url`), that
  // origin is first-party too — a genuine embed-token failure there must
  // still surface the toast, not be swallowed as "third-party".
  it('surfaces the toast on a 401 from the configured tile CDN origin', async () => {
    tileConfigState.cdn_base_url = 'https://cdn.example.com';
    renderEmbedViewer();
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    mapState.fakeMap.emit('error', {
      error: { status: 401, url: 'https://cdn.example.com/api/tiles/collection.mvt' },
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: expect.any(String) }),
    );
  });
});
