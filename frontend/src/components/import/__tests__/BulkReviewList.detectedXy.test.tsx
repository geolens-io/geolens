import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { BulkReviewList } from '../BulkReviewList';
import type { CommitImportRequest, FileEntry } from '@/types/api';

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: ({
    onGeometryDraftChange,
  }: {
    onGeometryDraftChange?: (d: { geometry: 'point' | 'wkt' | null; srid: number | null }) => void;
  }) => (
    <div data-testid="import-metadata-form">
      <button onClick={() => onGeometryDraftChange?.({ geometry: null, srid: null })}>draft-none</button>
      <button onClick={() => onGeometryDraftChange?.({ geometry: 'point', srid: 27700 })}>draft-27700</button>
    </div>
  ),
}));

function csvEntry(
  detected: { x_column: string | null; y_column: string | null; wkt_column: string | null } | null,
  commitRequest?: CommitImportRequest,
): FileEntry {
  return {
    id: 'entry-1',
    file: null,
    fileName: 'places.csv',
    status: 'preview',
    jobId: 'job-1',
    previewData: {
      job_id: 'job-1',
      source_filename: 'places.csv',
      columns: [],
      geometry_type: null,
      crs: null,
      layer_name: 'places',
      layers: [],
      sample_rows: [],
      feature_count: 20,
      detected_geometry_columns: detected,
    },
    commitRequest,
    error: null,
    submittedTitle: null,
    submittedVisibility: null,
    submittedKind: null,
  } as FileEntry;
}

function renderEntry(entry: FileEntry) {
  render(
    <BulkReviewList
      entries={[entry]}
      onCommitSingle={() => {}}
      onCommitAll={() => {}}
      onRemove={() => {}}
      isCommitting={false}
    />,
  );
}

describe('BulkReviewList tabular summary', () => {
  it('describes a table with detected x/y columns as points in EPSG:4326', () => {
    renderEntry(csvEntry({ x_column: 'lon', y_column: 'lat', wkt_column: null }));

    const summary = screen.getByText(/20 features/);
    expect(summary).toHaveTextContent('EPSG:4326');
    expect(summary).not.toHaveTextContent(/non-spatial|no CRS/i);
    expect(screen.queryAllByText(/non-spatial/i)).toHaveLength(0);
    expect(screen.getAllByText('Point (from columns)')).toHaveLength(1);
  });

  it('still calls a table without detected geometry columns non-spatial', () => {
    renderEntry(csvEntry(null));

    expect(screen.getByText(/20 features/)).toHaveTextContent(/non-spatial.*no CRS/i);
  });

  it('follows a request that imports the table as non-spatial', () => {
    renderEntry(
      csvEntry(
        { x_column: 'lon', y_column: 'lat', wkt_column: null },
        { title: 'places' } as CommitImportRequest,
      ),
    );

    expect(screen.getByText(/20 features/)).toHaveTextContent(/non-spatial.*no CRS/i);
  });

  it('follows the form draft when it switches to non-spatial', async () => {
    renderEntry(csvEntry({ x_column: 'lon', y_column: 'lat', wkt_column: null }));

    await userEvent.click(screen.getByText('draft-none'));

    expect(screen.getByText(/20 features/)).toHaveTextContent(/non-spatial.*no CRS/i);
  });

  it('shows the draft SRID override on the summary and the CRS row', async () => {
    renderEntry(csvEntry({ x_column: 'lon', y_column: 'lat', wkt_column: null }));

    await userEvent.click(screen.getByText('draft-27700'));

    expect(screen.getByText(/20 features/)).toHaveTextContent('EPSG:27700');
    expect(screen.getByText('EPSG:27700', { exact: false, selector: 'dd' })).toBeInTheDocument();
  });

  it('shows the SRID override of a submitted request', () => {
    renderEntry(
      csvEntry(
        { x_column: 'lon', y_column: 'lat', wkt_column: null },
        { title: 'places', x_column: 'lon', y_column: 'lat', srid_override: 27700 } as CommitImportRequest,
      ),
    );

    expect(screen.getByText(/20 features/)).toHaveTextContent('EPSG:27700');
  });

  it('labels the kind badge from the same geometry as the summary', async () => {
    renderEntry(csvEntry({ x_column: 'lon', y_column: 'lat', wkt_column: null }));
    expect(screen.getByText('VEC')).toBeInTheDocument();

    await userEvent.click(screen.getByText('draft-none'));

    expect(screen.getByText('TAB')).toBeInTheDocument();
    expect(screen.queryByText('VEC')).not.toBeInTheDocument();
  });

  it('shows an SRID override on a file with native geometry and no CRS', async () => {
    const entry = csvEntry(null);
    Object.assign(entry.previewData as object, { geometry_type: 'Point', crs: null });
    renderEntry(entry);
    expect(screen.getByText(/20 features/)).toHaveTextContent('no CRS');

    await userEvent.click(screen.getByText('draft-27700'));

    expect(screen.getByText(/20 features/)).toHaveTextContent('EPSG:27700');
    expect(screen.getByText('EPSG:27700', { exact: false, selector: 'dd' })).toBeInTheDocument();
  });
});
