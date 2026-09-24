/** A staged tileset is reviewed by its tileset facts and committed with the common form fields. */
import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BulkReviewList } from '../BulkReviewList';
import type { CommitImportRequest, FileEntry, TilesetPreviewResponse } from '@/types/api';

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: ({
    onCommit,
    isTileset,
    detectedCrs,
  }: {
    onCommit: (request: CommitImportRequest) => void;
    isTileset?: boolean;
    detectedCrs: number | null;
  }) => (
    <button
      type="button"
      data-testid="metadata-form"
      data-tileset={String(Boolean(isTileset))}
      data-crs={String(detectedCrs)}
      onClick={() => onCommit({ title: 'Campus', visibility: 'private', srid_override: null })}
    >
      Commit
    </button>
  ),
}));

const PREVIEW: TilesetPreviewResponse = {
  job_id: 'job-1',
  source_filename: 'campus.zip',
  version: '1.1',
  geometric_error: 16,
  bounding_volume: 'region',
  extent_bbox: [-1, -1, 1, 1],
  unpacked_bytes: 2048,
  entry_count: 3,
};

function entry(preview: TilesetPreviewResponse = PREVIEW): FileEntry {
  return {
    id: 'entry-1',
    file: null,
    fileName: 'campus.zip',
    status: 'preview',
    jobId: 'job-1',
    previewData: preview,
    error: null,
  };
}

function renderList(entries: FileEntry[], onCommitSingle = vi.fn()) {
  render(
    <BulkReviewList
      entries={entries}
      onCommitSingle={onCommitSingle}
      onCommitAll={vi.fn()}
      onRemove={vi.fn()}
      isCommitting={false}
    />,
  );
  return onCommitSingle;
}

describe('BulkReviewList with a tileset', () => {
  it('shows the tileset summary, facts and kind rather than a vector reading', () => {
    renderList([entry()]);

    expect(screen.getByText('3D Tiles 1.1 · 2 KB · Region')).toBeInTheDocument();
    expect(screen.getByText('Tileset')).toBeInTheDocument();
    expect(screen.getByText('(-1.0000, -1.0000) to (1.0000, 1.0000)')).toBeInTheDocument();
    expect(screen.getByText('3DT')).toBeInTheDocument();
    expect(screen.getByText('1 file · 1 tileset')).toBeInTheDocument();
    expect(screen.queryByText('Geometry & projection')).not.toBeInTheDocument();
  });

  it('says a box volume gives no extent', () => {
    renderList([entry({ ...PREVIEW, bounding_volume: 'box', extent_bbox: null })]);

    expect(screen.getByText('none; only a region gives one')).toBeInTheDocument();
  });

  it('commits the form as a tileset, with no CRS and no layer', async () => {
    const onCommitSingle = renderList([entry()]);
    const form = screen.getByTestId('metadata-form');

    expect(form).toHaveAttribute('data-tileset', 'true');
    expect(form).toHaveAttribute('data-crs', 'null');
    await userEvent.setup().click(form);

    expect(onCommitSingle).toHaveBeenCalledWith('entry-1', {
      title: 'Campus',
      visibility: 'private',
      srid_override: null,
    });
  });
});
