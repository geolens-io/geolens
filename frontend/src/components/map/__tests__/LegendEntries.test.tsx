import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LegendClassesList } from '../LegendEntries';
import type { LegendClasses, LegendSwatch } from '../legend-facts';

function legendSwatch(overrides: Partial<LegendSwatch> = {}): LegendSwatch {
  return { fill: null, fillOpacity: 1, opacity: 1, stroke: null, pattern: null, ...overrides };
}

function categories(items: { value: string; label?: string; color: string }[]): LegendClasses {
  return {
    mode: 'categorical',
    target: 'color',
    title: 'class',
    items: items.map(({ value, label, color }) => ({ color, label: label ?? value })),
    breaks: [],
  };
}

describe('LegendClassesList', () => {
  it('labels categories with their own labels', () => {
    render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([
          { value: '01', label: 'Residential', color: '#ff5a5f' },
          { value: '02', label: 'Mixed Residential/Commercial', color: '#ffb000' },
        ])]}
      />,
    );

    expect(screen.getByText('Residential')).toBeInTheDocument();
    expect(screen.getByText('Mixed Residential/Commercial')).toBeInTheDocument();
    expect(screen.queryByText('01')).not.toBeInTheDocument();
  });

  it('labels graduated classes by break range and titles only a following colour classification', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Point"
        classes={[
          { mode: 'graduated', target: 'radius', title: 'Magnitude', items: [{ color: '#ef4444', size: 4 }, { color: '#ef4444', size: 8 }], breaks: [6] },
          { mode: 'graduated', target: 'color', title: 'Depth', items: [{ color: '#fde725' }, { color: '#7d3c98' }], breaks: [50] },
        ]}
      />,
    );

    expect(screen.getByText('Size: Magnitude')).toBeInTheDocument();
    expect(screen.getByText('Color: Depth')).toBeInTheDocument();
    expect(screen.getAllByText('< 6')).toHaveLength(1);
    expect(screen.getByText('≥ 50')).toBeInTheDocument();
    const circles = Array.from(container.querySelectorAll('svg[viewBox="0 0 24 24"] circle'));
    expect(circles.map((circle) => [circle.getAttribute('r'), circle.getAttribute('fill')])).toEqual([
      ['4', '#ef4444'],
      ['8', '#ef4444'],
    ]);
  });

  it('draws width classes as lines of each width in the class colour', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="LineString"
        classes={[{ mode: 'graduated', target: 'width', title: 'Flow', items: [{ color: '#0284c7', size: 1 }, { color: '#0284c7', size: 6 }], breaks: [10] }]}
      />,
    );

    expect(screen.getByText('Width: Flow')).toBeInTheDocument();
    const lines = Array.from(container.querySelectorAll('line'));
    expect(lines.map((line) => [line.getAttribute('stroke-width'), line.getAttribute('stroke')])).toEqual([
      ['1', '#0284c7'],
      ['6', '#0284c7'],
    ]);
  });

  it('draws no title for a lone colour classification', () => {
    render(<LegendClassesList geometryType="Polygon" classes={[categories([{ value: 'a', color: '#ff5a5f' }])]} />);

    expect(screen.queryByText(/Color:/)).not.toBeInTheDocument();
  });
});

// fix(#951): MapLibre draws a fill-pattern INSTEAD of the fill, so a solid chip
// described a colour that appeared nowhere on the map.
// fix(#1288 codex): the fill/pattern now lives on a nested div, split from the
// border, so fillOpacity can dim one without the other — assertions below read
// the inner div for fill/pattern styling and the outer for border/opacity.
describe('GeometrySwatch — patterned polygons', () => {
  it('draws the pattern preview, in the class colour, instead of a solid block', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#ff5a5f' }])]}
        style={legendSwatch({ pattern: { id: 'geolens-fill-hatch', tint: null } })}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.backgroundImage).toContain('repeating-linear-gradient');
    expect(fill.style.backgroundColor).toBe('transparent');
    expect(fill.style.color).toBe('rgb(255, 90, 95)');
  });

  // fix(#914): the map tints the pattern with the layer's fill colour, which for a
  // patterned layer lives in the fillColorSaved stash rather than in paint — so the
  // chip has to draw that colour, not whatever its own `color` fell back to.
  it('draws the pattern in the colour the map tints it with, not the chip colour', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#ff5a5f' }])]}
        style={legendSwatch({ pattern: { id: 'geolens-fill-hatch', tint: '#1d4ed8' } })}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.color).toBe('rgb(29, 78, 216)');
  });

  it('leaves unpatterned polygons on the solid chip', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#ff5a5f' }])]}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.backgroundImage).toBe('');
    expect(fill.style.backgroundColor).toBe('rgb(255, 90, 95)');
  });

  // fix(#1288 codex): a partially-transparent pattern must dim independently of
  // the border, and for ANY color format — not just 6-digit hex — since opacity
  // is applied via plain CSS opacity on the fill layer, not string parsing.
  it('applies fillOpacity to the pattern layer only, not the border', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: 'rgb(255, 90, 95)' }])]}
        style={legendSwatch({ pattern: { id: 'geolens-fill-hatch', tint: null }, fillOpacity: 0, stroke: { color: '#ec4b7f', width: 1 } })}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(swatch.style.opacity).toBe('');
    expect(swatch.style.borderColor).toBe('rgb(236, 75, 127)');
    expect(fill.style.opacity).toBe('0');
  });
});

