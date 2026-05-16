import { describe, it, expect } from 'vitest';
import type { StyleSpecification } from 'maplibre-gl';
import {
  toMaplibreStyle,
  sanitizeMaplibreStyle,
  resolveBasemapId,
  getThemeBasemap,
  findBasemapById,
  basemapThumbnail,
  applyBasemapConfigToStyle,
  LIGHT_PRESET_ID,
  DARK_PRESET_ID,
  BLANK_BASEMAP_ID,
} from '../basemap-utils';
import type { BasemapEntry } from '@/api/settings';

describe('toMaplibreStyle', () => {
  it('returns GL style JSON URL as-is', () => {
    const url = 'https://example.com/style.json';
    expect(toMaplibreStyle(url)).toBe(url);
  });

  it('ignores attribution for GL style JSON URLs', () => {
    const url = 'https://example.com/style.json';
    expect(toMaplibreStyle(url, '© Example')).toBe(url);
  });

  it('returns /styles/ URL as-is (GL style without .json extension)', () => {
    const url = 'https://tiles.openfreemap.org/styles/bright';
    expect(toMaplibreStyle(url)).toBe(url);
  });

  it('returns MapTiler style.json URL with query params as-is', () => {
    const url = 'https://api.maptiler.com/maps/streets-v2/style.json?key=abc123';
    expect(toMaplibreStyle(url)).toBe(url);
  });

  it('returns Mapbox /styles/ URL with query params as-is', () => {
    const url = 'https://api.mapbox.com/styles/v1/mapbox/streets-v12?access_token=pk.test';
    expect(toMaplibreStyle(url)).toBe(url);
  });

  it('wraps XYZ URL in StyleSpecification', () => {
    const url = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
    const result = toMaplibreStyle(url) as StyleSpecification;
    expect(result.version).toBe(8);
    expect(result.sources.basemap).toEqual({
      type: 'raster',
      tiles: [url],
      tileSize: 256,
    });
    expect(result.layers).toHaveLength(1);
    expect(result.layers[0]).toMatchObject({
      id: 'basemap-tiles',
      type: 'raster',
      source: 'basemap',
    });
  });

  it('includes attribution on raster source when provided', () => {
    const url = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
    const attribution = '© OpenStreetMap contributors';
    const result = toMaplibreStyle(url, attribution) as StyleSpecification;
    expect((result.sources.basemap as Record<string, unknown>).attribution).toBe(attribution);
  });

  it('omits attribution on raster source when not provided', () => {
    const url = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
    const result = toMaplibreStyle(url) as StyleSpecification;
    expect((result.sources.basemap as Record<string, unknown>).attribution).toBeUndefined();
  });

  it('includes glyphs URL for raster basemaps', () => {
    const url = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
    const result = toMaplibreStyle(url) as StyleSpecification;
    expect(result.glyphs).toBeDefined();
  });
});

describe('sanitizeMaplibreStyle', () => {
  it('removes unsupported fill-pattern references from remote styles', () => {
    const style = {
      version: 8,
      sources: {},
      layers: [
        {
          id: 'landcover_wood',
          type: 'fill',
          paint: {
            'fill-color': '#222',
            'fill-pattern': 'wood-pattern',
            'fill-opacity': 0.8,
          },
        },
        {
          id: 'background',
          type: 'background',
          paint: { 'background-color': '#111' },
        },
      ],
    } as StyleSpecification;

    const result = sanitizeMaplibreStyle(style);

    expect(result.layers[0]).toMatchObject({
      id: 'landcover_wood',
      paint: {
        'fill-color': '#222',
        'fill-opacity': 0.8,
      },
    });
    expect(result.layers[0].paint).not.toHaveProperty('fill-pattern');
    expect(result.layers[1]).toBe(style.layers[1]);
  });

  it('removes known missing icon-image references from remote styles', () => {
    const style = {
      version: 8,
      sources: {
        openmaptiles: {
          type: 'vector',
          tiles: ['https://example.com/{z}/{x}/{y}.pbf'],
        },
      },
      layers: [
        {
          id: 'place_city',
          type: 'symbol',
          source: 'openmaptiles',
          'source-layer': 'place',
          layout: {
            'icon-image': ['step', ['zoom'], 'circle-11', 9, ''],
            'text-field': ['get', 'name'],
          },
        },
      ],
    } as StyleSpecification;

    const result = sanitizeMaplibreStyle(style);

    expect(result.layers[0]).toMatchObject({
      id: 'place_city',
      layout: {
        'icon-image': ['step', ['zoom'], '', 9, ''],
        'text-field': ['get', 'name'],
      },
    });
  });

  it('wraps remote style numeric filters so null feature values do not warn', () => {
    const style = {
      version: 8,
      sources: {
        openmaptiles: {
          type: 'vector',
          tiles: ['https://example.com/{z}/{x}/{y}.pbf'],
        },
      },
      layers: [
        {
          id: 'boundary_3',
          type: 'line',
          source: 'openmaptiles',
          'source-layer': 'boundary',
          filter: ['all', ['>=', ['get', 'admin_level'], 3], ['<=', ['get', 'admin_level'], 6]],
          paint: { 'line-color': '#aaa' },
        },
      ],
    } as StyleSpecification;

    const result = sanitizeMaplibreStyle(style);
    const layer = result.layers[0] as StyleSpecification['layers'][number] & { filter?: unknown };

    expect(layer.filter).toEqual([
      'all',
      ['>=', ['to-number', ['get', 'admin_level'], -1_000_000_000_000], 3],
      ['<=', ['to-number', ['get', 'admin_level'], 1_000_000_000_000], 6],
    ]);
  });
});

