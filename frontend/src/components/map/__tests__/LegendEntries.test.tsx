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
