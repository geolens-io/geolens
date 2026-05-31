import { describe, expect, it } from 'vitest';
import { normalizeLayerStyleState, normalizeStyleConfig, RENDER_MODES } from '../normalize-style-config';

describe('normalizeLayerStyleState', () => {
  it('moves legacy builder paint metadata into style_config.builder and returns clean paint', () => {
    const normalized = normalizeLayerStyleState(
      { mode: 'graduated', column: 'pop', ramp: 'YlOrRd' },
      {
        'fill-color': '#123456',
        'fill-opacity': 0,
        '_fill-disabled': true,
        '_fill-opacity-saved': 0.42,
        '_stroke-disabled': true,
        '_outline-color': '#abcdef',
        '_outline-width': 0,
        '_outline-width-saved': 2,
        '_height_column': 'height_m',
      },
      'Polygon',
    );

    expect(normalized.paint).toEqual({
      'fill-color': '#123456',
      'fill-opacity': 0,
    });
    expect(normalized.style_config?.builder).toEqual({
      fillDisabled: true,
      fillOpacitySaved: 0.42,
      strokeDisabled: true,
      outlineColor: '#abcdef',
      outlineWidth: 0,
      outlineWidthSaved: 2,
      heightColumn: 'height_m',
    });
  });

  it('hydrates builder-only style config when legacy responses have no data-driven config', () => {
    const normalized = normalizeLayerStyleState(
      null,
      {
        'circle-color': '#ff0000',
        '_stroke-disabled': true,
        '_outline-width-saved': 3,
      },
      'Point',
    );

    expect(normalized.paint).toEqual({ 'circle-color': '#ff0000' });
    expect(normalized.style_config).toEqual({
      builder: {
        strokeDisabled: true,
        outlineWidthSaved: 3,
      },
    });
  });

  it('normalizes legacy heatmap metadata without keeping private paint keys', () => {
    const normalized = normalizeLayerStyleState(
      { render_mode: 'heatmap', ramp: 'Viridis', weight_column: 'count' },
      {
        'heatmap-radius': 24,
        '_heatmap-ramp': 'Blues',
        '_heatmap-weight-column': 'density',
      },
      'Point',
    );

    expect(normalized.paint).toEqual({ 'heatmap-radius': 24 });
    expect(normalized.style_config).toMatchObject({
      render_mode: 'heatmap',
      builder: {
        heatmapRamp: 'Blues',
        heatmapWeightColumn: 'density',
      },
    });
  });

  it('preserves render-mode-only style configs for DEM/raster adapters', () => {
    const normalized = normalizeLayerStyleState(
      { render_mode: 'hillshade' },
      {},
      null,
    );

    expect(normalized.paint).toEqual({});
    expect(normalized.style_config).toEqual({ render_mode: 'hillshade' });
  });

  it('promotes legacy nested builder render_mode and drops it from builder metadata', () => {
    const normalized = normalizeLayerStyleState(
      {
        builder: {
          render_mode: 'hillshade',
          outline_color: '#1d4ed8',
          outline_width: 2,
        },
      },
      {},
      null,
    );

    expect(normalized.style_config).toEqual({
      render_mode: 'hillshade',
      builder: {
        outlineColor: '#1d4ed8',
        outlineWidth: 2,
      },
    });
  });

  it('preserves render_mode terrain for DEM/raster adapters', () => {
    const normalized = normalizeLayerStyleState(
      { render_mode: 'terrain' },
      {},
      null,
    );

    expect(normalized.paint).toEqual({});
    expect(normalized.style_config).toEqual({ render_mode: 'terrain' });
  });

  it('preserves render_mode image for DEM/raster adapters', () => {
    const normalized = normalizeLayerStyleState(
      { render_mode: 'image' },
      {},
      null,
    );

    expect(normalized.paint).toEqual({});
    expect(normalized.style_config).toEqual({ render_mode: 'image' });
  });
});

describe('RENDER_MODES allowlist', () => {
  it('contains all editor-emittable modes', () => {
    const expected = ['heatmap', 'hillshade', 'symbol', 'arrow', 'cluster', 'terrain', 'image'];
    for (const mode of expected) {
      expect(RENDER_MODES, `RENDER_MODES should contain '${mode}'`).toContain(mode);
    }
  });
});

