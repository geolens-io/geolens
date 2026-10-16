import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BulkReviewList } from '../BulkReviewList';
import type { FileEntry } from '@/types/api';

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: () => <div data-testid="import-metadata-form" />,
}));

function entryWithLayers(
  layers: { name: string; feature_count?: number | null; field_count?: number | null }[],
): FileEntry {
  return {
    id: 'entry-1',
    file: null,
    fileName: 'book.xlsx',
    status: 'preview',
    jobId: 'job-1',
    previewData: {
      job_id: 'job-1',
      source_filename: 'book.xlsx',
      columns: [],
      geometry_type: null,
      crs: null,
      layer_name: 'Sheet1',
      layers,
      sample_rows: [],
      feature_count: null,
      detected_geometry_columns: null,
    },
    error: null,
    submittedTitle: null,
    submittedVisibility: null,
    submittedKind: null,
  };
}

describe('BulkReviewList sheet options', () => {
  beforeAll(() => {
    Element.prototype.hasPointerCapture = vi.fn(() => false);
    Element.prototype.releasePointerCapture = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('shows zero counts for a layer whose preview omits them', async () => {
    render(
      <BulkReviewList
        entries={[entryWithLayers([{ name: 'Sheet1' }, { name: 'Sheet2', feature_count: 7, field_count: 2 }])]}
        onCommitSingle={() => {}}
        onCommitAll={() => {}}
        onRemove={() => {}}
        isCommitting={false}
      />,
    );

    await userEvent.click(screen.getByRole('combobox', { name: /sheet|layer/i }));

    expect(await screen.findByRole('option', { name: /Sheet1.*0 rows.*0 columns/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Sheet2.*7 rows.*2 columns/ })).toBeInTheDocument();
  });
});
