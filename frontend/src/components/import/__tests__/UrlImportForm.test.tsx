/**
 * feat(#1705): UrlImportForm orchestration tests.
 *
 * The heavy children (ImportMetadataForm, ImportPreview, JobProgress) are
 * stubbed — these tests pin the step machine and the API call shapes:
 * fetch → preview → review → commit → tracking, error fallback to idle,
 * and layer_name threading for multi-layer containers.
 */
import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UrlImportForm } from '../UrlImportForm';
import type { CommitImportRequest } from '@/types/api';
import { clearUrlImport, peekUrlImport } from '@/api/url-import-session';
import { ApiError } from '@/api/client';

const mockUploadFromUrl = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();
const mockGetJobStatus = vi.fn();
const mockCancelJob = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
  getJobStatus: (...args: unknown[]) => mockGetJobStatus(...args),
  cancelJob: (...args: unknown[]) => mockCancelJob(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('../ImportPreview', () => ({
  ImportPreview: () => <div data-testid="import-preview" />,
}));

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: ({
    onCommit,
  }: {
    onCommit: (m: CommitImportRequest) => void;
  }) => (
    <button type="button" onClick={() => onCommit({ title: 'My Dataset' })}>
      commit-stub
    </button>
  ),
}));

vi.mock('../JobProgress', () => ({
  JobProgress: ({ jobId }: { jobId: string }) => (
    <div data-testid="job-progress">{jobId}</div>
  ),
}));

const VECTOR_PREVIEW = {
  job_id: 'job-1',
  source_filename: 'roads.geojson',
  columns: [{ name: 'id', type: 'Integer' }],
  crs: 4326,
  geometry_type: 'LineString',
  feature_count: 10,
  sample_rows: [],
  layer_name: 'roads',
  layers: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  // fix(#1708 codex r19): the URL-import session is module-owned so it can
  // outlive an unmount (that is the point). Tests must therefore start from
  // a clean one, or a leftover session resumes into the next test's mount.
  clearUrlImport();
});

afterEach(() => {
  clearUrlImport();
});

async function fetchUrl(url: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('urlImport.label'), url);
  await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
  return user;
}

