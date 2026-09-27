import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BulkReviewList } from '../BulkReviewList';
import type { FileEntry, TilesetPreviewResponse } from '@/types/api';

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: () => <button type="button">Import reviewed dataset</button>,
}));

const preview: TilesetPreviewResponse = {
  job_id: 'job-1',
  source_filename: 'campus.zip',
  version: '1.1',
  geometric_error: 16,
  bounding_volume: 'region',
  extent_bbox: [-1, -1, 1, 1],
  unpacked_bytes: 2048,
  entry_count: 3,
};

function entry(id: string, name: string): FileEntry {
  return {
    id,
    file: null,
    fileName: name,
    status: 'preview',
    jobId: `job-${id}`,
    previewData: { ...preview, source_filename: name },
    error: null,
  };
}

function list(entries: FileEntry[], onCommitAll = vi.fn(), onRemove = vi.fn()) {
  render(
    <BulkReviewList
      entries={entries}
      onCommitSingle={vi.fn()}
      onCommitAll={onCommitAll}
      onRemove={onRemove}
      isCommitting={false}
    />,
  );
}

describe('BulkReviewList review actions', () => {
  it('keeps expansion and removal as separately named keyboard controls', async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    list([entry('one', 'campus.zip')], vi.fn(), onRemove);

    const expand = screen.getByRole('button', { name: 'Show or hide details for campus.zip' });
    const remove = screen.getByRole('button', { name: 'Remove campus.zip' });
    expect(expand).toHaveAttribute('aria-expanded', 'true');
    expect(expand).toHaveAttribute('aria-controls', 'review-details-one');
    expect(expand).not.toContainElement(remove);

    expand.focus();
    await user.keyboard('{Enter}');
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    expect(onRemove).not.toHaveBeenCalled();

    remove.focus();
    await user.keyboard(' ');
    expect(onRemove).toHaveBeenCalledWith('one');
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'Import All with Defaults' })).not.toBeInTheDocument();
  });

  it('requires explicit confirmation before a batch discards reviewed fields', async () => {
    const user = userEvent.setup();
    const onCommitAll = vi.fn();
    list([entry('one', 'campus.zip'), entry('two', 'city.zip')], onCommitAll);

    await user.click(screen.getByRole('button', { name: 'Import All with Defaults' }));
    expect(onCommitAll).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toHaveTextContent('All edits in the review forms');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCommitAll).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Import All with Defaults' }));
    await user.click(screen.getByRole('button', { name: 'Import with defaults' }));
    expect(onCommitAll).toHaveBeenCalledOnce();
  });
});
