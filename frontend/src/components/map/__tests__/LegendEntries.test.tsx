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
