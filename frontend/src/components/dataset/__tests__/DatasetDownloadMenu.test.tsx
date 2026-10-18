import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { render, screen, waitFor } from '@/test/test-utils';
import { downloadExport } from '@/api/datasets';
import { DatasetDownloadMenu } from '@/components/dataset/DatasetDownloadMenu';

vi.mock('@/api/datasets', () => ({ downloadExport: vi.fn() }));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

async function chooseGeoJson() {
  const user = userEvent.setup();
  render(<DatasetDownloadMenu datasetId="ds-1" datasetName="Parks" geometryType="Polygon" />);
  await user.click(screen.getByRole('button', { name: 'Download' }));
  await user.click(await screen.findByRole('menuitem', { name: 'GeoJSON' }));
}

describe('DatasetDownloadMenu', () => {
  beforeEach(() => vi.clearAllMocks());

  it('saves the export under the dataset title', async () => {
    vi.mocked(downloadExport).mockResolvedValue(undefined);
    await chooseGeoJson();

    expect(downloadExport).toHaveBeenCalledWith('ds-1', 'geojson', 'Parks.geojson');
  });

  it('shows the API error message when the export fails', async () => {
    vi.mocked(downloadExport).mockRejectedValue(new Error('You do not have access to export this dataset.'));
    await chooseGeoJson();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('You do not have access to export this dataset.'),
    );
  });

  it('falls back to a generic message for a non-Error failure', async () => {
    vi.mocked(downloadExport).mockRejectedValue('boom');
    await chooseGeoJson();

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Export failed'));
  });
});
