import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ColorizedGeometryIcon, LayerTypeIcon, extractStyleHints, type LayerTypeIconLayer } from '../layer-icons';

// Guards the contract LegendPlugin + StackRow both depend on: callers pass the
// capability KIND ('raster'/'vrt'), not the raw layer_type ('raster_geolens').
// Passing the wrong value fell through to a polygon swatch — the "purple
// polygon for raster layers in the legend" bug.
describe('ColorizedGeometryIcon raster/vrt contract', () => {
  it('renders the grid (raster) icon for kind "raster", not a polygon', () => {
    const { container } = render(
      <ColorizedGeometryIcon geometryType={null} colors={[]} layerId="x" layerType="raster" />,
    );
    expect(container.querySelector('.lucide-grid-3x3')).not.toBeNull();
  });

  it('renders the layers (vrt) icon for kind "vrt"', () => {
    const { container } = render(
      <ColorizedGeometryIcon geometryType={null} colors={[]} layerId="x" layerType="vrt" />,
    );
    expect(container.querySelector('.lucide-layers')).not.toBeNull();
  });
});

// ux(#840): categorical styles render hard-stop bands (each color duplicated
// at its band edges) instead of a smooth ramp, capped at 4 bands. Graduated
// ramps keep the smooth gradient.
describe('discrete bands for categorical styles (ux #840)', () => {
  const layerWith = (style_config: LayerTypeIconLayer['style_config']): LayerTypeIconLayer => ({
    dataset_geometry_type: 'POINT',
    layer_type: 'vector_geolens',
    paint: { 'circle-color': ['match', ['get', 'fall'], 'Fell', '#f59e0b', '#94a3b8'] },
    layout: {},
    opacity: 1,
    style_config,
  });

  it('duplicates gradient stops into hard bands for a categorical layer', () => {
    const { container } = render(
      <LayerTypeIcon
        layer={layerWith({
          mode: 'categorical',
          column: 'fall',
          categories: [
            { value: 'Fell', color: '#f59e0b' },
            { value: 'Found', color: '#94a3b8' },
          ],
        })}
        iconId="cat-2"
      />,
    );
    // querySelector('linearGradient …') never matches in JSDOM (HTML selector
    // lowercasing vs case-sensitive SVG tagName) — query the stops directly.
    const stops = Array.from(container.querySelectorAll('stop'));
    // 2 categories → 2 bands → 4 stops with a hard edge at 50%
    expect(stops.map((s) => [s.getAttribute('offset'), s.getAttribute('stop-color')])).toEqual([
      ['0%', '#f59e0b'],
      ['50%', '#f59e0b'],
      ['50%', '#94a3b8'],
      ['100%', '#94a3b8'],
    ]);
  });

  it('caps the icon at 4 bands for many-category layers', () => {
    const categories = ['#111111', '#222222', '#333333', '#444444', '#555555', '#666666']
      .map((color, i) => ({ value: `c${i}`, color }));
    const { container } = render(
      <LayerTypeIcon layer={layerWith({ mode: 'categorical', column: 'c', categories })} iconId="cat-6" />,
    );
    expect(container.querySelectorAll('stop')).toHaveLength(8);
  });

  it('keeps the smooth ramp for graduated colors (no categories)', () => {
    const { container } = render(
      <LayerTypeIcon
        layer={layerWith({ mode: 'graduated', column: 'mass', colors: ['#111111', '#222222', '#333333'] })}
        iconId="grad-3"
      />,
    );
    const stops = Array.from(container.querySelectorAll('stop'));
    expect(stops.map((s) => s.getAttribute('offset'))).toEqual(['0%', '50%', '100%']);
  });
});