// fix(#1288): a stroke-only polygon (fillOpacity: 0) used to render at
// container-level opacity 0 — invisible, even though it has a visible outline.
describe('GeometrySwatch — stroke-only polygons (fix #1288)', () => {
  it('renders a transparent fill inside a fully opaque border', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#3b82f6' }])]}
        style={legendSwatch({ fillOpacity: 0, stroke: { color: '#ec4b7f', width: 1 } })}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(swatch.style.opacity).toBe('');
    expect(swatch.style.borderColor).toBe('rgb(236, 75, 127)');
    expect(fill.style.backgroundColor).toBe('rgb(59, 130, 246)');
    expect(fill.style.opacity).toBe('0');
  });

  // fix(#1288 codex): #f00 (3-digit hex) is a valid CSS color the alpha-blend
  // helper used to silently ignore — plain opacity on the fill layer handles it
  // (and every other CSS color syntax) with no format-specific parsing.
  it('dims a fill given in a non-6-digit-hex color format', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#f00' }])]}
        style={legendSwatch({ fillOpacity: 0.3 })}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.backgroundColor).toBe('rgb(255, 0, 0)');
    expect(fill.style.opacity).toBe('0.3');
  });

  it('leaves a normal fill unchanged', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#3b82f6' }])]}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.backgroundColor).toBe('rgb(59, 130, 246)');
    expect(fill.style.opacity).toBe('');
  });

  it('still applies layer-level opacity to the whole swatch', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#3b82f6' }])]}
        style={legendSwatch({ opacity: 0.5 })}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(swatch.style.opacity).toBe('0.5');
  });

  it('draws the stroke as the border at its width', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#3b82f6' }])]}
        style={legendSwatch({ stroke: { color: '#ec4b7f', width: 2 } })}
      />,
    );
    const chip = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(chip).toHaveClass('border');
    expect(chip.style.borderColor).toBe('rgb(236, 75, 127)');
    expect(chip.style.borderWidth).toBe('2px');
  });

  it('draws no border when the swatch has no stroke', () => {
    const { container } = render(
      <LegendClassesList
        geometryType="Polygon"
        classes={[categories([{ value: 'a', label: 'A', color: '#3b82f6' }])]}
        style={legendSwatch()}
      />,
    );
    const chip = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(chip).not.toHaveClass('border');
    expect(chip.style.borderColor).toBe('');
  });
});

describe('GeometrySwatch — points', () => {
  it('draws the ring the swatch has, and none without one', () => {
    const { container } = render(
      <>
        <LegendClassesList
          geometryType="Point"
          classes={[categories([{ value: 'a', label: 'A', color: '#fff7ed' }])]}
          style={legendSwatch({ stroke: { color: '#ea580c', width: 2 } })}
        />
        <LegendClassesList
          geometryType="Point"
          classes={[categories([{ value: 'b', label: 'B', color: '#fff7ed' }])]}
          style={legendSwatch()}
        />
      </>,
    );
    const [ringed, ringless] = Array.from(container.querySelectorAll('circle'));
    expect(ringed).toHaveAttribute('stroke', '#ea580c');
    expect(ringed).toHaveAttribute('stroke-width', '2');
    expect(ringless).not.toHaveAttribute('stroke');
    expect(ringless).toHaveAttribute('stroke-width', '0');
  });
});