describe('UrlImportForm', () => {
  test('fetch button disabled until a URL is typed', () => {
    render(<UrlImportForm />);
    expect(screen.getByRole('button', { name: 'urlImport.fetch' })).toBeDisabled();
  });

  test('happy path: fetch → preview → review → commit → tracking', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockResolvedValue(VECTOR_PREVIEW);
    mockCommitImport.mockResolvedValue({ job_id: 'job-1', status: 'queued' });

    render(<UrlImportForm />);
    const user = await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(screen.getByTestId('import-preview')).toBeInTheDocument(),
    );
    expect(mockUploadFromUrl).toHaveBeenCalledWith(
      'https://files.example.test/roads.geojson',
      undefined,
    );
    expect(mockPreviewFile).toHaveBeenCalledWith('job-1');

    await user.click(screen.getByRole('button', { name: 'commit-stub' }));

    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toHaveTextContent('job-1'),
    );
    // Single-layer file: no layer_name in the commit body.
    expect(mockCommitImport).toHaveBeenCalledWith('job-1', {
      title: 'My Dataset',
    });
  });

  test('filename override is passed through', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-2', status: 'pending' });
    mockPreviewFile.mockResolvedValue(VECTOR_PREVIEW);

    render(<UrlImportForm />);
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText('urlImport.label'),
      'https://files.example.test/download?id=7',
    );
    await user.type(
      screen.getByLabelText('urlImport.filenameLabel'),
      'points.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));

    await waitFor(() =>
      expect(mockUploadFromUrl).toHaveBeenCalledWith(
        'https://files.example.test/download?id=7',
        'points.geojson',
      ),
    );
  });

  test('fetch failure returns to idle with the error shown', async () => {
    mockUploadFromUrl.mockRejectedValue(new Error('boom'));

    render(<UrlImportForm />);
    await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(screen.getByText('urlImport.fetchFailed')).toBeInTheDocument(),
    );
    // Back on the idle form.
    expect(screen.getByLabelText('urlImport.label')).toBeInTheDocument();
    expect(mockPreviewFile).not.toHaveBeenCalled();
  });

  // fix(review #1800 P2 on #1778): a preview failure whose job is confirmed
  // gone (404/410 on the preview call itself) is genuinely terminal — clear
  // the session, same as a fetch failure.
  test('a preview failure that is 404 on the job releases the module session', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValue(new ApiError('Job not found', 404));

    render(<UrlImportForm />);
    await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(screen.getByText('Job not found')).toBeInTheDocument(),
    );
    expect(peekUrlImport()).toBeNull();
  });

  // fix(review #1800 P2 on #1778): #1778's original fix cleared the session
  // unconditionally on ANY preview failure, which threw away the only
  // client-side copy of the staged job id — a transient failure (GDAL
  // timeout, network blip) leaves the job right where it was (`pending`).
  // Clearing then made a same-URL resubmit re-download server-side and
  // orphaned the original staged job for the sweeper. A non-terminal
  // failure must keep the session and offer explicit Retry/Cancel actions
  // instead.
  test('a transient preview failure (job still pending) keeps the session and the job id', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValueOnce(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });

    render(<UrlImportForm />);
    await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'urlImport.retryPreview' })).toBeInTheDocument(),
    );
    expect(peekUrlImport()?.jobId).toBe('job-1');
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);
  });

  // fix(review #1800 P2 round 3): the url/filename fields stayed editable
  // next to the recovery actions while a job was retained — changing a
  // value and clicking Fetch started a SECOND session, replacing the
  // module-level `current` (startUrlImport can no longer recognize the
  // old key) and orphaning the retained job's staged file with nothing
  // left to reach it. Ordinary submission is disabled while a job is
  // retained; the two recovery actions are the only way forward.
  test('a retained job disables ordinary submission (button, inputs, and Enter-to-submit)', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValueOnce(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });

    const { container } = render(<UrlImportForm />);
    await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'urlImport.retryPreview' })).toBeInTheDocument(),
    );
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);

    // UI-level: the button and both fields are disabled.
    expect(screen.getByRole('button', { name: 'urlImport.fetch' })).toBeDisabled();
    expect(screen.getByLabelText('urlImport.label')).toBeDisabled();
    expect(screen.getByLabelText('urlImport.filenameLabel')).toBeDisabled();

    // Pin: submitting a DIFFERENT url (bypassing the disabled button via a
    // direct form submit — the same defense-in-depth shape every other
    // guard in this component uses) does not call the download endpoint,
    // and the retained job id is unchanged.
    fireEvent.change(screen.getByLabelText('urlImport.label'), {
      target: { value: 'https://files.example.test/different.geojson' },
    });
    const form = container.querySelector('form');
    expect(form).not.toBeNull();
    fireEvent.submit(form!);

    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);
    expect(peekUrlImport()?.jobId).toBe('job-1');
  });

  // Pin: "Cancel and start over" clears jobId, which re-enables the form —
  // the only way back to ordinary submission.
  test('Cancel and start over re-enables the form', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValue(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockCancelJob.mockResolvedValue({ status: 'cancelled' });

    const user = userEvent.setup();
    render(<UrlImportForm />);
    await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }));

    // reset() also clears the url field, so the fetch button stays
    // disabled for the OTHER reason (nothing typed) until this proves the
    // fields themselves are enabled again by typing into them.
    await waitFor(() =>
      expect(screen.getByLabelText('urlImport.label')).not.toBeDisabled(),
    );
    expect(screen.getByLabelText('urlImport.filenameLabel')).not.toBeDisabled();
    await user.type(screen.getByLabelText('urlImport.label'), 'https://files.example.test/next.geojson');
    expect(screen.getByRole('button', { name: 'urlImport.fetch' })).not.toBeDisabled();
  });

  // Pin: "Cancel and start over" cancels the staged job through the
  // existing cancel endpoint, then clears the session.
  test('Cancel and start over cancels the staged job and clears the session', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValue(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockCancelJob.mockResolvedValue({ status: 'cancelled' });

    render(<UrlImportForm />);
    const user = await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }));

    await waitFor(() => expect(mockCancelJob).toHaveBeenCalledWith('job-1'));
    await waitFor(() =>
      expect(screen.getByLabelText('urlImport.label')).toBeInTheDocument(),
    );
    expect(peekUrlImport()).toBeNull();
  });

  // fix(review #1800 P2 round 2): the cancel handler used to reset
  // UNCONDITIONALLY once cancelJob settled, success or failure — a failed
  // cancel (job still pending server-side with its staged file) cleared
  // the only client-side copy of the job id anyway, orphaning it with no
  // way back short of the sweep. A 500 is not confirmation the job is
  // gone: keep the recovery state and show the error instead.
  test('a failed cancel (500) keeps the job id and the recovery actions, and shows the error', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValue(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockCancelJob.mockRejectedValue(new ApiError('Server error', 500));

    render(<UrlImportForm />);
    const user = await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }));

    await waitFor(() => expect(screen.getByText('Server error')).toBeInTheDocument());
    expect(
      screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'urlImport.retryPreview' })).toBeInTheDocument();
    expect(peekUrlImport()?.jobId).toBe('job-1');
  });

  // Pin: when the cancel call itself reports the job already gone (404),
  // there is nothing left to keep — start over.
  test('a cancel that reports the job already gone (404) resets the form', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValue(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockCancelJob.mockRejectedValue(new ApiError('Job not found', 404));

    render(<UrlImportForm />);
    const user = await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.cancelAndStartOver' }));

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'urlImport.cancelAndStartOver' }),
      ).not.toBeInTheDocument(),
    );
    expect(peekUrlImport()).toBeNull();
  });

  test('multi-layer preview shows the layer picker and threads layer_name', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-3', status: 'pending' });
    mockPreviewFile.mockResolvedValue({
      ...VECTOR_PREVIEW,
      layer_name: 'layer_a',
      layers: [
        { name: 'layer_a', feature_count: 5, field_count: 2 },
        { name: 'layer_b', feature_count: 9, field_count: 3 },
      ],
    });
    mockCommitImport.mockResolvedValue({ job_id: 'job-3', status: 'queued' });

    render(<UrlImportForm />);
    const user = await fetchUrl('https://files.example.test/multi.gpkg');

    await waitFor(() =>
      expect(screen.getByLabelText('urlImport.layerLabel')).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() =>
      expect(mockCommitImport).toHaveBeenCalledWith('job-3', {
        title: 'My Dataset',
        layer_name: 'layer_a',
      }),
    );
  });
});
