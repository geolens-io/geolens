import { render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BulkReviewList } from '../BulkReviewList';
import type { FileEntry, FilePreviewResponse } from '@/types/api';

function entry(id: string, fileName: string): FileEntry {
  const preview: FilePreviewResponse = {
    job_id: `job-${id}`,
    source_filename: fileName,
    columns: [{ name: 'latitude', type: 'Real' }],
    geometry_type: null,
    crs: null,
    layer_name: fileName,
    layers: [],
    sample_rows: [],
    feature_count: 2,
    detected_geometry_columns: null,
  };
  return {
    id,
    file: null,
    fileName,
    status: 'preview',
    jobId: `job-${id}`,
    previewData: preview,
    error: null,
  };
}

it('keeps labels, controls, and radio groups scoped to the second expanded real form', async () => {
  const user = userEvent.setup();
  render(<BulkReviewList
    entries={[entry('one', 'first.csv'), entry('two', 'second.csv')]}
    onCommitSingle={vi.fn()}
    onCommitAll={vi.fn()}
    onRemove={vi.fn()}
    isCommitting={false}
  />);

  await user.click(screen.getByRole('button', { name: 'Show or hide details for second.csv' }));
  const firstPanel = document.getElementById('review-details-one')!;
  const secondPanel = document.getElementById('review-details-two')!;
  const firstName = within(firstPanel).getByLabelText('Name *');
  const secondName = within(secondPanel).getByLabelText('Name *');
  const secondMode = within(secondPanel).getByLabelText('Mode');

  expect(firstPanel).toHaveAttribute('hidden');
  expect(secondPanel).not.toHaveAttribute('hidden');
  expect(firstName.id).not.toBe(secondName.id);
  expect(within(secondPanel).getByText('Name *', { selector: 'label' })).toHaveAttribute('for', secondName.id);
  expect(within(secondPanel).getByText('Mode', { selector: 'label' })).toHaveAttribute('for', secondMode.id);
  expect(document.querySelectorAll(`[id="${secondName.id}"]`)).toHaveLength(1);

  await user.clear(secondName);
  await user.type(secondName, 'Reviewed second');
  expect(firstName).toHaveValue('first');
  expect(secondName).toHaveValue('Reviewed second');
});
