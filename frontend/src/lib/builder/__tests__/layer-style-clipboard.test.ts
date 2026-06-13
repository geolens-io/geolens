/**
 * Phase 1201-01 (ENH-02/ENH-03) — pure layer-style-clipboard helper tests.
 *
 * Covers:
 *  - geometryClass derivation from dataset_geometry_type
 *  - extractCopyableStyle deep-clones paint + style_config, strips identity fields
 *  - isStyleCompatible same-class true / cross-class false / 'other' false
 *  - applyCopiedStyleToLayer is pure (no source mutation), merges paint + replaces
 *    style_config, never carries identity fields into the target
 *  - polygon→polygon round-trip preserves categories + colors + breaks
 */

import { describe, it, expect } from 'vitest';
import {
  extractCopyableStyle,
  isStyleCompatible,
  applyCopiedStyleToLayer,
  type CopiedStyle,
} from '@/lib/builder/layer-style-clipboard';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'My Layer',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
  };
}

describe('layer-style-clipboard — extractCopyableStyle / geometryClass', () => {
  it('derives polygon geometryClass for Polygon and MultiPolygon', () => {
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: 'Polygon' })).geometryClass).toBe('polygon');
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: 'MultiPolygon' })).geometryClass).toBe('polygon');
  });

  it('derives line geometryClass for LineString and MultiLineString', () => {
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: 'LineString' })).geometryClass).toBe('line');
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: 'MultiLineString' })).geometryClass).toBe('line');
  });

  it('derives point geometryClass for Point and MultiPoint', () => {
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: 'Point' })).geometryClass).toBe('point');
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: 'MultiPoint' })).geometryClass).toBe('point');
  });

  it("derives 'other' geometryClass for raster / null geometry", () => {
    expect(extractCopyableStyle(makeLayer({ dataset_geometry_type: null })).geometryClass).toBe('other');
  });

  it('deep-clones paint so mutating the copy does not affect the source layer', () => {
    const layer = makeLayer({ paint: { 'fill-color': '#abc', 'fill-opacity': 0.5 } });
    const copied = extractCopyableStyle(layer);
    (copied.paint as Record<string, unknown>)['fill-color'] = '#000';
    expect(layer.paint['fill-color']).toBe('#abc');
  });

  it('deep-clones style_config (categories/colors/breaks preserved, not aliased)', () => {
    const styleConfig: StyleConfig = {
      mode: 'categorical',
      column: 'kind',
      ramp: 'Viridis',
      categories: [
        { value: 'a', color: '#ff0000' },
        { value: 'b', color: '#00ff00' },
      ],
      breaks: [1, 2, 3],
      colors: ['#111', '#222', '#333'],
      method: 'quantile',
      classCount: 3,
    };
    const layer = makeLayer({ style_config: styleConfig });
    const copied = extractCopyableStyle(layer);
    expect(copied.style_config).toEqual(styleConfig);
    // mutate the copy — source untouched
    (copied.style_config!.categories as Array<{ color: string }>)[0].color = '#changed';
    expect(layer.style_config!.categories![0].color).toBe('#ff0000');
  });

  it('does NOT carry layer-identity fields onto the copied payload', () => {
    const copied = extractCopyableStyle(makeLayer({ id: 'src', dataset_id: 'dsX', display_name: 'Named' }));
    expect((copied as unknown as Record<string, unknown>).id).toBeUndefined();
    expect((copied as unknown as Record<string, unknown>).dataset_id).toBeUndefined();
    expect((copied as unknown as Record<string, unknown>).display_name).toBeUndefined();
  });
});

