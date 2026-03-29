import { describe, it, expect, vi } from 'vitest';
import { buildLabelLayerSpec, syncLabelLayer } from '../label-layer-utils';
import type { LabelConfig } from '@/types/api';

const baseLc: LabelConfig = {
  column: 'name',
  fontSize: 14,
  textColor: '#111',
  haloColor: '#fff',
  haloWidth: 2,
  minZoom: 3,
  maxZoom: 18,
};

describe('buildLabelLayerSpec', () => {
  it('builds a symbol layer spec with point placement defaults', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-1',
      sourceId: 'source-1',
      sourceLayer: 'data.my_table',
      lc: baseLc,
      geomType: 'fill',
    });

    expect(spec.id).toBe('label-1');
    expect(spec.type).toBe('symbol');
    expect(spec.source).toBe('source-1');
    expect(spec['source-layer']).toBe('data.my_table');
    expect(spec.minzoom).toBe(3);
    expect(spec.maxzoom).toBe(18);

    const layout = spec.layout as Record<string, unknown>;
    expect(layout['text-field']).toEqual(['get', 'name']);
    expect(layout['text-size']).toBe(14);
    expect(layout['symbol-placement']).toBe('point');
    expect(layout['text-allow-overlap']).toBe(false);
    expect(layout['text-anchor']).toBe('center');
    expect(layout['text-offset']).toEqual([0, 0]);

    const paint = spec.paint as Record<string, unknown>;
    expect(paint['text-color']).toBe('#111');
    expect(paint['text-halo-color']).toBe('#fff');
    expect(paint['text-halo-width']).toBe(2);
  });

  it('uses line placement for line geometry', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-2',
      sourceId: 'source-2',
      sourceLayer: 'data.lines',
      lc: { column: 'road_name' },
      geomType: 'line',
    });

    const layout = spec.layout as Record<string, unknown>;
    expect(layout['symbol-placement']).toBe('line');
    expect(layout['text-anchor']).toBeUndefined();
    expect(layout['text-offset']).toBeUndefined();
  });

  it('respects explicit placement override', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-3',
      sourceId: 'source-3',
      sourceLayer: 'data.pts',
      lc: { column: 'label', placement: 'line-center' },
      geomType: 'circle',
    });

    const layout = spec.layout as Record<string, unknown>;
    expect(layout['symbol-placement']).toBe('line-center');
    expect(layout['text-anchor']).toBeUndefined();
  });

  it('uses circle offset default for point placement on circle geometry', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-4',
      sourceId: 'source-4',
      sourceLayer: 'data.pts',
      lc: { column: 'name' },
      geomType: 'circle',
    });

    const layout = spec.layout as Record<string, unknown>;
    expect(layout['text-offset']).toEqual([0, -1.5]);
  });

  it('includes visibility when provided', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-5',
      sourceId: 'source-5',
      sourceLayer: 'data.t',
      lc: { column: 'x' },
      geomType: 'fill',
      visibility: 'none',
    });

    const layout = spec.layout as Record<string, unknown>;
    expect(layout['visibility']).toBe('none');
  });

  it('omits visibility when not provided', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-6',
      sourceId: 'source-6',
      sourceLayer: 'data.t',
      lc: { column: 'x' },
      geomType: 'fill',
    });

    const layout = spec.layout as Record<string, unknown>;
    expect(layout).not.toHaveProperty('visibility');
  });

  it('passes through textAnchor, textOffset, and allowOverlap', () => {
    const spec = buildLabelLayerSpec({
      labelId: 'label-7',
      sourceId: 'source-7',
      sourceLayer: 'data.t',
      lc: { column: 'x', placement: 'point', textAnchor: 'top', textOffset: [1, -2], allowOverlap: true },
      geomType: 'fill',
    });

    const layout = spec.layout as Record<string, unknown>;
    expect(layout['text-anchor']).toBe('top');
    expect(layout['text-offset']).toEqual([1, -2]);
    expect(layout['text-allow-overlap']).toBe(true);
  });
});

describe('syncLabelLayer', () => {
  function createMockMap() {
    return {
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
      setLayerZoomRange: vi.fn(),
    };
  }

  it('sets all layout and paint properties for point placement', () => {
    const map = createMockMap();
    syncLabelLayer(map, 'label-1', baseLc, 'fill');

    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-1', 'text-field', ['get', 'name']);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-1', 'text-size', 14);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-1', 'symbol-placement', 'point');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-1', 'text-allow-overlap', false);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-1', 'text-anchor', 'center');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-1', 'text-offset', [0, 0]);

    expect(map.setPaintProperty).toHaveBeenCalledWith('label-1', 'text-color', '#111');
    expect(map.setPaintProperty).toHaveBeenCalledWith('label-1', 'text-halo-color', '#fff');
    expect(map.setPaintProperty).toHaveBeenCalledWith('label-1', 'text-halo-width', 2);

    expect(map.setLayerZoomRange).toHaveBeenCalledWith('label-1', 3, 18);
  });

  it('clears text-anchor and text-offset for line placement', () => {
    const map = createMockMap();
    syncLabelLayer(map, 'label-2', { column: 'road', placement: 'line' }, 'line');

    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-2', 'symbol-placement', 'line');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-2', 'text-anchor', undefined);
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-2', 'text-offset', undefined);
  });

  it('defaults to line placement for line geometry when placement not specified', () => {
    const map = createMockMap();
    syncLabelLayer(map, 'label-3', { column: 'name' }, 'line');

    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-3', 'symbol-placement', 'line');
    expect(map.setLayoutProperty).toHaveBeenCalledWith('label-3', 'text-anchor', undefined);
  });

  it('uses default zoom range when not specified', () => {
    const map = createMockMap();
    syncLabelLayer(map, 'label-4', { column: 'x' }, 'fill');

    expect(map.setLayerZoomRange).toHaveBeenCalledWith('label-4', 0, 22);
  });
});
