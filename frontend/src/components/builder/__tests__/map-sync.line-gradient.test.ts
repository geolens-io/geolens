import { describe, it, expect, vi } from 'vitest';
import { syncLayersToMap } from '../map-sync';
import type { SyncLayerInput } from '../map-sync';
import type { TileToken } from '@/api/tiles';

vi.mock('@/lib/tile-utils', () => ({
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
}));

Object.defineProperty(window, 'location', {
  value: { origin: 'http://localhost:8080' },
  writable: true,
});

function makeMockMap() {
  return {
    getSource: vi.fn(() => null),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getLayer: vi.fn(() => null),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
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
  it('emits lineMetrics: true when a line layer has line-gradient paint set', () => {
    const map = makeMockMap();
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const layer = makeLayer({
      id: 'l-grad',
      paint: { 'line-color': '#000', 'line-width': 2, 'line-gradient': gradient },
    });
    syncLayersToMap(map, [layer], tokens(layer), undefined, { current: new Set() }, { current: '' });
    const calls = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c: unknown[]) => c[0] === 'source-l-grad',
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
      (c: unknown[]) => c[0] === 'source-l-intent',
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
      (c: unknown[]) => c[0] === 'source-l-plain',
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
      (c: unknown[]) => c[0] === 'source-l-array-intent',
    );
    expect(calls.length).toBe(1);
    const spec = calls[0][1] as Record<string, unknown>;
    expect(spec).not.toHaveProperty('lineMetrics');
  });

  it('emits lineMetrics: true once when two layers share a source and one needs it', () => {
    const map = makeMockMap();
    const sharedDatasetId = 'ds-shared';
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const layerA = makeLayer({ id: 'a', dataset_id: sharedDatasetId, paint: { 'line-color': '#000', 'line-width': 2 } });
    const layerB = makeLayer({ id: 'b', dataset_id: sharedDatasetId, paint: { 'line-color': '#000', 'line-width': 2, 'line-gradient': gradient } });
    // Both layers share dataset_id but each layer gets its own sourceId via prefixed('source', layer.id).
    // In the current map-sync model, each layer has its own source — so the shared-source case is when
    // two SyncLayerInput entries have the SAME id (which is impossible by construction). The realistic
    // shared case is two map layers pointing at the same dataset_id but distinct layer ids; each gets
    // its own source. This test asserts that EACH source is independently evaluated, and the gradient
    // layer's source emits lineMetrics: true while the plain layer's source does not.
    syncLayersToMap(map, [layerA, layerB], new Map([
      [sharedDatasetId, VECTOR_TOKEN],
    ]), undefined, { current: new Set() }, { current: '' });
    const callA = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.find(
      (c: unknown[]) => c[0] === 'source-a',
    );
    const callB = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.find(
      (c: unknown[]) => c[0] === 'source-b',
    );
    expect(callA).toBeDefined();
    expect(callB).toBeDefined();
    const specA = callA![1] as Record<string, unknown>;
    const specB = callB![1] as Record<string, unknown>;
    expect(specA).not.toHaveProperty('lineMetrics');
    expect(specB).toMatchObject({ lineMetrics: true });
  });
});
