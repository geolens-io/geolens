import { render, screen } from '@/test/test-utils';
import { ExportButton } from '../ExportButton';

vi.mock('@/api/datasets', () => ({
  downloadExport: vi.fn(),
}));

describe('ExportButton', () => {
  it('renders all 4 format options by default', () => {
    render(<ExportButton datasetId="ds-1" datasetName="test" />);

    const select = screen.getByRole('combobox');
    const options = Array.from(select.querySelectorAll('option'));
    expect(options).toHaveLength(4);
    const values = options.map((o) => o.value);
    expect(values).toContain('gpkg');
    expect(values).toContain('geojson');
    expect(values).toContain('shp');
    expect(values).toContain('csv');
  });

  it('limits table datasets to CSV export', () => {
    render(<ExportButton datasetId="ds-1" datasetName="test" recordType="table" />);

    const select = screen.getByRole('combobox');
    const options = Array.from(select.querySelectorAll('option'));
    expect(options).toHaveLength(1);
    const values = options.map((o) => o.value);
    expect(values).toContain('csv');
    expect(select).toHaveValue('csv');
  });
});
