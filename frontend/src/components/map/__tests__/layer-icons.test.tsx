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
    // fix(#1288 codex): the pattern now lives on a nested span so its opacity
    // can be dimmed independently of the border — assert on that inner span.
    const chip = container.firstElementChild!.firstElementChild as HTMLElement;
    expect(chip.style.backgroundImage).toContain('radial-gradient');
    expect(chip.style.color).toBe('rgb(255, 90, 95)');
  });

  // fix(#914): same agreement requirement as the legend chip.
  it('draws the pattern in the map tint when one is resolved', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#ff5a5f']}
        layerId="x"
        styleHints={{ fillPattern: 'geolens-fill-dots', fillPatternColor: '#1d4ed8' }}
      />,
    );
    const chip = container.firstElementChild!.firstElementChild as HTMLElement;
    expect(chip.style.color).toBe('rgb(29, 78, 216)');
  });

  // fix(#1288 codex): a partially-transparent patterned fill (fillOpacity < 1)
  // must dim the pattern pixels without touching the border.
  it('applies fillOpacity to the pattern layer only, not the border', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#ff5a5f']}
        layerId="x"
        styleHints={{ fillPattern: 'geolens-fill-dots', fillOpacity: 0, strokeColor: '#ec4b7f' }}
      />,
    );
    const outer = container.firstElementChild as HTMLElement;
    const inner = outer.firstElementChild as HTMLElement;
    expect(outer.style.opacity).toBe('');
    expect(outer.style.borderColor).toBe('rgb(236, 75, 127)');
    expect(inner.style.opacity).toBe('0');
  });

  it('extractStyleHints resolves the tint from the fillColorSaved stash', () => {
    // A pattern deletes fill-color from paint (EDIT-05), so the stash is the only
    // place the layer's colour survives.
    expect(
      extractStyleHints({ 'fill-pattern': 'geolens-fill-grid' }, {}, 'POLYGON', 1, {
        builder: { fillColorSaved: '#1d4ed8' },
      }).fillPatternColor,
    ).toBe('#1d4ed8');
    // A layer that still carries both keys (older clients) tints from paint.
    expect(
      extractStyleHints({ 'fill-pattern': 'geolens-fill-grid', 'fill-color': '#ff0000' }, {}, 'POLYGON')
        .fillPatternColor,
    ).toBe('#ff0000');
    // Nothing to tint with -> undefined, and every consumer falls back to grey.
    expect(
      extractStyleHints({ 'fill-pattern': 'geolens-fill-grid' }, {}, 'POLYGON').fillPatternColor,
    ).toBeUndefined();
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

// fix(#1288): a stroke-only polygon (fill-opacity: 0, visible outline) used to
// render an invisible swatch — element-level opacity hid the outline along with
// the fill it was meant to suppress. fillOpacity now lands on the SVG fill only.
describe('stroke-only polygon swatch (fix #1288)', () => {
  it('renders a visible outline when fill-opacity is 0', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#3b82f6']}
        layerId="x"
        styleHints={{ fillOpacity: 0, strokeColor: '#ec4b7f' }}
      />,
    );
    const span = container.firstElementChild as HTMLElement;
    expect(span.style.opacity).toBe('');
    const icon = container.querySelector('.lucide-pentagon') as SVGElement;
    expect(icon.getAttribute('fill-opacity')).toBe('0');
    expect(icon.getAttribute('stroke')).toBe('#ec4b7f');
  });

  it('leaves a normal filled polygon unchanged', () => {
    const { container } = render(
      <ColorizedGeometryIcon geometryType="POLYGON" colors={['#3b82f6']} layerId="x" />,
    );
    const span = container.firstElementChild as HTMLElement;
    expect(span.style.opacity).toBe('');
    const icon = container.querySelector('.lucide-pentagon') as SVGElement;
    expect(icon.getAttribute('fill')).toBe('#3b82f6');
    expect(icon.getAttribute('fill-opacity')).toBeNull();
  });

  it('still applies layer-level opacity to the whole swatch', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#3b82f6']}
        layerId="x"
        styleHints={{ opacity: 0.4 }}
      />,
    );
    const span = container.firstElementChild as HTMLElement;
    expect(span.style.opacity).toBe('0.4');
  });

  it('extractStyleHints prefers builder.outlineColor over a stale paint mirror', () => {
    // The renderer draws from style_config.builder, so a swatch reading only the
    // flat paint mirror can show a color the map no longer draws.
    const hints = extractStyleHints(
      { 'fill-opacity': 0, '_outline-color': '#0058ac' },
      {},
      'POLYGON',
      1,
      { builder: { outlineColor: '#ec4b7f' } },
    );
    expect(hints.strokeColor).toBe('#ec4b7f');
    expect(hints.fillOpacity).toBe(0);
  });

  // fix(#1288 codex): with fill-opacity now revealing the outline instead of
  // hiding the whole swatch, a stroke the user turned off via the builder (which
  // can leave a stale/absent paint['_stroke-disabled']) must not draw as visible.
  it('extractStyleHints prefers builder.strokeDisabled over a stale paint mirror', () => {
    const hints = extractStyleHints(
      { 'fill-opacity': 0, '_outline-color': '#ec4b7f' },
      {},
      'POLYGON',
      1,
      { builder: { strokeDisabled: true, outlineColor: '#ec4b7f' } },
    );
    expect(hints.strokeDisabled).toBe(true);
    expect(hints.strokeColor).toBeUndefined();
  });

  // fix(#1288 codex): an explicit outline width of 0 draws nothing on the map
  // (distinct from strokeDisabled, which is a separate private flag) — the
  // swatch must not draw ShapeIcon's fixed-width outline for it regardless.
  it('extractStyleHints treats an explicit zero outline width as a disabled stroke', () => {
    const hints = extractStyleHints(
      { 'fill-opacity': 0, '_outline-color': '#ec4b7f', '_outline-width': 0 },
      {},
      'POLYGON',
    );
    expect(hints.strokeDisabled).toBe(true);
    expect(hints.strokeColor).toBeUndefined();
  });

  it('extractStyleHints prefers builder.outlineWidth over a stale paint mirror', () => {
    const hints = extractStyleHints(
      { 'fill-opacity': 0, '_outline-color': '#ec4b7f', '_outline-width': 2 },
      {},
      'POLYGON',
      1,
      { builder: { outlineWidth: 0, outlineColor: '#ec4b7f' } },
    );
    expect(hints.strokeDisabled).toBe(true);
    expect(hints.strokeColor).toBeUndefined();
  });
});
