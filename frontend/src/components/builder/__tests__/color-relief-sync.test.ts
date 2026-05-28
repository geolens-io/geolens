import { describe, it, expect, vi, beforeEach } from 'vitest';
import { buildElevationExpression, syncColorReliefLayer } from '../color-relief-sync';
import type { AdapterLayerInput } from '../layer-adapters/types';

// ---------------------------------------------------------------------------
// Minimal mock map
// ---------------------------------------------------------------------------
function createMockMap() {
  const layers = new Map<string, { id: string }>();
  const sources = new Set<string>();

  return {
    _layers: layers,
    _sources: sources,
    getLayer: vi.fn((id: string) => layers.get(id) ?? null),
    addLayer: vi.fn((layer: { id: string }) => {
      layers.set(layer.id, layer);
    }),
    removeLayer: vi.fn((id: string) => {
      layers.delete(id);
    }),
    getSource: vi.fn((id: string) => (sources.has(id) ? { type: 'raster-dem' } : null)),
  } as unknown as import('maplibre-gl').Map & {
    _layers: Map<string, { id: string }>;
    _sources: Set<string>;
  };
}

function makeInput(
  overrides: Partial<AdapterLayerInput> & {
    paint?: Record<string, unknown>;
    style_config?: Record<string, unknown> | null;
  } = {},
): AdapterLayerInput {
  return {
    id: 'dem-1',
    dataset_table_name: 'dem_table',
    dataset_geometry_type: null,
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    is_dem: true,
    sourceId: 'source-dem-1',
    layerId: 'layer-dem-1',
    sourceLayer: '',
    tileUrl: '',
    style_config: { render_mode: 'hillshade' },
    ...overrides,
  } as AdapterLayerInput;
}

// ---------------------------------------------------------------------------
// buildElevationExpression
// ---------------------------------------------------------------------------
describe('buildElevationExpression', () => {
  it('returns an interpolate expression starting with the correct tokens', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr[0]).toBe('interpolate');
    expect(expr[1]).toEqual(['linear']);
    expect(expr[2]).toEqual(['elevation']);
  });

  it('produces 7 color stops (14 value/color pairs after the 3 header tokens)', () => {
    const expr = buildElevationExpression('Viridis');
    // Total length = 3 (header) + 7 * 2 (stop pairs) = 17
    expect(expr.length).toBe(17);
  });

  it('first elevation stop is at elevMin (default 0)', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr[3]).toBe(0);
  });

  it('last elevation stop is at elevMax (default 4000)', () => {
    const expr = buildElevationExpression('Viridis');
    expect(expr[expr.length - 2]).toBe(4000);
  });

  it('elevation stops are evenly spaced across 0–4000 m', () => {
    const expr = buildElevationExpression('Viridis');
    const stops: number[] = [];
    for (let i = 3; i < expr.length; i += 2) {
      stops.push(expr[i] as number);
    }
    expect(stops).toHaveLength(7);
    // Step = 4000 / 6 ≈ 666.67
    const step = 4000 / 6;
    for (let i = 0; i < stops.length; i++) {
      expect(stops[i]).toBeCloseTo(i * step, 5);
    }
  });

  it('color values are hex strings', () => {
    const expr = buildElevationExpression('Viridis');
    for (let i = 4; i < expr.length; i += 2) {
      expect(typeof expr[i]).toBe('string');
      expect((expr[i] as string).startsWith('#')).toBe(true);
    }
  });

  it('respects custom elevMin and elevMax', () => {
    const expr = buildElevationExpression('Inferno', 500, 2000);
    expect(expr[3]).toBe(500);
    expect(expr[expr.length - 2]).toBe(2000);
  });

  it('falls back to a valid expression for an unknown ramp name', () => {
    // getRampColors falls back to YlOrRd for unknown names (Threat T-1140-05)
    const expr = buildElevationExpression('NotARealRamp');
    expect(expr[0]).toBe('interpolate');
    expect(expr.length).toBe(17);
  });
});

