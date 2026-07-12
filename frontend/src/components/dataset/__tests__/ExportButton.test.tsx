import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ExportButton } from '../ExportButton';

vi.mock('@/api/datasets', () => ({
  downloadExport: vi.fn(),
}));

// fix(#438): DS-08 — the format picker is now a Radix Select, whose options only
// mount once the trigger is opened, and which needs these pointer/scroll APIs
// that jsdom lacks.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

describe('ExportButton', () => {
  it('renders all 5 format options by default', async () => {
    const user = userEvent.setup();
    render(<ExportButton datasetId="ds-1" datasetName="test" />);

    await user.click(screen.getByRole('combobox'));
    const options = await screen.findAllByRole('option');
    expect(options).toHaveLength(5);
    const labels = options.map((o) => o.textContent);
    expect(labels).toEqual(
      expect.arrayContaining(['GeoPackage', 'GeoJSON', 'Shapefile', 'CSV', 'GeoParquet']),
    );
  });

  it('shows a DuckDB snippet when GeoParquet is selected', async () => {
    const user = userEvent.setup();
    render(<ExportButton datasetId="ds-1" datasetName="rivers" />);

    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: 'GeoParquet' }));

    expect(screen.getByText(/LOAD spatial/)).toBeInTheDocument();
    expect(screen.getByText(/rivers\.parquet/)).toBeInTheDocument();
  });

  it('sanitizes quotes and path separators in the DuckDB snippet filename', async () => {
    const user = userEvent.setup();
    render(<ExportButton datasetId="ds-1" datasetName="Bob's Roads/2026" />);

    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: 'GeoParquet' }));

    // Path separator -> _, single quote doubled -> valid DuckDB string literal
    // that matches the browser-saved filename.
    expect(screen.getByText(/Bob''s Roads_2026\.parquet/)).toBeInTheDocument();
  });

  it('limits table datasets to CSV export', async () => {
    const user = userEvent.setup();
    render(<ExportButton datasetId="ds-1" datasetName="test" recordType="table" />);

    // The trigger already shows CSV as the only/selected format.
    expect(screen.getByRole('combobox')).toHaveTextContent('CSV');
    await user.click(screen.getByRole('combobox'));
    const options = await screen.findAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent('CSV');
  });
});
