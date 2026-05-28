/**
 * contour-sync.test.ts
 *
 * Unit tests for syncContourLayer and ensureDemSource.
 *
 * maplibre-contour is mocked so the tests run without a real MapLibre context
 * or DEM tile server.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { syncContourLayer, ensureDemSource, _demSources } from '../contour-sync';
import type { AdapterLayerInput } from '../layer-adapters/types';

// ---------------------------------------------------------------------------
// Mock maplibre-contour
// ---------------------------------------------------------------------------

const mockContourProtocolUrl = vi.fn(
  () => 'contour-protocol://source-dem1-contour?thresholds=...',
);
const mockSetupMaplibre = vi.fn();

// DemSource must be mocked as a constructor function (class) so `new DemSource(...)`
// works inside ensureDemSource. Arrow functions cannot be called with `new`.
function MockDemSource() {
  return {
    setupMaplibre: mockSetupMaplibre,
    contourProtocolUrl: mockContourProtocolUrl,
  };
}

vi.mock('maplibre-contour', () => ({
  default: {
    DemSource: MockDemSource,
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createMockMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  return {
    getLayer: vi.fn((id: string) => (layers.has(id) ? { id } : null)),
    removeLayer: vi.fn((id: string) => { layers.delete(id); }),
    addLayer: vi.fn((spec: { id: string }) => { layers.add(spec.id); }),
    getSource: vi.fn((id: string) => (sources.has(id) ? { id } : null)),
    addSource: vi.fn((id: string) => { sources.add(id); }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    setPaintProperty: vi.fn(),
    // expose internals for assertions
    _layers: layers,
    _sources: sources,
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'dem1',
    dataset_table_name: 'dem_table',
    dataset_geometry_type: null,
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    is_dem: true,
    sourceId: 'source-dem1',
    layerId: 'layer-dem1',
    sourceLayer: 'raster',
    tileUrl: '/raster-tiles/dem1/tiles/{z}/{x}/{y}.png',
    ...overrides,
  } as AdapterLayerInput;
}

// ---------------------------------------------------------------------------
// Reset registry before each test to avoid cross-test contamination
// ---------------------------------------------------------------------------

beforeEach(() => {
  _demSources.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('syncContourLayer', () => {
  it('disabled: removes existing line layer and source, does not add to desiredSources', () => {
    const map = createMockMap();
    // Pre-populate line layer and contour source to simulate "was enabled before"
    map._layers.add('layer-dem1-contour');
    map._sources.add('source-dem1-contour');

    const desiredSources = new Set<string>();
    const input = makeInput({ paint: { '_contour-enabled': false } });

    syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);

    expect(map.removeLayer).toHaveBeenCalledWith('layer-dem1-contour');
    expect(map.removeSource).toHaveBeenCalledWith('source-dem1-contour');
    expect(desiredSources.has('source-dem1-contour')).toBe(false);
  });

  it('disabled (paint key absent): does nothing if layer/source do not exist', () => {
    const map = createMockMap();
    const desiredSources = new Set<string>();
    const input = makeInput({ paint: {} });

    syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);

    expect(map.removeLayer).not.toHaveBeenCalled();
    expect(map.removeSource).not.toHaveBeenCalled();
    expect(desiredSources.size).toBe(0);
  });

  it('enabled: adds vector source + line layer; adds contourSourceId to desiredSources', () => {
    const map = createMockMap();
    const desiredSources = new Set<string>();
    const input = makeInput({
      paint: {
        '_contour-enabled': true,
        '_contour-interval': 100,
        '_contour-color': '#333333',
        '_contour-weight': 2,
      },
    });

    syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);

    // Source should be added
    expect(map.addSource).toHaveBeenCalledWith(
      'source-dem1-contour',
      expect.objectContaining({ type: 'vector' }),
    );

    // Line layer should be added with correct paint
    expect(map.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'layer-dem1-contour',
        type: 'line',
        source: 'source-dem1-contour',
        'source-layer': 'contours',
        paint: {
          'line-color': '#333333',
          'line-width': 2,
        },
      }),
      'layer-dem1', // inserted before (below) the hillshade layer
    );

    // Must be added to desiredSources
    expect(desiredSources.has('source-dem1-contour')).toBe(true);
  });

  it('enabled (layer already exists): calls setPaintProperty for color and weight, not addLayer', () => {
    const map = createMockMap();
    // Simulate layer already on map
    map._layers.add('layer-dem1-contour');
    map._sources.add('source-dem1-contour');

    const desiredSources = new Set<string>();
    const input = makeInput({
      paint: {
        '_contour-enabled': true,
        '_contour-color': '#FF0000',
        '_contour-weight': 1.5,
      },
    });

    syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);

    expect(map.addLayer).not.toHaveBeenCalled();
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-dem1-contour', 'line-color', '#FF0000');
    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-dem1-contour', 'line-width', 1.5);
    expect(desiredSources.has('source-dem1-contour')).toBe(true);
  });

  it('changing weight calls setPaintProperty with line-width', () => {
    const map = createMockMap();
    map._layers.add('layer-dem1-contour');
    map._sources.add('source-dem1-contour');

    const desiredSources = new Set<string>();
    const input = makeInput({
      paint: { '_contour-enabled': true, '_contour-weight': 3 },
    });

    syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);

    expect(map.setPaintProperty).toHaveBeenCalledWith('layer-dem1-contour', 'line-width', 3);
  });

  it('enabled with default values falls back to interval=100, color=#555555, weight=1', () => {
    const map = createMockMap();
    const desiredSources = new Set<string>();
    const input = makeInput({ paint: { '_contour-enabled': true } });

    syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);

    expect(map.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        paint: { 'line-color': '#555555', 'line-width': 1 },
      }),
      'layer-dem1',
    );
  });

  it('degrades gracefully when addLayer throws (no exception escapes)', () => {
    const map = createMockMap();
    (map.addLayer as ReturnType<typeof vi.fn>).mockImplementation(() => {
      throw new Error('map not ready');
    });
    const desiredSources = new Set<string>();
    const input = makeInput({ paint: { '_contour-enabled': true } });

    expect(() => {
      syncContourLayer(map as unknown as import('maplibre-gl').Map, input, desiredSources);
    }).not.toThrow();
  });
});

describe('ensureDemSource', () => {
  it('calls setupMaplibre exactly once for the same sourceId', () => {
    const map = createMockMap();

    ensureDemSource(map as unknown as import('maplibre-gl').Map, 'source-dem1', '/tiles/{z}/{x}/{y}.png');
    ensureDemSource(map as unknown as import('maplibre-gl').Map, 'source-dem1', '/tiles/{z}/{x}/{y}.png');

    // setupMaplibre should be called only once despite two calls
    expect(mockSetupMaplibre).toHaveBeenCalledTimes(1);
  });

  it('returns the cached DemSource on second call', () => {
    const map = createMockMap();

    const first = ensureDemSource(map as unknown as import('maplibre-gl').Map, 'source-dem1', '/tiles/{z}/{x}/{y}.png');
    const second = ensureDemSource(map as unknown as import('maplibre-gl').Map, 'source-dem1', '/tiles/{z}/{x}/{y}.png');

    expect(first).toBe(second);
  });

  it('creates separate DemSource instances for different sourceIds', () => {
    const map = createMockMap();

    ensureDemSource(map as unknown as import('maplibre-gl').Map, 'source-dem-a', '/tiles/{z}/{x}/{y}.png');
    ensureDemSource(map as unknown as import('maplibre-gl').Map, 'source-dem-b', '/tiles/{z}/{x}/{y}.png');

    expect(mockSetupMaplibre).toHaveBeenCalledTimes(2);
    expect(_demSources.size).toBe(2);
  });
});
