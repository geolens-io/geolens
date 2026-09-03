/**
 * feat(#1705): UrlImportForm orchestration tests.
 *
 * The heavy children (ImportMetadataForm, ImportPreview, JobProgress) are
 * stubbed — these tests pin the step machine and the API call shapes:
 * fetch → preview → review → commit → tracking, error fallback to idle,
 * and layer_name threading for multi-layer containers.
 */
import { render, screen, waitFor } from '@/test/test-utils';
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
  test('a transient preview failure (job still pending) keeps the session and blocks a re-download on resubmit', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
    mockPreviewFile.mockRejectedValueOnce(new ApiError('Preview timed out', 0));
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-1', status: 'pending' });

    render(<UrlImportForm />);
    const user = await fetchUrl('https://files.example.test/roads.geojson');

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'urlImport.retryPreview' })).toBeInTheDocument(),
    );
    expect(peekUrlImport()?.jobId).toBe('job-1');
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);

    // Pin: resubmitting the SAME url does not call the download endpoint
    // again (startUrlImport reuses the fulfilled same-key session). The
    // url field still holds the original value (it survives a preview
    // failure), so clicking Fetch again resubmits it unchanged.
    mockPreviewFile.mockResolvedValueOnce(VECTOR_PREVIEW);
    expect(screen.getByLabelText('urlImport.label')).toHaveValue(
      'https://files.example.test/roads.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));

    await waitFor(() =>
      expect(screen.getByTestId('import-preview')).toBeInTheDocument(),
    );
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);
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
