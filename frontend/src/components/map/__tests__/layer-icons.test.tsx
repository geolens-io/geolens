import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ColorizedGeometryIcon, LayerTypeIcon, getLayerColors, type LayerTypeIconLayer } from '../layer-icons';
import type { LegendSwatch } from '../legend-facts';
import { MAP_COLORS } from '@/lib/map-colors';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import type { MapLayerResponse } from '@/types/api';

function legendSwatch(overrides: Partial<LegendSwatch> = {}): LegendSwatch {
  return { fill: null, fillOpacity: 1, opacity: 1, stroke: null, pattern: null, ...overrides };
}

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
  const layerWith = (style_config: NonNullable<LayerTypeIconLayer['style_config']>): LayerTypeIconLayer => ({
    dataset_geometry_type: 'POINT',
    layer_type: 'vector_geolens',
    // The paint reads the classified column, so the classification is live.
    paint: { 'circle-color': ['match', ['get', style_config.column], 'Fell', '#f59e0b', '#94a3b8'] },
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

  it('draws no class colours for a symbol layer with a leftover classification', () => {
    const { container } = render(<LayerTypeIcon layer={SAVED_LAYERS.symbolWithLeftoverClassification} iconId="symbols" />);
    expect(container.querySelectorAll('stop')).toHaveLength(0);
    expect(container.querySelector('.lucide-circle')).toHaveAttribute('fill', MAP_COLORS.icon.fallback);
  });

  it('draws a size classification in its classes\' colour when no colour classes are listed', () => {
    const layer: LayerTypeIconLayer = {
      dataset_geometry_type: 'POINT',
      layer_type: 'vector_geolens',
      paint: {
        'circle-radius': ['step', ['get', 'pop'], 4, 1000, 8],
        'circle-color': ['case', ['==', ['get', 'pop'], null], '#cccccc', ['step', ['get', 'pop'], '#fee8c8', 1000, '#e34a33']],
      },
      style_config: { mode: 'graduated', column: 'pop', target: 'radius', sizes: [4, 8], breaks: [1000] },
    };
    const { container } = render(<LayerTypeIcon layer={layer} iconId="sized" />);
    expect(container.querySelector('.lucide-circle')).toHaveAttribute('fill', MAP_COLORS.fallback);
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

// LayerTypeIcon memoizes its hint and swatch extraction. A spy cannot see the
// in-module calls, so these count property READS: only the swatch reads a
// polygon's `_stroke-disabled`, and a line's hints read `layout['line-dasharray']`.
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

// The map draws a fill-pattern instead of the fill, so a patterned polygon's icon draws the pattern.
describe('patterned polygon swatch (fix #951)', () => {
  it('renders the pattern preview instead of the solid pentagon', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="POLYGON"
        colors={['#ff5a5f']}
        layerId="x"
        swatch={legendSwatch({ pattern: { id: 'geolens-fill-dots', tint: null } })}
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
        swatch={legendSwatch({ pattern: { id: 'geolens-fill-dots', tint: '#1d4ed8' } })}
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
        swatch={legendSwatch({
          pattern: { id: 'geolens-fill-dots', tint: null },
          fillOpacity: 0,
          stroke: { color: '#ec4b7f', width: 1 },
        })}
      />,
    );
    const outer = container.firstElementChild as HTMLElement;
    const inner = outer.firstElementChild as HTMLElement;
    expect(outer.style.opacity).toBe('');
    expect(outer.style.borderColor).toBe('rgb(236, 75, 127)');
    expect(inner.style.opacity).toBe('0');
  });

  it('draws the pattern for generic GEOMETRY layers (mixed adapter)', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="GEOMETRY"
        colors={['#ff5a5f']}
        layerId="x"
        swatch={legendSwatch({ pattern: { id: 'geolens-fill-grid', tint: null } })}
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
        swatch={legendSwatch({ fillOpacity: 0, stroke: { color: '#ec4b7f', width: 1 } })}
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
});

// fix(#1494): a horizontal <line> has a zero-height bounding box, and the SVG
// spec disables rendering of any element painted by a bounding-box-united
// gradient when either bbox dimension is zero. The line icon's gradient must
// therefore declare userSpaceOnUse, or every multi-color line layer (banded
// categorical and graduated alike) renders a blank where its symbology
// belongs — in the builder layer list, the sidebar rail, and both legends.
describe('ColorizedGeometryIcon line gradients (fix #1494)', () => {
  const bands = ['#9ca3af', '#60a5fa', '#facc15', '#fb923c'];

  it('paints multi-color line icons with a user-space gradient', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="MultiLineString"
        colors={bands}
        layerId="storm-tracks"
        discrete
      />,
    );

    const gradient = container.querySelector('linearGradient');
    expect(gradient).not.toBeNull();
    expect(gradient).toHaveAttribute('gradientUnits', 'userSpaceOnUse');

    const line = container.querySelector('line');
    expect(line).toHaveAttribute('stroke', `url(#${gradient!.id})`);
    // The gradient must span the stroke it paints, not default to a unit box.
    expect(gradient).toHaveAttribute('x1', line!.getAttribute('x1')!);
    expect(gradient).toHaveAttribute('x2', line!.getAttribute('x2')!);
  });

  it('keeps single-color line icons on a plain stroke with no gradient', () => {
    const { container } = render(
      <ColorizedGeometryIcon
        geometryType="LineString"
        colors={['#ef4444']}
        layerId="single"
      />,
    );

    expect(container.querySelector('linearGradient')).toBeNull();
    expect(container.querySelector('line')).toHaveAttribute('stroke', '#ef4444');
  });
});

describe('getLayerColors heatmap ramp direction', () => {
  it('reverses the sampled ramp when _heatmap-reversed is set', () => {
    const layerWithRamp = (reversed: boolean): Parameters<typeof getLayerColors>[0] => ({
      paint: { '_heatmap-ramp': 'YlOrRd', '_heatmap-reversed': reversed },
      style_config: { render_mode: 'heatmap', ramp: 'YlOrRd' } as MapLayerResponse['style_config'],
    });

    const forward = getLayerColors(layerWithRamp(false), null);
    const reversed = getLayerColors(layerWithRamp(true), null);
    expect(reversed).toEqual([...forward].reverse());
    expect(reversed[0]).not.toBe(forward[0]);
  });
});

describe('LayerTypeIcon swatch', () => {
  it('outlines a polygon with no stored stroke in the default outline the map draws', () => {
    const { container } = render(<LayerTypeIcon layer={SAVED_LAYERS.polygon} iconId="parcels" />);
    const icon = container.querySelector('.lucide-pentagon');
    expect(icon).toHaveAttribute('stroke', MAP_COLORS.default.stroke);
    expect(icon).toHaveAttribute('fill-opacity', '0.3');
  });

  it('rings a point only where circle-stroke-width draws a ring', () => {
    const hollow = { ...SAVED_LAYERS.ringlessPoint, paint: { 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c' } };
    const { container } = render(
      <>
        <LayerTypeIcon layer={SAVED_LAYERS.point} iconId="wells" />
        <LayerTypeIcon layer={hollow} iconId="hollow" />
      </>,
    );
    const [ringed, ringless] = Array.from(container.querySelectorAll('.lucide-circle'));
    expect(ringed).toHaveAttribute('stroke', '#1d4ed8');
    expect(ringless).toHaveAttribute('stroke-width', '0');
  });
});