describe('layer-style-clipboard — isStyleCompatible', () => {
  it('returns true for same geometry class', () => {
    const copied = extractCopyableStyle(makeLayer({ dataset_geometry_type: 'Polygon' }));
    expect(isStyleCompatible(copied, makeLayer({ dataset_geometry_type: 'MultiPolygon' }))).toBe(true);
  });

  it('returns false across incompatible geometries (line → polygon)', () => {
    const copied = extractCopyableStyle(makeLayer({ dataset_geometry_type: 'LineString' }));
    expect(isStyleCompatible(copied, makeLayer({ dataset_geometry_type: 'Polygon' }))).toBe(false);
  });

  it("returns false when either side is 'other' (raster/null geometry)", () => {
    const copiedPolygon = extractCopyableStyle(makeLayer({ dataset_geometry_type: 'Polygon' }));
    expect(isStyleCompatible(copiedPolygon, makeLayer({ dataset_geometry_type: null }))).toBe(false);

    const copiedOther = extractCopyableStyle(makeLayer({ dataset_geometry_type: null }));
    expect(isStyleCompatible(copiedOther, makeLayer({ dataset_geometry_type: null }))).toBe(false);
  });
});

describe('layer-style-clipboard — applyCopiedStyleToLayer', () => {
  it('does not mutate the source copied payload or the target layer', () => {
    const copied = extractCopyableStyle(
      makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#abc' }, style_config: { mode: 'categorical', column: 'k', ramp: 'X' } }),
    );
    const copiedSnapshot = structuredClone(copied) as CopiedStyle;
    const target = makeLayer({ id: 'tgt', dataset_geometry_type: 'Polygon', paint: { 'fill-opacity': 0.3 } });
    const targetPaintSnapshot = { ...target.paint };

    const result = applyCopiedStyleToLayer(target, copied);

    expect(result).not.toBe(target);
    expect(copied).toEqual(copiedSnapshot); // copied untouched
    expect(target.paint).toEqual(targetPaintSnapshot); // target untouched
  });

  it('merges copied paint over the target paint and replaces style_config', () => {
    const copied = extractCopyableStyle(
      makeLayer({
        dataset_geometry_type: 'Polygon',
        paint: { 'fill-color': '#123456' },
        style_config: { mode: 'graduated', column: 'pop', ramp: 'Viridis', breaks: [1, 2], colors: ['#a', '#b', '#c'] },
      }),
    );
    const target = makeLayer({ id: 'tgt', dataset_geometry_type: 'Polygon', paint: { 'fill-opacity': 0.25 }, style_config: null });

    const result = applyCopiedStyleToLayer(target, copied);

    // target's own paint keys preserved, copied paint overlaid
    expect(result.paint['fill-opacity']).toBe(0.25);
    expect(result.paint['fill-color']).toBe('#123456');
    // style_config replaced wholesale by the copied one
    expect(result.style_config).toEqual(copied.style_config);
  });

  it('preserves the target layer-identity fields (id/dataset_id/display_name unchanged)', () => {
    const copied = extractCopyableStyle(makeLayer({ id: 'src', dataset_id: 'dsSrc', display_name: 'Source', dataset_geometry_type: 'Polygon' }));
    const target = makeLayer({ id: 'tgt', dataset_id: 'dsTgt', display_name: 'Target', dataset_geometry_type: 'Polygon' });

    const result = applyCopiedStyleToLayer(target, copied);

    expect(result.id).toBe('tgt');
    expect(result.dataset_id).toBe('dsTgt');
    expect(result.display_name).toBe('Target');
  });

  it('polygon→polygon copy/paste round-trip reproduces categories + colors', () => {
    const styleConfig: StyleConfig = {
      mode: 'categorical',
      column: 'zone',
      ramp: 'Set2',
      categories: [
        { value: 'residential', color: '#e41a1c' },
        { value: 'commercial', color: '#377eb8' },
      ],
    };
    const source = makeLayer({ id: 'src', dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ffffff' }, style_config: styleConfig });
    const target = makeLayer({ id: 'tgt', dataset_geometry_type: 'MultiPolygon', paint: {}, style_config: null });

    const copied = extractCopyableStyle(source);
    expect(isStyleCompatible(copied, target)).toBe(true);
    const result = applyCopiedStyleToLayer(target, copied);

    expect(result.style_config).toEqual(styleConfig);
    expect(result.paint['fill-color']).toBe('#ffffff');
  });
});
