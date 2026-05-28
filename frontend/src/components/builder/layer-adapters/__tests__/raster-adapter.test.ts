import { describe, it, expect, vi } from 'vitest';
import { rasterAdapter } from '../raster-adapter';
import type { AdapterLayerInput } from '../types';

/**
 * WALK-R-05 regression tests — split source-guard from layer-guard in addLayers.
 *
 * Prior to this fix, `addLayers` had a single early-return: `if (map.getSource(sourceId)) return`.
 * This prevented re-adding the layer when a style swap removes layers but keeps sources,
 * causing blank tiles on basemap reload.
 *
 * Fix: split into two independent guards:
 *   - `if (!map.getSource(sourceId)) map.addSource(...)`
 *   - `if (map.getLayer(layerId)) return`
 *   - then `map.addLayer(...)`
 */

interface AddLayerCall {
  id: string;
  layout?: { visibility?: string };
  paint?: Record<string, unknown>;
}

function createMockMap(opts: { sourceExists?: boolean; layerExists?: boolean } = {}) {
  const { sourceExists = false, layerExists = false } = opts;
  return {
    getSource: vi.fn().mockReturnValue(sourceExists ? { type: 'raster' } : null),
    getLayer: vi.fn().mockReturnValue(layerExists ? { id: 'mock-layer' } : undefined),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getPaintProperty: vi.fn().mockReturnValue(undefined),
    setPaintProperty: vi.fn(),
    getLayoutProperty: vi.fn().mockReturnValue(undefined),
    setLayoutProperty: vi.fn(),
  };
}

function makeInput(overrides: Partial<AdapterLayerInput> = {}): AdapterLayerInput {
  return {
    id: 'layer-1',
    dataset_table_name: 'ds_1',
    dataset_geometry_type: null,
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    sourceId: 'source-raster-1',
    layerId: 'layer-raster-1',
    sourceLayer: '',
    // sourceType intentionally omitted — raster layers are not vector/geojson
    tileUrl: '/api/tiles/{z}/{x}/{y}',
    tileSize: 256,
    minzoom: 0,
    maxzoom: 18,
    ...overrides,
  };
}

describe('raster-adapter addLayers — WALK-R-05 split-guard', () => {
  it('Test 1: cold add (source missing, layer missing) — calls addSource AND addLayer', () => {
    const map = createMockMap({ sourceExists: false, layerExists: false });
    rasterAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput());

    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.addLayer).toHaveBeenCalledTimes(1);
  });

  it('Test 2: WALK-R-05 source-exists/layer-missing — addSource NOT called, addLayer IS called', () => {
    const map = createMockMap({ sourceExists: true, layerExists: false });
    rasterAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput());

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).toHaveBeenCalledTimes(1);
  });

  it('Test 3: source-exists AND layer-exists — no-op (neither addSource nor addLayer called)', () => {
    const map = createMockMap({ sourceExists: true, layerExists: true });
    rasterAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput());

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
  });

  it('Test 4: visible=false — addLayer receives layout.visibility === "none"', () => {
    const map = createMockMap({ sourceExists: false, layerExists: false });
    rasterAdapter.addLayers(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.addLayer).toHaveBeenCalledTimes(1);
    const call = map.addLayer.mock.calls[0][0] as AddLayerCall;
    expect(call.layout?.visibility).toBe('none');
  });

  it('Test 5: syncPaint with existing layer — routes through RASTER_PAINT_PROPERTIES (smoke)', () => {
    const map = createMockMap({ sourceExists: true, layerExists: true });
    // Provide a known raster paint value
    rasterAdapter.syncPaint(map as unknown as import('maplibre-gl').Map, makeInput({
      paint: { 'raster-brightness-min': 0.2 },
      opacity: 0.9,
    }));
    // setPaintProperty must have been invoked at least once (opacity path)
    expect(map.setPaintProperty).toHaveBeenCalled();
  });

  it('Test 6: syncVisibility(visible=false) — calls setLayoutProperty with "none"', () => {
    const map = createMockMap({ sourceExists: true, layerExists: true });
    rasterAdapter.syncVisibility(map as unknown as import('maplibre-gl').Map, makeInput({ visible: false }));

    expect(map.setLayoutProperty).toHaveBeenCalledWith('layer-raster-1', 'visibility', 'none');
  });

  it('Test 7: getLayerIds returns [layerId]', () => {
    const ids = rasterAdapter.getLayerIds('my-raster-layer');
    expect(ids).toEqual(['my-raster-layer']);
  });
});

