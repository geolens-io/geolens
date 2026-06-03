import { describe, it, expect, vi } from 'vitest';
import { syncLayersToMap } from '../map-sync';
import type { SyncLayerInput } from '../map-sync';
import type { TileToken } from '@/api/tiles';

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

function makeMockMap() {
  // Phase 1050 SF-04: with deduped sources, the mock must track addSource
  // calls so that `if (!map.getSource(sourceId))` correctly returns falsy
  // for already-added sources within a single sync — otherwise two layers
  // sharing a dataset both pass the idempotency guard and addSource fires
  // twice (instrumentation artifact, not a real bug).
  const sources = new Map<string, unknown>();
  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: unknown) => {
      sources.set(id, spec);
    }),
    addLayer: vi.fn(),
    getLayer: vi.fn(() => null),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: [] })),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeLayer(overrides: Partial<SyncLayerInput> = {}): SyncLayerInput {
  return {
    id: 'l1',
    dataset_id: 'ds-1',
    dataset_table_name: 'roads',
    dataset_geometry_type: 'LINESTRING',
    opacity: 1,
    visible: true,
    paint: { 'line-color': '#000', 'line-width': 2 },
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    is_dem: false,
    is_3d: false,
    feature_count: null,
    ...overrides,
  };
}

const VECTOR_TOKEN: TileToken = {
  kind: 'vector',
  sig: 'mock',
  exp: 9999999999,
  scope: 'test',
  expires_in: 3600,
};

function tokens(layer: SyncLayerInput) {
  const m = new Map<string, TileToken>();
  m.set(layer.dataset_id, VECTOR_TOKEN);
  return m;
}

describe('syncLayersToMap line-gradient lineMetrics emission', () => {
  // Phase 1050 SF-04: non-cluster vector layers now share a deduped source
  // keyed by dataset_table_name. The factory default is `roads`, so the
  // source id is `source-data-roads` (not the legacy per-layer key).
  const SHARED_SRC = 'source-data-roads';

  it('emits lineMetrics: true when a line layer has line-gradient paint set', () => {
    const map = makeMockMap();
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const layer = makeLayer({
      id: 'l-grad',
      paint: { 'line-color': '#000', 'line-width': 2, 'line-gradient': gradient },
    });
    syncLayersToMap(map, [layer], tokens(layer), undefined, { current: new Set() }, { current: '' });
    const calls = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c: unknown[]) => c[0] === SHARED_SRC,
    );
    expect(calls.length).toBe(1);
    expect(calls[0][1]).toMatchObject({ type: 'vector', lineMetrics: true });
  });

  it('emits lineMetrics: true when builder.lineGradient intent is recorded with empty paint', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      id: 'l-intent',
      paint: { 'line-color': '#000', 'line-width': 2 },
      // Cast required: StyleConfig requires `mode | column | ramp` for data-driven
      // styling, but this test only exercises the line-gradient detection path,
      // which reads `style_config.builder.lineGradient` and ignores the rest.
      // Constructing a full StyleConfig just to satisfy TS would obscure intent.
      style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#00f' }] } } } as unknown as SyncLayerInput['style_config'],
    });
    syncLayersToMap(map, [layer], tokens(layer), undefined, { current: new Set() }, { current: '' });
    const calls = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c: unknown[]) => c[0] === SHARED_SRC,
    );
    expect(calls.length).toBe(1);
    expect(calls[0][1]).toMatchObject({ type: 'vector', lineMetrics: true });
  });

  it('omits lineMetrics when no consumer needs it (no regression for plain line layers)', () => {
    const map = makeMockMap();
    const layer = makeLayer({
      id: 'l-plain',
      paint: { 'line-color': '#000', 'line-width': 2 },
    });
    syncLayersToMap(map, [layer], tokens(layer), undefined, { current: new Set() }, { current: '' });
    const calls = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c: unknown[]) => c[0] === SHARED_SRC,
    );
    expect(calls.length).toBe(1);
    const spec = calls[0][1] as Record<string, unknown>;
    expect(spec).not.toHaveProperty('lineMetrics');
  });

  it('rejects array-shaped builder.lineGradient intent (parity with backend dict-only contract)', () => {
    // Locked contract per CONTEXT D-01: builder.lineGradient must be a non-empty plain object.
    // Arrays must be rejected on both sides. Backend `_layer_uses_line_gradient` does this via
    // `isinstance(intent, dict)`; frontend `lineGradientNeededFor` does it via
    // `!Array.isArray(intent)`. This test locks the frontend half so future Phase 256 changes
    // cannot silently introduce array-shaped intent without aligning the backend too.
    const map = makeMockMap();
    const layer = makeLayer({
      id: 'l-array-intent',
      paint: { 'line-color': '#000', 'line-width': 2 },
      // Cast required: this test deliberately constructs an invalid array-shaped
      // `lineGradient` to lock the rejection path in `lineGradientNeededFor`.
      // The runtime contract is `{ stops: ... }`-only; the cast bypasses TS so
      // we can verify the runtime guard rejects array-shaped intent without
      // weakening the public BuilderStyleConfig type.
      style_config: {
        builder: { lineGradient: [{ position: 0, color: '#00f' }] },
      } as unknown as SyncLayerInput['style_config'],
    });
    syncLayersToMap(map, [layer], tokens(layer), undefined, { current: new Set() }, { current: '' });
    const calls = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c: unknown[]) => c[0] === SHARED_SRC,
    );
    expect(calls.length).toBe(1);
    const spec = calls[0][1] as Record<string, unknown>;
    expect(spec).not.toHaveProperty('lineMetrics');
  });

  it('emits lineMetrics: true on the deduped shared source when ANY consumer needs it (SF-04)', () => {
    const map = makeMockMap();
    const sharedDatasetId = 'ds-shared';
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    // Phase 1050 SF-04: two layers sharing dataset_table_name now share ONE
    // MapLibre source. If ANY consumer needs lineMetrics, the shared source
    // gets it — exactly what `lineGradientNeededFor`'s full-list iteration
    // was designed for (see map-sync.ts line 336 forward-compat comment).
    const layerA = makeLayer({ id: 'a', dataset_id: sharedDatasetId, paint: { 'line-color': '#000', 'line-width': 2 } });
    const layerB = makeLayer({ id: 'b', dataset_id: sharedDatasetId, paint: { 'line-color': '#000', 'line-width': 2, 'line-gradient': gradient } });
    syncLayersToMap(map, [layerA, layerB], new Map([
      [sharedDatasetId, VECTOR_TOKEN],
    ]), undefined, { current: new Set() }, { current: '' });
    // Only one addSource call for the shared deduped source.
    const sharedCalls = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c: unknown[]) => c[0] === SHARED_SRC,
    );
    expect(sharedCalls.length).toBe(1);
    expect(sharedCalls[0][1]).toMatchObject({ type: 'vector', lineMetrics: true });
  });
});
