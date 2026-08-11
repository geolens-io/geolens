// feat(#1241): the chat preview → dataset snapshot. What matters here is that
// the client's FeatureCollection reaches the ORDINARY ingest path — upload,
// preview, commit — as a .geojson file, so the result is a dataset with
// nothing special about it downstream.
import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { SaveChatPreviewDialog, chatPreviewFileName } from '../SaveChatPreviewDialog';
import { ApiError } from '@/api/client';

const { uploadFile, previewFile, commitImport } = vi.hoisted(() => ({
  uploadFile: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
}));

vi.mock('@/api/ingest', () => ({ uploadFile, previewFile, commitImport }));

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('sonner', () => ({ toast: { success: toastSuccess, error: toastError } }));

const geojson: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [1, 2] },
      properties: { magnitude: 5.5 },
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  uploadFile.mockResolvedValue({ job_id: 'job-1' });
  previewFile.mockResolvedValue({ job_id: 'job-1' });
  commitImport.mockResolvedValue({ job_id: 'job-1', status: 'pending', message: 'Import queued' });
});

function renderDialog(props: Partial<React.ComponentProps<typeof SaveChatPreviewDialog>> = {}) {
  const onOpenChange = vi.fn();
  render(
    <SaveChatPreviewDialog
      open
      onOpenChange={onOpenChange}
      geojson={geojson}
      prompt="show me the latest earthquake"
      {...props}
    />,
  );
  return { onOpenChange };
}

function submit() {
  fireEvent.click(screen.getByRole('button', { name: /import dataset/i }));
}

describe('chatPreviewFileName', () => {
  it('suggests the prompt as the file name', () => {
    expect(chatPreviewFileName('show me the latest earthquake', 'Fallback')).toBe(
      'show me the latest earthquake.geojson',
    );
  });

  // The form seeds its title field with stripExtension(defaultName), which cuts
  // at the LAST dot — so a prompt carrying its own dots only survives because
  // what we hand it is a file name, not a bare title.
  it('keeps a prompt that contains dots intact through the extension', () => {
    expect(chatPreviewFileName('buildings over 3.5m', 'Fallback')).toBe(
      'buildings over 3.5m.geojson',
    );
  });

  it('collapses whitespace and drops path separators', () => {
    expect(chatPreviewFileName('  parks\n/ gardens  ', 'Fallback')).toBe('parks gardens.geojson');
  });

  it('falls back when there is no prompt to name it after', () => {
    expect(chatPreviewFileName(undefined, 'Chat query result')).toBe('Chat query result.geojson');
    expect(chatPreviewFileName('   ', 'Chat query result')).toBe('Chat query result.geojson');
  });

  it('caps a rambling prompt instead of making a 900-character name', () => {
    const name = chatPreviewFileName('a'.repeat(400), 'Fallback');
    expect(name).toBe(`${'a'.repeat(80)}.geojson`);
  });
});

describe('SaveChatPreviewDialog', () => {
  it('prefills the name from the chat prompt', () => {
    renderDialog();
    expect(screen.getByLabelText(/name/i)).toHaveValue('show me the latest earthquake');
  });

  it('says the dataset is a snapshot, not a live query', () => {
    renderDialog();
    expect(screen.getByText(/snapshot of this answer, not a live query/i)).toBeInTheDocument();
  });

  it('pushes the preview through upload → preview → commit', async () => {
    const { onOpenChange } = renderDialog();
    submit();

    await waitFor(() => expect(commitImport).toHaveBeenCalled());

    const file = uploadFile.mock.calls[0][0] as File;
    expect(file.name).toBe('show me the latest earthquake.geojson');
    await expect(file.text()).resolves.toBe(JSON.stringify(geojson));

    // Preview is not skippable: it is where an unreadable or over-budget
    // payload is rejected, before a job is queued.
    expect(previewFile).toHaveBeenCalledWith('job-1');
    expect(commitImport).toHaveBeenCalledWith(
      'job-1',
      expect.objectContaining({ title: 'show me the latest earthquake', visibility: 'private' }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it('commits the edited name, not the suggestion', async () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Quakes today' } });
    submit();

    await waitFor(() => expect(commitImport).toHaveBeenCalled());
    expect(commitImport).toHaveBeenCalledWith('job-1', expect.objectContaining({ title: 'Quakes today' }));
    // The upload still carries the suggested file name — renaming the dataset
    // is not renaming the file it came from.
    expect((uploadFile.mock.calls[0][0] as File).name).toBe('show me the latest earthquake.geojson');
  });

  it('keeps the dialog open and surfaces the reason when the upload fails', async () => {
    uploadFile.mockRejectedValue(new ApiError('File too large', 413));
    const { onOpenChange } = renderDialog();
    submit();

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('File too large'));
    expect(previewFile).not.toHaveBeenCalled();
    expect(commitImport).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('never commits a payload the ingest preview rejected', async () => {
    previewFile.mockRejectedValue(new ApiError('Unable to preview file.', 422));
    renderDialog();
    submit();

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(commitImport).not.toHaveBeenCalled();
  });

  it('uploads once when the submit button is double-clicked', async () => {
    renderDialog();
    const button = screen.getByRole('button', { name: /import dataset/i });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(commitImport).toHaveBeenCalled());
    expect(uploadFile).toHaveBeenCalledTimes(1);
  });
});
