// fix(#890): the #755 double-log shape was still live for raster/DEM tiles.
// `isHandledTileAuthError` excludes `/raster-tiles/` (audit w3-maps A1) because a
// fresh tile sig cannot fix raster auth — that rides the Authorization header —
// but BuilderMap's own error handler reported a suppressed "re-mint requested"
// row anyway (`reminted` is true even though resignVectorSourceForRetry returned
// false), while the <Map> onError fallback still console.errored the same
// failure. One suppressed yellow next to one unsuppressed red, and the early
// return swallowed the toast, for a failure nobody was recovering.
//
// The handler now agrees with the predicate: a raster/DEM 401/403 is reported
// ONCE, unsuppressed, and surfaces the session-expired toast. The re-mint itself
// still runs — its apiFetch renews an expiring JWT, which IS what a raster 401
// needs (codex P1 on this PR) — it just no longer counts as recovery. The vector
// path (GUARD-03 re-sign + #621 re-mint) is unchanged.

import type { ReactNode } from 'react';
import { act, render } from '@/test/test-utils';
import type { MapLayerResponse } from '@/types/api';
import type { VectorTileToken } from '@/api/tiles';
import { getSourceIdForLayer } from '@/components/builder/map-sync';
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

// Capture the problem-reporter writes — the report buffer is where the double
// log was visible, so the entries ARE the assertion surface here.
const reportState = vi.hoisted(() => ({ push: vi.fn(), remint: vi.fn() }));
vi.mock('@/lib/report', () => ({
  pushReportEntry: reportState.push,
  reportTileTokenRemint: reportState.remint,
}));

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

import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';

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
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const track = (event: string, handler: (payload?: unknown) => void) => {
    const existing = handlers.get(event) ?? new Set();
    existing.add(handler);
    handlers.set(event, existing);
  };
  const setTiles = vi.fn();
  const state = {
    setTiles,
    // The <Map> `onError` prop, captured from the render so the test drives the
    // REAL wiring (logUnhandledMapError) instead of assuming it.
    onError: null as ((e: unknown) => void) | null,
    fakeMap: {} as FakeMap,
    reset: () => {
      handlers.clear();
      setTiles.mockClear();
      state.onError = null;
    },
  };
  state.fakeMap = {
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
    getSource: vi.fn(() => ({ type: 'vector', setTiles })),
    getLayer: vi.fn(() => null),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    getZoom: vi.fn(() => 2),
    setZoom: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };
  return state;
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({
      children,
      onLoad,
      onError,
    }: {
      children?: ReactNode;
      onLoad?: (event: { target: FakeMap }) => void;
      onError?: (e: unknown) => void;
    }) => {
      mapState.onError = onError ?? null;
      React.useEffect(() => {
        onLoad?.({ target: mapState.fakeMap });
      }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
  };
});

const DATASET_ID = 'ds-uuid-890';
const RASTER_TILE_URL = `${window.location.origin}/raster-tiles/${DATASET_ID}/tiles/9/151/191.png`;

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-890',
    dataset_id: DATASET_ID,
    dataset_name: 'Elevation',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'elevation',
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
    ...(overrides as object),
  } as unknown as MapLayerResponse;
}

let errorSpy: ReturnType<typeof vi.spyOn>;

async function renderBuilderMap(layer: MapLayerResponse) {
  await act(async () => {
    render(<BuilderMap layers={[layer]} basemapStyle="openfreemap-positron" />);
  });
  // Drop the mount-time token→setTiles sync (and anything React logged during
  // it) so the assertions below only see what the error handler did.
  mapState.setTiles.mockClear();
  errorSpy.mockClear();
}

/** Entries the surface handler pushed for a map error (report buffer rows). */
function pushedEntries() {
  return reportState.push.mock.calls.map((call) => call[0] as Record<string, unknown>);
}

