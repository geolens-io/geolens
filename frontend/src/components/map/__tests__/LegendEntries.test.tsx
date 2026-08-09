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
    expect(swatch.style.backgroundImage).toContain('repeating-linear-gradient');
    expect(swatch.style.backgroundColor).toBe('transparent');
    expect(swatch.style.color).toBe('rgb(255, 90, 95)');
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
    expect(swatch.style.color).toBe('rgb(29, 78, 216)');
  });

  it('leaves unpatterned polygons on the solid chip', () => {
    const { container } = render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#ff5a5f' }]}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(swatch.style.backgroundImage).toBe('');
    expect(swatch.style.backgroundColor).toBe('rgb(255, 90, 95)');
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
    expect(swatch.style.opacity).toBe('');
    expect(swatch.style.backgroundColor).toBe('rgba(59, 130, 246, 0)');
    expect(swatch.style.borderColor).toBe('rgb(236, 75, 127)');
  });

  it('leaves a normal fill unchanged', () => {
    const { container } = render(
      <CategoricalLegend
        geometryType="Polygon"
        categories={[{ value: 'a', label: 'A', color: '#3b82f6' }]}
      />,
    );
    const swatch = container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(swatch.style.backgroundColor).toBe('rgb(59, 130, 246)');
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
});
