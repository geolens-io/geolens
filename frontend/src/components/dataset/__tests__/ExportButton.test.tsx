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
  it('renders all 4 format options by default', async () => {
    const user = userEvent.setup();
    render(<ExportButton datasetId="ds-1" datasetName="test" />);

    await user.click(screen.getByRole('combobox'));
    const options = await screen.findAllByRole('option');
    expect(options).toHaveLength(4);
    const labels = options.map((o) => o.textContent);
    expect(labels).toEqual(
      expect.arrayContaining(['GeoPackage', 'GeoJSON', 'Shapefile', 'CSV']),
    );
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
