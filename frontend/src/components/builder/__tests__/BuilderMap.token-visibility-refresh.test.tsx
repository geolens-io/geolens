// fix(#755): wiring pin for the proactive tile-token refresh. Tile sigs are
// minted on 900 s `round_expiry()` boundaries, so a tab backgrounded for a few
// minutes returns with an expired sig and MapLibre 403s every visible tile
// before the reactive GUARD-03 / #621 handler heals the map. BuilderMap must
// kick the SAME throttled re-mint on the visible edge of `visibilitychange`.
//
// The hook's own semantics (skew window, hidden-edge no-op, unmount detach) are
// covered in hooks/__tests__/use-tile-auth-recovery.test.ts. This file pins the
// CALL SITE: delete `useVisibleTileTokenRefresh(...)` from BuilderMap and these
// fail. Uses the vi.hoisted fakeMap + @vis.gl/react-maplibre recipe from
// BuilderMap.terrain-visibility.test.tsx.

import type { ReactNode } from 'react';
import { act, render } from '@/test/test-utils';
import type { MapLayerResponse } from '@/types/api';
import type { VectorTileToken } from '@/api/tiles';
import { BuilderMap } from '../BuilderMap';

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({
    data: [
      {
        id: 'openfreemap-positron',
        label: 'Light',
        url: 'https://tiles.example.com/styles/basic',
        enabled: true,
      },
    ],
  }),
  useMapDefaults: () => ({ data: { center_lng: 0, center_lat: 0, zoom: 2 } }),
  useTileConfig: () => ({ data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' } }),
  useEnabledPlugins: () => ({ data: [], isLoading: false }),
}));

const tileTokenState = vi.hoisted(() => ({
  tokens: [] as Array<{ data: VectorTileToken | undefined; isLoading: boolean; isError: boolean }>,
  invalidate: vi.fn(),
}));

vi.mock('@/hooks/use-tile-token', () => ({
  // The re-mint the builder's recovery path calls: dropping the cached tile
  // tokens is what forces a fresh sig.
  useInvalidateTileTokens: () => tileTokenState.invalidate,
  useTileTokens: () => tileTokenState.tokens,
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

// Stub the imperative style/layer writers — this test only cares that the
// re-mint fires, not what the fake map's style ends up looking like.
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return {
    ...actual,
    syncLayersToMap: vi.fn(),
    applyBasemapConfigToMap: vi.fn(),
    reorderBasemapLabels: vi.fn(),
    reorderDataLayers: vi.fn(),
    ensureRasterDemTerrainSource: vi.fn(),
  };
});

type FakeMap = {
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  isStyleLoaded: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  setMissingStyleImageResolver: ReturnType<typeof vi.fn>;
  setProjection: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  fitBounds: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  setZoom: ReturnType<typeof vi.fn>;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const track = (event: string, handler: (payload?: unknown) => void) => {
    const existing = handlers.get(event) ?? new Set();
    existing.add(handler);
    handlers.set(event, existing);
  };
  const fakeMap: FakeMap = {
    on: vi.fn(track),
    off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      handlers.get(event)?.delete(handler);
    }),
    once: vi.fn(track),
    setTransformRequest: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getCanvas: vi.fn(() => ({ style: { cursor: '' }, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    setTerrain: vi.fn(),
    setMissingStyleImageResolver: vi.fn(),
    setProjection: vi.fn(),
    triggerRepaint: vi.fn(),
    getSource: vi.fn(() => null),
    getLayer: vi.fn(() => null),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    getZoom: vi.fn(() => 2),
    setZoom: vi.fn(),
  };
  return { fakeMap, reset: () => handlers.clear() };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (event: { target: FakeMap }) => void }) => {
      React.useEffect(() => {
        onLoad?.({ target: mapState.fakeMap });
      }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
  };
});

const DATASET_ID = 'ds-uuid-755';

function vectorToken(expSeconds: number): VectorTileToken {
  return { kind: 'vector', sig: 'sig-755', exp: expSeconds, scope: 'parcels', expires_in: 900 };
}

function makeVectorLayer(): MapLayerResponse {
  return {
    id: 'layer-755',
    dataset_id: DATASET_ID,
    dataset_name: 'Parcels',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'parcels',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: null,
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
  } as unknown as MapLayerResponse;
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
}

async function renderBuilderMap() {
  await act(async () => {
    render(<BuilderMap layers={[makeVectorLayer()]} basemapStyle="openfreemap-positron" />);
  });
}

describe('BuilderMap proactive tile-token refresh on tab return (fix #755)', () => {
  beforeEach(() => {
    mapState.reset();
    tileTokenState.invalidate.mockClear();
    setVisibility('visible');
  });

  afterEach(() => {
    setVisibility('visible');
  });

  it('re-mints when the tab becomes visible with an expired sig', async () => {
    tileTokenState.tokens = [
      { data: vectorToken(Math.floor(Date.now() / 1000) - 120), isLoading: false, isError: false },
    ];
    await renderBuilderMap();
    // Mount itself must not re-mint — the mount race is a separate concern.
    expect(tileTokenState.invalidate).not.toHaveBeenCalled();

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(tileTokenState.invalidate).toHaveBeenCalledTimes(1);
  });

  it('does not re-mint when the sig is still comfortably fresh', async () => {
    tileTokenState.tokens = [
      { data: vectorToken(Math.floor(Date.now() / 1000) + 900), isLoading: false, isError: false },
    ];
    await renderBuilderMap();

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(tileTokenState.invalidate).not.toHaveBeenCalled();
  });

  it('does not re-mint on the hidden edge (a paused map drops the setTiles reload)', async () => {
    tileTokenState.tokens = [
      { data: vectorToken(Math.floor(Date.now() / 1000) - 120), isLoading: false, isError: false },
    ];
    await renderBuilderMap();

    setVisibility('hidden');
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(tileTokenState.invalidate).not.toHaveBeenCalled();
  });

  it('stops re-minting once the map unmounts (no leaked visibilitychange listener)', async () => {
    tileTokenState.tokens = [
      { data: vectorToken(Math.floor(Date.now() / 1000) - 120), isLoading: false, isError: false },
    ];
    let unmount: () => void = () => {};
    await act(async () => {
      ({ unmount } = render(
        <BuilderMap layers={[makeVectorLayer()]} basemapStyle="openfreemap-positron" />,
      ));
    });

    await act(async () => {
      unmount();
    });
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(tileTokenState.invalidate).not.toHaveBeenCalled();
  });
});
