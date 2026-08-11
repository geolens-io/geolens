// feat(#1241): the chat preview → dataset snapshot. What matters here is that
// the client's FeatureCollection reaches the ORDINARY ingest path — upload,
// preview, commit — as a .geojson file, so the result is a dataset with
// nothing special about it downstream.
import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import {
  SaveChatPreviewDialog,
  chatPreviewFileName,
  chatPreviewUploadName,
} from '../SaveChatPreviewDialog';
import { ApiError } from '@/api/client';

const { uploadFile, previewFile, commitImport, getJobStatus } = vi.hoisted(() => ({
  uploadFile: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
  getJobStatus: vi.fn(),
}));

vi.mock('@/api/ingest', () => ({ uploadFile, previewFile, commitImport, getJobStatus }));

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
  getJobStatus.mockResolvedValue({ id: 'job-1', status: 'running' });
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

// feat(#1241 codex r5): graphemes are the wrong unit for a filesystem entry.
// 80 emoji plus the extension is 328 bytes, and local staging writes
// `<job-uuid>_<basename>` into a directory entry Linux caps at 255 — the
// upload then fails with ENAMETOOLONG, which the endpoint returns as a 500.
describe('chatPreviewUploadName', () => {
  const bytes = (value: string) => new TextEncoder().encode(value).length;

  it('leaves an ordinary name alone', () => {
    expect(chatPreviewUploadName('show me the latest earthquake.geojson')).toBe(
      'show me the latest earthquake.geojson',
    );
  });

  it('bounds a multibyte name that passed the grapheme cap', () => {
    const emoji = chatPreviewFileName('🌍'.repeat(120), 'Fallback');
    expect(bytes(emoji)).toBeGreaterThan(255);

    const uploaded = chatPreviewUploadName(emoji);
    expect(bytes(uploaded)).toBeLessThanOrEqual(120);
    expect(uploaded.endsWith('.geojson')).toBe(true);
  });

  it('keeps whole characters when it trims', () => {
    // A split surrogate pair would encode as U+FFFD and corrupt the name.
    const uploaded = chatPreviewUploadName(chatPreviewFileName('🌍'.repeat(120), 'Fallback'));
    expect(uploaded).toBe(`${'🌍'.repeat(28)}.geojson`);
  });

  it('bounds a long non-Latin name without losing the extension', () => {
    const uploaded = chatPreviewUploadName(chatPreviewFileName('東京'.repeat(40), 'Fallback'));
    expect(bytes(uploaded)).toBeLessThanOrEqual(120);
    expect(uploaded.endsWith('.geojson')).toBe(true);
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

  // feat(#1241 codex r2): the commit chain has three server steps and the
  // dialog stays open when one fails. Re-uploading on retry strands the first
  // staged job, and if a commit was accepted with only its response lost, a
  // fresh job would queue a SECOND dataset from the same answer. Resuming puts
  // the retry back on the job the server already has, where a repeat commit is
  // refused rather than duplicated.
  it('resumes the staged job on retry instead of uploading again', async () => {
    commitImport.mockRejectedValueOnce(new ApiError('Service unavailable', 503));
    renderDialog();

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalled());

    submit();
    await waitFor(() => expect(commitImport).toHaveBeenCalledTimes(2));
    expect(uploadFile).toHaveBeenCalledTimes(1);
    // The payload was already validated by the first preview; the retry picks
    // up at the step that failed.
    expect(previewFile).toHaveBeenCalledTimes(1);
    expect(commitImport.mock.calls.every(([jobId]) => jobId === 'job-1')).toBe(true);
    expect(toastSuccess).toHaveBeenCalled();
  });

  // feat(#1241 codex r3): the ambiguous case. A commit that reached the server
  // with only its response lost leaves a queued import behind, and the backend
  // refuses the repeat with 400 "Job already processed" — forever. Without
  // this the dialog can never close over a dataset that already exists.
  it('treats "job already processed" on a retry as the success it describes', async () => {
    commitImport
      .mockRejectedValueOnce(new ApiError('Network unavailable', 0))
      .mockRejectedValueOnce(new ApiError('Job already processed', 400));
    const { onOpenChange } = renderDialog();

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));

    submit();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(toastError).toHaveBeenCalledTimes(1);
  });

  // feat(#1241 codex r4): the backend answers a repeat commit with the same
  // 400 for every non-pending status, and a dispatch failure leaves the job
  // `failed` with its staged file deleted. Reading the 400 alone reported
  // success for an import that was never queued.
  it('does not claim success when the job the commit reached is dead', async () => {
    commitImport
      .mockRejectedValueOnce(new ApiError('Queue unavailable', 503))
      .mockRejectedValueOnce(new ApiError('Job already processed', 400));
    getJobStatus.mockResolvedValue({ id: 'job-1', status: 'failed' });
    const { onOpenChange } = renderDialog();

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(2));
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();

    // The dead job is abandoned rather than resumed forever: the next attempt
    // starts a fresh upload, which is the only thing that can succeed once the
    // staged file is gone.
    submit();
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
  });

  it('claims nothing when the job status cannot be read', async () => {
    commitImport
      .mockRejectedValueOnce(new ApiError('Network unavailable', 0))
      .mockRejectedValueOnce(new ApiError('Job already processed', 400));
    getJobStatus.mockRejectedValue(new ApiError('Not found', 404));
    const { onOpenChange } = renderDialog();

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(2));
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('does not swallow a 400 on the first commit attempt', async () => {
    commitImport.mockRejectedValue(new ApiError('Job has no file', 400));
    const { onOpenChange } = renderDialog();

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Job has no file'));
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('re-runs only the failed step when the preview is what failed', async () => {
    previewFile.mockRejectedValueOnce(new ApiError('Unable to preview file.', 422));
    renderDialog();

    submit();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(commitImport).not.toHaveBeenCalled();

    submit();
    await waitFor(() => expect(commitImport).toHaveBeenCalled());
    expect(uploadFile).toHaveBeenCalledTimes(1);
    expect(previewFile).toHaveBeenCalledTimes(2);
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
