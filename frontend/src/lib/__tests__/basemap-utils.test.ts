import { describe, it, expect } from 'vitest';
import type { StyleSpecification } from 'maplibre-gl';
import {
  toMaplibreStyle,
  resolveBasemapId,
  getThemeBasemap,
  findBasemapById,
  basemapThumbnail,
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
    expect(result.glyphs).toBeDefined();
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
