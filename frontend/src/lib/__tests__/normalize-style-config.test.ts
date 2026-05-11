import { describe, expect, it } from 'vitest';
import { normalizeLayerStyleState, normalizeStyleConfig } from '../normalize-style-config';

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
    });
  });
});
