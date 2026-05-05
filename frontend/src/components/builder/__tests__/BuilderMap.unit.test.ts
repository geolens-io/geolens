import {
  ensureRasterDemTerrainSource,
  getExpressionSafeOpacity,
  isTerrainCapableDemLayer,
  normalizeTerrainExaggeration,
  simplifyPaint,
  TERRAIN_SOURCE_ID,
} from '../map-sync';

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
    });

    expect(map.addSource).toHaveBeenCalledWith(TERRAIN_SOURCE_ID, {
      type: 'raster-dem',
      tiles: [`${window.location.origin}/raster-tiles/dem/tiles/{z}/{x}/{y}.png`],
      tileSize: 512,
      minzoom: 2,
      maxzoom: 14,
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
    expect(normalizeTerrainExaggeration(12)).toBe(10);
  });
});
