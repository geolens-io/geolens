import {
  applyBasemapConfigToMap,
  ensureRasterDemTerrainSource,
  getExpressionSafeOpacity,
  isTerrainCapableDemLayer,
  MAP_STACK_Z_ORDER_POLICY,
  normalizeTerrainExaggeration,
  simplifyPaint,
  TERRAIN_SOURCE_ID,
} from '../map-sync';
import { shouldSuppressBuilderMapError } from '../BuilderMap';
import { applyBasemapConfigToStyle, normalizeBasemapConfig } from '@/lib/basemap-utils';
import type { StyleSpecification } from 'maplibre-gl';

function createTerrainMap() {
  const sources = new Map<string, { type?: string; tiles?: string[]; serialize: () => { tiles?: string[] } }>();
  return {
    getSource: vi.fn((id: string) => sources.get(id)),
    addSource: vi.fn((id: string, spec: { type?: string; tiles?: string[] }) => {
      sources.set(id, { ...spec, serialize: () => spec });
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    setTerrain: vi.fn(),
  };
}

describe('simplifyPaint', () => {
  it('passes through scalar values unchanged', () => {
    expect(simplifyPaint({ 'fill-color': '#ff0000', 'fill-opacity': 0.5 })).toEqual({
      'fill-color': '#ff0000',
      'fill-opacity': 0.5,
    });
  });

  it('extracts default color (index 2) from step expressions', () => {
    const step = ['step', ['get', 'population'], '#ffffcc', 1000, '#41b6c4', 5000, '#253494'];
    expect(simplifyPaint({ 'fill-color': step })).toEqual({
      'fill-color': '#ffffcc', // default at index 2, not last element
    });
  });

  it('extracts fallback (last element) from match expressions', () => {
    const match = ['match', ['get', 'type'], 'park', '#22c55e', 'water', '#3b82f6', '#cccccc'];
    expect(simplifyPaint({ 'fill-color': match })).toEqual({
      'fill-color': '#cccccc', // fallback is last element for match
    });
  });

  it('returns undefined for short expression arrays', () => {
    expect(simplifyPaint({ 'fill-color': ['get'] })).toEqual({
      'fill-color': undefined,
    });
  });

  it('handles mixed scalar and expression values', () => {
    const step = ['step', ['get', 'val'], '#aaa', 10, '#bbb'];
    expect(simplifyPaint({ 'fill-color': step, 'fill-opacity': 0.7 })).toEqual({
      'fill-color': '#aaa',
      'fill-opacity': 0.7,
    });
  });

  it('returns undefined for expression with non-scalar default', () => {
    const expr = ['step', ['get', 'x'], ['literal', [255, 0, 0]], 10, '#bbb'];
    expect(simplifyPaint({ 'fill-color': expr })).toEqual({
      'fill-color': undefined,
    });
  });
});

describe('getExpressionSafeOpacity', () => {
  it('multiplies scalar paint opacity by master layer opacity', () => {
    expect(getExpressionSafeOpacity({ 'line-opacity': 0.5 }, 'line', 0.4)).toBe(0.2);
  });

  it('returns expression-valued paint opacity without multiplying it', () => {
    const opacityExpression = ['step', ['zoom'], 0.25, 10, 0.75];

    expect(getExpressionSafeOpacity({ 'circle-opacity': opacityExpression }, 'circle', 0.4)).toEqual(opacityExpression);
  });

  it('uses geometry defaults when paint opacity is missing', () => {
    expect(getExpressionSafeOpacity({}, 'fill', 0.5)).toBe(0.15);
  });
});

describe('terrain helpers', () => {
  it('adds raster-dem terrain sources with absolute tile URLs', () => {
    const map = createTerrainMap();

    ensureRasterDemTerrainSource(map as never, '/raster-tiles/dem/tiles/{z}/{x}/{y}.png', {
      tileSize: 512,
      minzoom: 2,
      maxzoom: 14,
      bounds: [-113, 36, -111.5, 37],
    });

    expect(map.addSource).toHaveBeenCalledWith(TERRAIN_SOURCE_ID, {
      type: 'raster-dem',
      tiles: [`${window.location.origin}/raster-tiles/dem/tiles/{z}/{x}/{y}.png`],
      tileSize: 512,
      minzoom: 2,
      maxzoom: 14,
      bounds: [-113, 36, -111.5, 37],
      encoding: 'mapbox',
    });
  });

  it('replaces an existing terrain source when the tile URL changes', () => {
    const map = createTerrainMap();

    ensureRasterDemTerrainSource(map as never, '/raster-tiles/dem-a/tiles/{z}/{x}/{y}.png');
    ensureRasterDemTerrainSource(map as never, '/raster-tiles/dem-b/tiles/{z}/{x}/{y}.png');

    expect(map.setTerrain).toHaveBeenCalledWith(null);
    expect(map.removeSource).toHaveBeenCalledWith(TERRAIN_SOURCE_ID);
    expect(map.addSource).toHaveBeenLastCalledWith(TERRAIN_SOURCE_ID, expect.objectContaining({
      tiles: [`${window.location.origin}/raster-tiles/dem-b/tiles/{z}/{x}/{y}.png`],
    }));
  });

  it('identifies terrain-capable DEM rasters and clamps exaggeration', () => {
    expect(isTerrainCapableDemLayer({ is_dem: true, dataset_record_type: 'raster_dataset' })).toBe(true);
    expect(isTerrainCapableDemLayer({ is_dem: true, dataset_record_type: 'vrt_dataset' })).toBe(true);
    expect(isTerrainCapableDemLayer({ is_dem: true, dataset_record_type: 'vector_dataset' })).toBe(false);

    expect(normalizeTerrainExaggeration(undefined)).toBe(1);
    expect(normalizeTerrainExaggeration(-2)).toBe(0);
    expect(normalizeTerrainExaggeration(2.5)).toBe(2.5);
    expect(normalizeTerrainExaggeration(12)).toBe(3);
  });
});

describe('builder map error hygiene', () => {
  it('suppresses transient internal terrain source errors', () => {
    expect(shouldSuppressBuilderMapError({
      message: `Source "${TERRAIN_SOURCE_ID}" not found for terrain`,
    })).toBe(true);
    expect(shouldSuppressBuilderMapError({
      message: 'DEM dimension mismatch while decoding raster-dem tile',
    })).toBe(true);
  });

  it('does not suppress HTTP tile errors', () => {
    expect(shouldSuppressBuilderMapError({
      message: 'Tile server unavailable',
      status: 503,
    })).toBe(false);
  });
});

describe('basemap appearance helpers', () => {
  const style: StyleSpecification = {
    version: 8,
    sources: {
      basemap: { type: 'vector', tiles: [] },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#ffffff' } },
      { id: 'water-fill', type: 'fill', source: 'basemap', 'source-layer': 'water', paint: { 'fill-color': '#aadaff' } },
      { id: 'road-primary', type: 'line', source: 'basemap', 'source-layer': 'roads', paint: { 'line-opacity': 1 } },
      { id: 'admin-boundary', type: 'line', source: 'basemap', 'source-layer': 'boundary', paint: { 'line-opacity': 1 } },
      { id: 'building-3d', type: 'fill-extrusion', source: 'basemap', 'source-layer': 'building', paint: {} },
      { id: 'place-label', type: 'symbol', source: 'basemap', 'source-layer': 'place_label', layout: { 'text-field': ['get', 'name'] }, paint: { 'text-opacity': 1 } },
    ],
  };

  it('normalizes missing configs to the legacy label toggle behavior', () => {
    expect(normalizeBasemapConfig(null, false)).toMatchObject({
      label_mode: 'hidden',
      road_visibility: 'full',
      building_visibility: true,
    });
  });

  it('applies curated layer visibility and tone changes to supported style layers', () => {
    const next = applyBasemapConfigToStyle(style, {
      label_mode: 'subtle',
      road_visibility: 'hidden',
      boundary_visibility: 'subtle',
      building_visibility: false,
      land_water_tone: 'monochrome',
      relief_contrast: null,
    });
    const byId = new Map(next.layers.map((layer) => [layer.id, layer]));

    expect(byId.get('water-fill')).toMatchObject({
      paint: expect.objectContaining({ 'fill-color': '#d9dde0' }),
    });
    expect(byId.get('road-primary')).toMatchObject({
      layout: expect.objectContaining({ visibility: 'none' }),
    });
    expect(byId.get('admin-boundary')).toMatchObject({
      paint: expect.objectContaining({ 'line-opacity': 0.4 }),
    });
    expect(byId.get('building-3d')).toMatchObject({
      layout: expect.objectContaining({ visibility: 'none' }),
    });
    expect(byId.get('place-label')).toMatchObject({
      paint: expect.objectContaining({ 'text-opacity': 0.55 }),
    });
  });

  it('applies basemap config to loaded map styles without touching managed data layers', () => {
    const loadedStyle: StyleSpecification = {
      ...style,
      sources: {
        ...style.sources,
        'source-user-roads': { type: 'vector', tiles: [] },
      },
      layers: [
        ...style.layers,
        { id: 'layer-user-roads', type: 'line', source: 'source-user-roads', 'source-layer': 'data.roads', paint: { 'line-opacity': 1 } },
      ],
    };
    const map = {
      getStyle: vi.fn(() => loadedStyle),
      getLayer: vi.fn((id: string) => loadedStyle.layers.some((layer) => layer.id === id)),
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
    };

    applyBasemapConfigToMap(map as never, {
      label_mode: 'hidden',
      road_visibility: 'subtle',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'muted',
      relief_contrast: null,
    });

    expect(map.setLayoutProperty).toHaveBeenCalledWith('place-label', 'visibility', 'none');
    expect(map.setPaintProperty).toHaveBeenCalledWith('road-primary', 'line-opacity', 0.35);
    expect(map.setPaintProperty).not.toHaveBeenCalledWith('layer-user-roads', 'line-opacity', expect.anything());
  });

  it('documents the map stack z-order policy', () => {
    expect(MAP_STACK_Z_ORDER_POLICY).toEqual([
      'surface terrain',
      'basemap relief and detail',
      'user data geometry',
      'basemap labels',
      'user data labels',
    ]);
  });
});