describe('normalizeStyleConfig', () => {
  it('preserves existing builder config while extracting data-driven expressions', () => {
    const config = normalizeStyleConfig(
      {
        mode: 'graduated',
        column: 'pop',
        ramp: 'YlOrRd',
        builder: { outlineColor: '#111111', outlineWidth: 2 },
      },
      {
        'fill-color': ['step', ['get', 'pop'], '#fee', 10, '#f00'],
      },
      'Polygon',
    );

    expect(config?.colors).toEqual(['#fee', '#f00']);
    expect(config?.breaks).toEqual([10]);
    expect(config?.builder).toEqual({ outlineColor: '#111111', outlineWidth: 2 });
  });

  it('canonicalizes legacy snake_case builder keys before map rendering', () => {
    const config = normalizeStyleConfig(
      {
        mode: 'categorical',
        column: 'fire_year',
        ramp: 'Custom',
        builder: {
          outline_color: '#ffcf66',
          outline_width: 0.25,
          height_column: 'height_m',
          height_scale: 1.8,
          extrusion_min_zoom: 12.5,
          extrusion_opacity: 0.92,
          arrow_color: '#112233',
          arrow_size: 16,
          arrow_spacing: 96,
          cluster_radius: 44,
          cluster_max_zoom: 13,
          cluster_color: '#1d4ed8',
          cluster_text_color: '#ffffff',
          cluster_text_size: 13,
        },
      },
      { 'fill-color': '#b30000' },
      'Polygon',
    );

    expect(config?.builder).toEqual({
      outlineColor: '#ffcf66',
      outlineWidth: 0.25,
      heightColumn: 'height_m',
      heightScale: 1.8,
      extrusionMinZoom: 12.5,
      extrusionOpacity: 0.92,
      arrowColor: '#112233',
      arrowSize: 16,
      arrowSpacing: 96,
      clusterRadius: 44,
      clusterMaxZoom: 13,
      clusterColor: '#1d4ed8',
      clusterTextColor: '#ffffff',
      clusterTextSize: 13,
    });
  });
});

describe('normalizeLayerStyleState — raster stretch/colormap round-trip (v1034)', () => {
  it('re-injects builder colormap/stretch/pmin/pmax/sigma back onto paint on load', () => {
    // Simulates a layer loaded from the backend: clean paint + builder-stored keys.
    const { paint, style_config } = normalizeLayerStyleState(
      { builder: { colormap: 'viridis', stretch: 'percentile', pmin: 5, pmax: 95, sigma: 3 } },
      { 'raster-opacity': 1 },
      null,
    );
    expect(paint._colormap).toBe('viridis');
    expect(paint._stretch).toBe('percentile');
    expect(paint._pmin).toBe(5);
    expect(paint._pmax).toBe(95);
    expect(paint._sigma).toBe(3);
    // The builder values survive in style_config too.
    expect(style_config?.builder?.colormap).toBe('viridis');
    expect(style_config?.builder?.pmin).toBe(5);
  });

  it('leaves paint untouched when no raster builder keys are present', () => {
    const { paint } = normalizeLayerStyleState(null, { 'raster-opacity': 0.5 }, null);
    expect(paint).toEqual({ 'raster-opacity': 0.5 });
    expect('_colormap' in paint).toBe(false);
  });

  it('B-011: re-injects DEM hypso (color-relief) builder keys back onto paint on load', () => {
    // A DEM layer loaded from the backend: clean paint + builder-stored hypso keys.
    const { paint, style_config } = normalizeLayerStyleState(
      { builder: { hypso_enabled: true, hypso_ramp: 'Inferno' } },
      { 'raster-opacity': 1 },
      null,
    );
    expect(paint['_hypso-enabled']).toBe(true);
    expect(paint['_hypso-ramp']).toBe('Inferno');
    // The builder values survive in style_config too.
    expect(style_config?.builder?.hypso_enabled).toBe(true);
    expect(style_config?.builder?.hypso_ramp).toBe('Inferno');
  });
});