describe('BLANK_BASEMAP_ID', () => {
  it('toMaplibreStyle returns a StyleSpecification with transparent background for blank ID', () => {
    const result = toMaplibreStyle(BLANK_BASEMAP_ID) as StyleSpecification;
    expect(result.version).toBe(8);
    expect(result.sources).toEqual({});
    expect(result.layers).toHaveLength(1);
    expect(result.layers[0]).toMatchObject({
      id: 'background',
      type: 'background',
      paint: { 'background-color': 'rgba(0,0,0,0)' },
    });
    // Blank basemap intentionally omits glyphs — no text layers, avoids CORS errors
    expect(result.glyphs).toBeUndefined();
  });

  it('toMaplibreStyle blank ignores attribution param', () => {
    const result = toMaplibreStyle(BLANK_BASEMAP_ID, '© Example') as StyleSpecification;
    expect(result.version).toBe(8);
    expect(result.sources).toEqual({});
  });

  it('basemapThumbnail returns a defined string for blank ID', () => {
    expect(basemapThumbnail(BLANK_BASEMAP_ID)).toBeDefined();
    expect(typeof basemapThumbnail(BLANK_BASEMAP_ID)).toBe('string');
    expect(basemapThumbnail(BLANK_BASEMAP_ID).length).toBeGreaterThan(0);
  });
});

describe('resolveBasemapId', () => {
  it('maps legacy "positron" to openfreemap-positron', () => {
    expect(resolveBasemapId('positron')).toBe('openfreemap-positron');
  });

  it('maps legacy "dark-matter" to openfreemap-dark', () => {
    expect(resolveBasemapId('dark-matter')).toBe('openfreemap-dark');
  });

  it('maps legacy "voyager" to openfreemap-positron', () => {
    expect(resolveBasemapId('voyager')).toBe('openfreemap-positron');
  });

  it('maps legacy "carto-positron" to openfreemap-positron', () => {
    expect(resolveBasemapId('carto-positron')).toBe('openfreemap-positron');
  });

  it('maps legacy "carto-dark-matter" to openfreemap-dark', () => {
    expect(resolveBasemapId('carto-dark-matter')).toBe('openfreemap-dark');
  });

  it('passes through openfreemap-positron as-is', () => {
    expect(resolveBasemapId('openfreemap-positron')).toBe('openfreemap-positron');
  });

  it('returns non-legacy keys unchanged', () => {
    expect(resolveBasemapId('openstreetmap')).toBe('openstreetmap');
    expect(resolveBasemapId('custom-123')).toBe('custom-123');
  });
});

describe('getThemeBasemap', () => {
  const basemaps: BasemapEntry[] = [
    { id: LIGHT_PRESET_ID, label: 'Light', url: 'https://tiles.openfreemap.org/styles/positron', enabled: true, is_preset: true },
    { id: DARK_PRESET_ID, label: 'Dark', url: 'https://tiles.openfreemap.org/styles/dark', enabled: true, is_preset: true },
    { id: 'osm', label: 'OSM', url: 'https://tile.osm.org/{z}/{x}/{y}.png', enabled: true, is_preset: true },
  ];

  it('returns light preset for light theme', () => {
    expect(getThemeBasemap(basemaps, 'light')?.id).toBe(LIGHT_PRESET_ID);
  });

  it('returns dark preset for dark theme', () => {
    expect(getThemeBasemap(basemaps, 'dark')?.id).toBe(DARK_PRESET_ID);
  });

  it('falls back to first enabled basemap when preferred is disabled', () => {
    const noDark = basemaps.map((b) =>
      b.id === DARK_PRESET_ID ? { ...b, enabled: false } : b,
    );
    expect(getThemeBasemap(noDark, 'dark')?.id).toBe(LIGHT_PRESET_ID);
  });

  it('returns undefined when no basemaps are enabled', () => {
    const allDisabled = basemaps.map((b) => ({ ...b, enabled: false }));
    expect(getThemeBasemap(allDisabled, 'light')).toBeUndefined();
  });

  it('returns undefined for empty array', () => {
    expect(getThemeBasemap([], 'light')).toBeUndefined();
  });
});

