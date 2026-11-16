import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BulkReviewList } from '../BulkReviewList';
import type { CommitImportRequest, FileEntry } from '@/types/api';

vi.mock('@/hooks/use-settings', () => ({
  useCanSetPublicVisibility: () => true,
}));

const defaultsRequest: CommitImportRequest = {
  title: 'places',
  x_column: 'lon',
  y_column: 'lat',
};

function csvEntry(status: FileEntry['status'], commitRequest?: CommitImportRequest): FileEntry {
  return {
    id: 'entry-1',
    file: null,
    fileName: 'places.csv',
    status,
    jobId: 'job-1',
    previewData: {
      job_id: 'job-1',
      source_filename: 'places.csv',
      columns: [
        { name: 'lon', type: 'Real' },
        { name: 'lat', type: 'Real' },
      ],
      geometry_type: null,
      crs: null,
      layer_name: 'places',
      layers: [],
      sample_rows: [],
      feature_count: 20,
      detected_geometry_columns: { x_column: 'lon', y_column: 'lat', wkt_column: null },
    },
    commitRequest,
    error: null,
    submittedTitle: null,
    submittedVisibility: null,
    submittedKind: null,
  } as FileEntry;
}

function list(entry: FileEntry) {
  return (
    <BulkReviewList
      entries={[entry]}
      onCommitSingle={() => {}}
      onCommitAll={() => {}}
      onRemove={() => {}}
      isCommitting={false}
    />
  );
}

describe('BulkReviewList draft precedence', () => {
  beforeAll(() => {
    Element.prototype.hasPointerCapture = vi.fn(() => false);
    Element.prototype.setPointerCapture = vi.fn();
    Element.prototype.releasePointerCapture = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('shows what a defaults batch submitted, not the draft it ignored', async () => {
    const user = userEvent.setup();
    const { rerender } = render(list(csvEntry('preview')));

    await user.click(screen.getByLabelText('Mode'));
    await user.click(await screen.findByRole('option', { name: 'Import as non-spatial' }));
    expect(screen.getByText(/20 features/)).toHaveTextContent(/non-spatial.*no CRS/i);

    rerender(list(csvEntry('committing', defaultsRequest)));
    expect(screen.getByText(/20 features/)).toHaveTextContent('EPSG:4326');

    rerender(list(csvEntry('commit-failed', defaultsRequest)));
    expect(screen.getByText(/20 features/)).toHaveTextContent('EPSG:4326');
    expect(screen.getByText('VEC')).toBeInTheDocument();
  });
});