// ---------------------------------------------------------------------------
// syncColorReliefLayer
// ---------------------------------------------------------------------------
describe('syncColorReliefLayer', () => {
  let map: ReturnType<typeof createMockMap>;

  beforeEach(() => {
    map = createMockMap();
    // Pre-register the raster-dem source (as hillshade-adapter would)
    map._sources.add('source-dem-1');
  });

  it('adds a color-relief layer when enabled + hillshade mode', () => {
    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    expect(map.addLayer).toHaveBeenCalledOnce();
    const layerSpec = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      id: string;
      type: string;
      source: string;
    };
    expect(layerSpec.id).toBe('layer-dem-1-colorrelief');
    expect(layerSpec.type).toBe('color-relief');
    expect(layerSpec.source).toBe('source-dem-1');
  });

  it('inserts the companion layer BELOW the hillshade layer (beforeLayerId arg)', () => {
    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    const beforeLayerId = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(beforeLayerId).toBe('layer-dem-1');
  });

  it('uses the existing sourceId (does NOT call addSource)', () => {
    const mockMapWithAddSource = {
      ...map,
      addSource: vi.fn(),
    };
    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(mockMapWithAddSource as unknown as import('maplibre-gl').Map, input);

    expect(mockMapWithAddSource.addSource).not.toHaveBeenCalled();
  });

  it('removes the companion layer when disabled', () => {
    // Pre-populate the companion layer as "already present"
    map._layers.set('layer-dem-1-colorrelief', { id: 'layer-dem-1-colorrelief' });

    const input = makeInput({
      paint: { '_hypso-enabled': false },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    expect(map.removeLayer).toHaveBeenCalledWith('layer-dem-1-colorrelief');
    expect(map.addLayer).not.toHaveBeenCalled();
  });

  it('does NOT add a color-relief layer in terrain mode', () => {
    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'terrain' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    expect(map.addLayer).not.toHaveBeenCalled();
  });

  it('does NOT add a color-relief layer in image mode (no render_mode)', () => {
    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: undefined },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    expect(map.addLayer).not.toHaveBeenCalled();
  });

  it('removes any existing companion layer in terrain mode (not just skips add)', () => {
    map._layers.set('layer-dem-1-colorrelief', { id: 'layer-dem-1-colorrelief' });

    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'terrain' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    expect(map.removeLayer).toHaveBeenCalledWith('layer-dem-1-colorrelief');
    expect(map.addLayer).not.toHaveBeenCalled();
  });

  it('recreates (removeLayer then addLayer) when ramp changes — Pitfall 1', () => {
    // Layer already exists
    map._layers.set('layer-dem-1-colorrelief', { id: 'layer-dem-1-colorrelief' });

    const input = makeInput({
      paint: { '_hypso-enabled': true, '_hypso-ramp': 'Inferno' },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    // removeLayer must be called BEFORE addLayer
    const removeCalls = (map.removeLayer as ReturnType<typeof vi.fn>).mock.invocationCallOrder;
    const addCalls = (map.addLayer as ReturnType<typeof vi.fn>).mock.invocationCallOrder;
    expect(removeCalls[0]).toBeLessThan(addCalls[0]);
  });

  it('color-relief-color expression uses the selected ramp', () => {
    const input = makeInput({
      paint: { '_hypso-enabled': true, '_hypso-ramp': 'Plasma' },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    const layerSpec = (map.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      paint: { 'color-relief-color': unknown[] };
    };
    const expr = layerSpec.paint['color-relief-color'];
    expect(Array.isArray(expr)).toBe(true);
    expect(expr[0]).toBe('interpolate');
    expect(expr[2]).toEqual(['elevation']);
  });

  it('defaults to Viridis ramp when _hypso-ramp is not set', () => {
    const inputWithRamp = makeInput({
      paint: { '_hypso-enabled': true, '_hypso-ramp': 'Viridis' },
      style_config: { render_mode: 'hillshade' },
    });
    const inputNoRamp = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'hillshade' },
    });

    const mapA = createMockMap();
    mapA._sources.add('source-dem-1');
    const mapB = createMockMap();
    mapB._sources.add('source-dem-1');

    syncColorReliefLayer(mapA as unknown as import('maplibre-gl').Map, inputWithRamp);
    syncColorReliefLayer(mapB as unknown as import('maplibre-gl').Map, inputNoRamp);

    const exprA = ((mapA.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      paint: { 'color-relief-color': unknown[] };
    }).paint['color-relief-color'];
    const exprB = ((mapB.addLayer as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      paint: { 'color-relief-color': unknown[] };
    }).paint['color-relief-color'];

    expect(exprA).toEqual(exprB);
  });

  it('skips add when source does not exist (defensive guard)', () => {
    // Source NOT in the set → source-less map
    map._sources.clear();

    const input = makeInput({
      paint: { '_hypso-enabled': true },
      style_config: { render_mode: 'hillshade' },
    });

    syncColorReliefLayer(map as unknown as import('maplibre-gl').Map, input);

    expect(map.addLayer).not.toHaveBeenCalled();
  });
});