describe('BuilderMap raster/DEM tile auth errors (fix #890)', () => {
  beforeEach(() => {
    mapState.reset();
    tileTokenState.invalidate.mockClear();
    reportState.push.mockClear();
    reportState.remint.mockClear();
    vi.mocked(toast.error).mockClear();
    // A live session: the auth toast is gated on the session existing
    // (fix #628). fix(#1446): keyed on the ACCESS token — the refresh token is
    // an httpOnly cookie now and reads as null for every cookie-mode user, so
    // seeding only refreshToken here would assert against a state real
    // sessions no longer reach.
    useAuthStore.setState({ token: 'access-token', refreshToken: null });
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    tileTokenState.tokens = [
      {
        data: { kind: 'vector', sig: 'sig-890', exp: Math.floor(Date.now() / 1000) + 900, scope: 'elevation', expires_in: 900 },
        isLoading: false,
        isError: false,
      },
    ];
  });

  afterEach(() => {
    errorSpy.mockRestore();
    useAuthStore.setState({ token: null, refreshToken: null });
  });

  it('logs a raster 403 exactly once and never claims a re-sign/re-mint', async () => {
    const layer = makeLayer({ dataset_record_type: 'raster_dataset' });
    await renderBuilderMap(layer);

    const event = {
      error: { message: `AJAXError: (403): ${RASTER_TILE_URL}`, status: 403, url: RASTER_TILE_URL },
      sourceId: getSourceIdForLayer(layer),
    };
    // Both halves of the double log: the surface's own map.on('error') handler
    // AND the wrapper's onError fallback, for the same MapLibre event.
    act(() => {
      mapState.fakeMap.emit('error', event);
      mapState.onError?.(event);
    });

    // fix(#890) (codex P1): the re-mint still runs — its apiFetch renews an
    // expiring JWT, the one thing that can fix a raster 401 — but nothing about
    // it recovers the tile, so no recovery may be CLAIMED.
    expect(tileTokenState.invalidate).toHaveBeenCalledTimes(1);
    expect(pushedEntries()).toHaveLength(1);
    expect(pushedEntries()[0]).toMatchObject({ suppressed: false, severity: 'error', source: 'maplibre' });
    expect(pushedEntries().some((e) => String(e.message).includes('re-mint requested'))).toBe(false);
    // …and the single honest log is the wrapper's console.error.
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(event.error);
    // The mint that did run is reported once, attributed to the error path.
    expect(reportState.remint).toHaveBeenCalledTimes(1);
    expect(reportState.remint).toHaveBeenCalledWith('builder', 'tile-error');
  });

  it('surfaces the auth toast for a raster 401 instead of swallowing it', async () => {
    const layer = makeLayer({ is_dem: true });
    await renderBuilderMap(layer);

    act(() => {
      mapState.fakeMap.emit('error', {
        error: { status: 401, url: RASTER_TILE_URL },
        sourceId: getSourceIdForLayer(layer),
      });
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: 'builder-map-auth-error' }),
    );
    expect(mapState.setTiles).not.toHaveBeenCalled();
  });

  // fix(#890): a raster auth failure is now recorded the same way an unrecovered
  // 5xx tile error already was — one unsuppressed `maplibre` row from the handler
  // plus the wrapper's console.error (which initReportCapture turns into a
  // `console` row). That pairing is the buffer's shape for EVERY error no
  // surface recovers, and it predates this PR; the #755 bug was a suppressed
  // "recovered" row sitting next to it, not the pairing. Dropping either half
  // for raster would cost the sourceId (the console row has none) or the devtools
  // log (the surfaces without their own row have nothing else). This pins the
  // parity so a future "dedupe raster" change has to face the 5xx case too.
  it('records a raster 403 the same way an unrecovered 5xx is recorded', async () => {
    const layer = makeLayer({ dataset_record_type: 'raster_dataset' });
    await renderBuilderMap(layer);

    const serverError = {
      error: { message: 'AJAXError: (500)', status: 500, url: RASTER_TILE_URL },
      sourceId: getSourceIdForLayer(layer),
    };
    act(() => {
      mapState.fakeMap.emit('error', serverError);
      mapState.onError?.(serverError);
    });
    const fiveHundred = pushedEntries();
    const fiveHundredLogs = errorSpy.mock.calls.length;
    // Guard against a vacuous comparison below.
    expect(fiveHundred).toHaveLength(1);
    expect(fiveHundred[0]).toMatchObject({ severity: 'error', suppressed: false });
    expect(fiveHundredLogs).toBe(1);

    reportState.push.mockClear();
    errorSpy.mockClear();
    const rasterError = {
      error: { message: `AJAXError: (403): ${RASTER_TILE_URL}`, status: 403, url: RASTER_TILE_URL },
      sourceId: getSourceIdForLayer(layer),
    };
    act(() => {
      mapState.fakeMap.emit('error', rasterError);
      mapState.onError?.(rasterError);
    });

    expect(pushedEntries()).toHaveLength(fiveHundred.length);
    expect(pushedEntries()[0]).toMatchObject({
      severity: fiveHundred[0].severity,
      suppressed: fiveHundred[0].suppressed,
    });
    expect(errorSpy.mock.calls.length).toBe(fiveHundredLogs);
  });

  it('still re-signs and re-mints a first-party VECTOR 403 (GUARD-03 / #621 intact)', async () => {
    const layer = makeLayer();
    const sourceId = getSourceIdForLayer(layer);
    await renderBuilderMap(layer);

    const vectorUrl = `${window.location.origin}/api/tiles/data.elevation/9/151/191.pbf?sig=stale`;
    const event = { error: { status: 403, url: vectorUrl }, sourceId };
    act(() => {
      mapState.fakeMap.emit('error', event);
      mapState.onError?.(event);
    });

    expect(mapState.setTiles).toHaveBeenCalledTimes(1);
    expect(tileTokenState.invalidate).toHaveBeenCalledTimes(1);
    // Recovery IS claimed here, suppressed, and the wrapper stays silent so the
    // recovered case reads as one row instead of two.
    const entries = pushedEntries();
    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({ suppressed: true, severity: 'warning' });
    expect(entries[1]).toMatchObject({ suppressed: true });
    expect(String(entries[1].message)).toContain('re-signed');
    expect(errorSpy).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
