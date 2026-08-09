import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CategoricalLegend } from '../LegendEntries';

describe('CategoricalLegend', () => {
  it('uses category labels when saved map metadata provides them', () => {
    render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[
          { value: '01', label: 'Residential', color: '#ff5a5f' },
          { value: '02', label: 'Mixed Residential/Commercial', color: '#ffb000' },
        ]}
      />,
    );

    expect(screen.getByText('Residential')).toBeInTheDocument();
    expect(screen.getByText('Mixed Residential/Commercial')).toBeInTheDocument();
    expect(screen.queryByText('01')).not.toBeInTheDocument();
    expect(screen.queryByText('02')).not.toBeInTheDocument();
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
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#ff5a5f' }]}
        style={{ fillPattern: 'geolens-fill-hatch' }}
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
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#ff5a5f' }]}
        style={{ fillPattern: 'geolens-fill-hatch', fillPatternColor: '#1d4ed8' }}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.color).toBe('rgb(29, 78, 216)');
  });

  it('leaves unpatterned polygons on the solid chip', () => {
    const { container } = render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#ff5a5f' }]}
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
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: 'rgb(255, 90, 95)' }]}
        style={{ fillPattern: 'geolens-fill-hatch', fillOpacity: 0, outlineColor: '#ec4b7f' }}
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
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#3b82f6' }]}
        style={{ fillOpacity: 0, outlineColor: '#ec4b7f' }}
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
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#f00' }]}
        style={{ fillOpacity: 0.3 }}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.backgroundColor).toBe('rgb(255, 0, 0)');
    expect(fill.style.opacity).toBe('0.3');
  });

  it('leaves a normal fill unchanged', () => {
    const { container } = render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#3b82f6' }]}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    const fill = swatch.firstElementChild as HTMLElement;
    expect(fill.style.backgroundColor).toBe('rgb(59, 130, 246)');
    expect(fill.style.opacity).toBe('');
  });

  it('still applies layer-level opacity to the whole swatch', () => {
    const { container } = render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#3b82f6' }]}
        style={{ opacity: 0.5 }}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(swatch.style.opacity).toBe('0.5');
  });

  // fix(#1288 codex): a truthy check on strokeWidth dropped an EXPLICIT 0,
  // falling back to the default 1px border even though the map draws no
  // outline at width 0.
  it('honors an explicit zero-width outline as no border', () => {
    const { container } = render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#3b82f6' }]}
        style={{ strokeWidth: 0, outlineColor: '#ec4b7f' }}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(swatch.style.borderWidth).toBe('0px');
  });
});