// fix(#452): replacement for the deleted StackRow.guard04.test.tsx. The
// extractStyleHints memo moved verbatim into LayerTypeIcon, where a vi.spyOn
// seam can no longer observe the (now intra-module) call. Instead, count
// property READS on the paint object — extractStyleHints touches
// `_stroke-disabled` on every compute and nothing else in the render path
// does, so the read count is a spy-free recomputation counter. Guards the
// `eslint-disable react-hooks/exhaustive-deps` memo: keying it on the local
// `paint`/`layout` fallbacks (fresh objects per render) would silently kill
// memoization for every stack row.
describe('LayerTypeIcon style-hint memoization (GUARD-04)', () => {
  function countingPaint() {
    let reads = 0;
    const paint: Record<string, unknown> = {};
    Object.defineProperty(paint, '_stroke-disabled', {
      get() {
        reads += 1;
        return false;
      },
      enumerable: true,
    });
    return { paint, reads: () => reads };
  }

  const baseLayer = (paint: Record<string, unknown>): LayerTypeIconLayer => ({
    dataset_geometry_type: 'POLYGON',
    layer_type: 'vector_geolens',
    paint,
    layout: {},
    opacity: 1,
    style_config: null,
  });

  it('does not recompute hints on unrelated prop changes, but does on a paint change', () => {
    const { paint, reads } = countingPaint();
    const layer = baseLayer(paint);
    const { rerender } = render(<LayerTypeIcon layer={layer} iconId="icon-a" />);
    const initialReads = reads();
    expect(initialReads).toBeGreaterThan(0);

    // Unrelated change (iconId is not a memo dep; layer identity unchanged) —
    // the memo must hold and paint must not be re-read.
    rerender(<LayerTypeIcon layer={layer} iconId="icon-b" />);
    expect(reads()).toBe(initialReads);

    // Keyed change: a NEW paint object must recompute the hints.
    const next = countingPaint();
    rerender(<LayerTypeIcon layer={baseLayer(next.paint)} iconId="icon-b" />);
    expect(next.reads()).toBeGreaterThan(0);
  });

  // The exact regression GUARD-04 exists for: with a NULL layer.paint, keying
  // the memo on the local `paint`/`layout` fallbacks (fresh `{}` per render)
  // would recompute on EVERY render. Count layout reads for a LINE layer
  // (extractStyleHints falls through to layout['line-dasharray'] when paint
  // has none) — the count must not grow on unrelated rerenders.
  it('holds the memo across rerenders when paint is null (fallback-object trap)', () => {
    let layoutReads = 0;
    const layout: Record<string, unknown> = {};
    Object.defineProperty(layout, 'line-dasharray', {
      get() {
        layoutReads += 1;
        return [2, 2];
      },
      enumerable: true,
    });
    const layer: LayerTypeIconLayer = {
      dataset_geometry_type: 'LINESTRING',
      layer_type: 'vector_geolens',
      paint: null as unknown as LayerTypeIconLayer['paint'],
      layout,
      opacity: 1,
      style_config: null,
    };

    const { rerender } = render(<LayerTypeIcon layer={layer} iconId="icon-a" />);
    const initialReads = layoutReads;
    expect(initialReads).toBeGreaterThan(0);

    rerender(<LayerTypeIcon layer={layer} iconId="icon-b" />);
    rerender(<LayerTypeIcon layer={layer} iconId="icon-c" />);
    expect(layoutReads).toBe(initialReads);
  });
});

// fix(#951): the layer-list swatch showed a solid pentagon for a patterned
// polygon layer. extractStyleHints now carries fill-pattern through.
describe('patterned polygon swatch (fix #951)', () => {
  it('renders the pattern preview instead of the solid pentagon', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#ff5a5f']}
        layerId="x"
        styleHints={{ fillPattern: 'geolens-fill-dots' }}
      />,
    );
    expect(container.querySelector('.lucide-pentagon')).toBeNull();
    const chip = container.firstElementChild as HTMLElement;
    expect(chip.style.backgroundImage).toContain('radial-gradient');
    expect(chip.style.color).toBe('rgb(255, 90, 95)');
  });

  it('extractStyleHints picks fill-pattern up from polygon paint', () => {
    expect(
      extractStyleHints({ 'fill-pattern': 'geolens-fill-grid' }, {}, 'POLYGON').fillPattern,
    ).toBe('geolens-fill-grid');
    expect(extractStyleHints({ 'fill-color': '#fff' }, {}, 'POLYGON').fillPattern).toBeUndefined();
  });

  it('ignores a fill-pattern id that has no built-in preview', () => {
    // An imported layer can carry any sprite id; taking the patterned branch for
    // one we cannot draw would render an empty chip instead of the solid colour.
    expect(extractStyleHints({ 'fill-pattern': 'custom-sprite' }, {}, 'POLYGON').fillPattern).toBeUndefined();
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#ff5a5f']}
        layerId="x"
        styleHints={extractStyleHints({ 'fill-pattern': 'custom-sprite' }, {}, 'POLYGON')}
      />,
    );
    expect(container.querySelector('.lucide-pentagon')).not.toBeNull();
  });

  it('carries the pattern through generic GEOMETRY layers (mixed adapter)', () => {
    for (const gt of ['GEOMETRY', 'GEOMETRYCOLLECTION']) {
      expect(extractStyleHints({ 'fill-pattern': 'geolens-fill-grid' }, {}, gt).fillPattern)
        .toBe('geolens-fill-grid');
    }
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="GEOMETRY"
        colors={['#ff5a5f']}
        layerId="x"
        styleHints={{ fillPattern: 'geolens-fill-grid' }}
      />,
    );
    expect(container.querySelector('.lucide-pentagon')).toBeNull();
  });

  it('leaves unpatterned polygons on the pentagon glyph', () => {
    const { container } = render(
      <ColorizedGeometryIcon geometryType="POLYGON" colors={['#ff5a5f']} layerId="x" />,
    );
    expect(container.querySelector('.lucide-pentagon')).not.toBeNull();
  });
});