describe('findBasemapById', () => {
  const basemaps: BasemapEntry[] = [
    { id: 'openfreemap-positron', label: 'OpenFreeMap Positron', url: 'https://tiles.openfreemap.org/styles/positron', enabled: true, is_preset: true },
    { id: 'openfreemap-dark', label: 'OpenFreeMap Dark', url: 'https://tiles.openfreemap.org/styles/dark', enabled: true, is_preset: true },
    { id: 'custom-1', label: 'Custom', url: 'https://tiles.example.com/{z}/{x}/{y}.png', enabled: true, is_preset: false },
  ];

  it('finds by exact id', () => {
    expect(findBasemapById(basemaps, 'custom-1')?.label).toBe('Custom');
  });

  it('finds by legacy key "positron"', () => {
    expect(findBasemapById(basemaps, 'positron')?.id).toBe('openfreemap-positron');
  });

  it('finds by legacy key "carto-positron"', () => {
    expect(findBasemapById(basemaps, 'carto-positron')?.id).toBe('openfreemap-positron');
  });

  it('finds by legacy key "carto-dark-matter"', () => {
    expect(findBasemapById(basemaps, 'carto-dark-matter')?.id).toBe('openfreemap-dark');
  });

  it('returns undefined for unknown id', () => {
    expect(findBasemapById(basemaps, 'nonexistent')).toBeUndefined();
  });
});

describe('preset IDs', () => {
  it('LIGHT_PRESET_ID is openfreemap-positron', () => {
    expect(LIGHT_PRESET_ID).toBe('openfreemap-positron');
  });

  it('DARK_PRESET_ID is openfreemap-dark', () => {
    expect(DARK_PRESET_ID).toBe('openfreemap-dark');
  });
});

describe('applyBasemapConfigToStyle master opacity', () => {
  it('multiplies raster-opacity on raster basemap layers by config.opacity', () => {
    const style: StyleSpecification = {
      version: 8,
      sources: { osm: { type: 'raster', tiles: ['x'], tileSize: 256 } },
      layers: [
        { id: 'osm', type: 'raster', source: 'osm' },
      ],
    };
    const next = applyBasemapConfigToStyle(style, { opacity: 0.55 });
    const layer = next.layers[0] as unknown as { paint: { 'raster-opacity': number } };
    expect(layer.paint['raster-opacity']).toBeCloseTo(0.55, 5);
  });

  it('multiplies existing line-opacity by config.opacity (compose with applyProminence)', () => {
    const style: StyleSpecification = {
      version: 8,
      sources: { v: { type: 'vector', tiles: ['x'] } },
      layers: [
        {
          id: 'road-primary',
          type: 'line',
          source: 'v',
          'source-layer': 'transportation',
          paint: { 'line-opacity': 1 },
        },
      ],
    };
    const next = applyBasemapConfigToStyle(style, {
      road_visibility: 'subtle',
      opacity: 0.5,
    });
    const layer = next.layers[0] as unknown as { paint: { 'line-opacity': number } };
    // applyProminence writes line-opacity = 0.35 for subtle roads;
    // master opacity 0.5 multiplies to 0.175.
    expect(layer.paint['line-opacity']).toBeCloseTo(0.175, 5);
  });

  it('opacity=1 is a no-op (paint unchanged for raster)', () => {
    const style: StyleSpecification = {
      version: 8,
      sources: { osm: { type: 'raster', tiles: ['x'], tileSize: 256 } },
      layers: [{ id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': 0.8 } }],
    };
    const next = applyBasemapConfigToStyle(style, { opacity: 1 });
    const layer = next.layers[0] as unknown as { paint: { 'raster-opacity': number } };
    expect(layer.paint['raster-opacity']).toBe(0.8);
  });

  it('leaves expression-valued *-opacity untouched (no AST surgery)', () => {
    const expression = ['interpolate', ['linear'], ['zoom'], 0, 0.2, 14, 0.8] as unknown as number;
    const style: StyleSpecification = {
      version: 8,
      sources: { osm: { type: 'raster', tiles: ['x'], tileSize: 256 } },
      layers: [
        { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': expression } },
      ],
    };
    const next = applyBasemapConfigToStyle(style, { opacity: 0.5 });
    const layer = next.layers[0] as unknown as { paint: { 'raster-opacity': unknown } };
    expect(layer.paint['raster-opacity']).toEqual(expression);
  });
});