describe('RASTER_OWNED_PAINT_PROPERTIES export', () => {
  it('exports exactly the 4 user-facing raster paint property keys in canonical order', async () => {
    const { RASTER_OWNED_PAINT_PROPERTIES } = await import('../raster-adapter');
    expect(RASTER_OWNED_PAINT_PROPERTIES).toEqual([
      'raster-brightness-min',
      'raster-contrast',
      'raster-saturation',
      'raster-hue-rotate',
    ]);
  });

  it('does NOT include raster-brightness-max, raster-resampling, raster-fade-duration, or raster-opacity', async () => {
    const { RASTER_OWNED_PAINT_PROPERTIES } = await import('../raster-adapter');
    const forbidden = ['raster-brightness-max', 'raster-resampling', 'raster-fade-duration', 'raster-opacity'];
    for (const key of forbidden) {
      expect(RASTER_OWNED_PAINT_PROPERTIES as readonly string[]).not.toContain(key);
    }
  });

  it('Pitfall 6: does NOT include _colormap or _stretch (builder-private keys must never reach setPaintProperty)', async () => {
    const { RASTER_OWNED_PAINT_PROPERTIES } = await import('../raster-adapter');
    expect(RASTER_OWNED_PAINT_PROPERTIES as readonly string[]).not.toContain('_colormap');
    expect(RASTER_OWNED_PAINT_PROPERTIES as readonly string[]).not.toContain('_stretch');
  });
});

describe('buildColormapTileUrl', () => {
  let buildColormapTileUrl: (baseUrl: string, paint: Record<string, unknown>) => string;

  beforeEach(async () => {
    // Use dynamic import so vi.resetModules() in other tests doesn't pollute
    ({ buildColormapTileUrl } = await import('../raster-adapter'));
  });

  const BASE = '/api/raster-tiles/abc/tiles/{z}/{x}/{y}.png';

  it('appends colormap_name for a non-gray colormap', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis' });
    expect(result).toBe(`${BASE}?colormap_name=viridis`);
  });

  it('appends both colormap_name and stretch when stretch is non-minmax', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis', _stretch: 'percentile' });
    expect(result).toContain('colormap_name=viridis');
    expect(result).toContain('stretch=percentile');
    expect(result.startsWith(BASE)).toBe(true);
  });

  it('returns base URL unchanged for gray colormap (Titiler single-band default)', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'gray' });
    expect(result).toBe(BASE);
  });

  it('returns base URL unchanged when paint is empty', () => {
    const result = buildColormapTileUrl(BASE, {});
    expect(result).toBe(BASE);
  });

  it('returns base URL unchanged when _colormap is undefined', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: undefined });
    expect(result).toBe(BASE);
  });

  it('appends colormap_name only (no stretch param) when _stretch is minmax', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis', _stretch: 'minmax' });
    expect(result).toContain('colormap_name=viridis');
    expect(result).not.toContain('stretch=');
  });

  it('appends stretch param for stddev (helper is robust to any non-minmax stretch)', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'inferno', _stretch: 'stddev' });
    expect(result).toContain('colormap_name=inferno');
    expect(result).toContain('stretch=stddev');
  });

  it('absolutize+colormap composition yields a well-formed origin/path?colormap_name=... URL', () => {
    // Simulate what absolutizeTileUrl would produce when origin is available
    const relative = '/api/raster-tiles/abc/tiles/{z}/{x}/{y}.png';
    const withColormap = buildColormapTileUrl(relative, { _colormap: 'plasma' });
    // Should still be a valid relative URL with single ? separator
    expect(withColormap).toBe(`${relative}?colormap_name=plasma`);
    // When prefixed with an origin, the result is well-formed
    const absolutized = `https://example.com${withColormap}`;
    expect(absolutized).toBe('https://example.com/api/raster-tiles/abc/tiles/{z}/{x}/{y}.png?colormap_name=plasma');
  });
});
