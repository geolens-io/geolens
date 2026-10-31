// resolvePolygonStroke picks the outline colour from builder state, then the paint keys, then the default.
import { describe, it, expect } from 'vitest';
import { MAP_COLORS } from '@/lib/map-colors';
import { fillAdapter, resolvePolygonStroke } from '../fill-adapter';
import type { AdapterLayerInput } from '../types';

describe('resolvePolygonStroke outline colour', () => {
  it('falls back to a string fill-outline-color before the default', () => {
    const stroke = resolvePolygonStroke({ 'fill-outline-color': '#14532d' }, {});
    expect(stroke.authoredColor).toBe('#14532d');
    expect(stroke.color).toBe('#14532d');
  });

  it('ranks it below the builder and mirror colours', () => {
    expect(resolvePolygonStroke({ 'fill-outline-color': '#14532d', '_outline-color': '#111111' }, {}).color).toBe('#111111');
    expect(resolvePolygonStroke({ 'fill-outline-color': '#14532d' }, { outlineColor: '#222222' }).color).toBe('#222222');
  });

  it('ignores a fill-outline-color that is not a string', () => {
    expect(resolvePolygonStroke({ 'fill-outline-color': ['get', 'c'] }, {}).authoredColor).toBeUndefined();
  });
});

describe('fill adapter native outline', () => {
  const input = (paint: Record<string, unknown>): AdapterLayerInput => ({
    id: 'layer-fill-1',
    dataset_table_name: 'ds_fill',
    dataset_geometry_type: 'POLYGON',
    opacity: 1,
    visible: true,
    paint,
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    sourceId: 'source-fill-1',
    layerId: 'layer-fill-1',
    sourceLayer: 'ds_fill',
    sourceType: 'vector',
    tileUrl: '/tiles/{z}/{x}/{y}',
  });
  const nativeOutline = (paint: Record<string, unknown>) =>
    fillAdapter.describe?.(input(paint)).specs[0].layer.paint?.['fill-outline-color'];

  it('draws the authored outline colour at a non-zero width', () => {
    expect(nativeOutline({ 'fill-outline-color': '#14532d', 'outline-width': 1 })).toBe('#14532d');
  });

  it('hides it at width zero', () => {
    expect(nativeOutline({ 'fill-outline-color': '#14532d', 'outline-width': 0 })).toBe(MAP_COLORS.transparent);
  });
});
