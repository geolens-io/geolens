/**
 * fix(#1708 codex r19): a URL import must survive the form unmounting.
 *
 * The Import page renders tabs conditionally, so switching away mid-import
 * unmounts UrlImportForm. The request keeps running server-side, so if the
 * job id lands in dead component state the user is left with an unreachable
 * pending job and its staged bytes until the sweep collects them.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UrlImportForm } from '../UrlImportForm';
import { clearUrlImport, peekUrlImport } from '@/api/url-import-session';

const mockUploadFromUrl = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();
const mockGetJobStatus = vi.fn();
const mockCancelJob = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
  // fix(review #1800 P2): UrlImportForm's preview-failure handling now
  // calls these to decide whether the failed job is still retryable.
  getJobStatus: (...args: unknown[]) => mockGetJobStatus(...args),
  cancelJob: (...args: unknown[]) => mockCancelJob(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

vi.mock('../ImportPreview', () => ({
  ImportPreview: () => <div data-testid="import-preview" />,
}));
vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: ({ onCommit }: { onCommit: (m: unknown) => void }) => (
    <div data-testid="metadata-form">
      <button type="button" onClick={() => onCommit({ title: 'Roads' })}>
        commit-stub
      </button>
    </div>
  ),
}));
vi.mock('../JobProgress', () => ({
  JobProgress: ({ jobId }: { jobId: string }) => (
    <div data-testid="job-progress">{jobId}</div>
  ),
}));

const VECTOR_PREVIEW = {
  job_id: 'job-survives',
  source_filename: 'roads.geojson',
  columns: [{ name: 'id', type: 'Integer' }],
  crs: 4326,
  geometry_type: 'LineString',
  feature_count: 3,
  sample_rows: [],
  layer_name: 'roads',
  layers: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  clearUrlImport();
});

afterEach(() => {
  clearUrlImport();
});

describe('UrlImportForm unmount survival', () => {
  test('a job returned while unmounted is captured and resumed on remount', async () => {
    // The server answers only after the form is gone — the reported case.
    let resolveUpload!: (v: { job_id: string; status: string }) => void;
    mockUploadFromUrl.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    mockPreviewFile.mockResolvedValue(VECTOR_PREVIEW);

    const user = userEvent.setup();
    const view = render(<UrlImportForm />);
    await user.type(
      screen.getByLabelText('urlImport.label'),
      'https://files.example.test/roads.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
    await waitFor(() => expect(mockUploadFromUrl).toHaveBeenCalledTimes(1));

    // Switch tabs: the Import page unmounts the form.
    view.unmount();

    // The server finishes anyway.
    resolveUpload({ job_id: 'job-survives', status: 'pending' });
    await waitFor(() =>
      expect(peekUrlImport()?.jobId).toBe('job-survives'),
    );

    // Coming back re-attaches to the same import instead of stranding it...
    render(<UrlImportForm />);
    await waitFor(() =>
      expect(screen.getByTestId('import-preview')).toBeInTheDocument(),
    );
    expect(mockPreviewFile).toHaveBeenCalledWith('job-survives');
    // ...and does NOT start a second import (which would strand the first
    // AND stage a duplicate).
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);
  });

  test('a remount while the fetch is still in flight adopts it, not a new one', async () => {
    mockUploadFromUrl.mockReturnValue(new Promise(() => {}));

    const user = userEvent.setup();
    const view = render(<UrlImportForm />);
    await user.type(
      screen.getByLabelText('urlImport.label'),
      'https://files.example.test/slow.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
    await waitFor(() => expect(mockUploadFromUrl).toHaveBeenCalledTimes(1));

    view.unmount();
    render(<UrlImportForm />);

    // Still exactly one server-side import, and the remounted form shows
    // the in-flight state rather than the idle form.
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByText('urlImport.fetching')).toBeInTheDocument(),
    );
  });

  test('a failure while unmounted settles the session and does not resume', async () => {
    let rejectUpload!: (e: unknown) => void;
    mockUploadFromUrl.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectUpload = reject;
      }),
    );

    const user = userEvent.setup();
    const view = render(<UrlImportForm />);
    await user.type(
      screen.getByLabelText('urlImport.label'),
      'https://files.example.test/bad.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
    await waitFor(() => expect(mockUploadFromUrl).toHaveBeenCalledTimes(1));

    view.unmount();
    rejectUpload(new Error('boom'));
    // The rejection is handled at module scope (no unhandled rejection),
    // and the session records it rather than losing it.
    await waitFor(() => expect(peekUrlImport()?.status).toBe('rejected'));

    // Remounting surfaces the failure and clears the session, so the next
    // attempt starts fresh.
    render(<UrlImportForm />);
    await waitFor(() =>
      expect(screen.getByText('urlImport.fetchFailed')).toBeInTheDocument(),
    );
    expect(peekUrlImport()).toBeNull();
    expect(mockPreviewFile).not.toHaveBeenCalled();
  });

  test('unmounting mid-commit resumes into tracking, not a blank form', async () => {
    // fix(#1708 codex r20): r19 covered fetch+preview but cleared the
    // session on commit success, so an unmount while commitImport() was in
    // flight wrote `tracking` into a dead component and left the user with
    // a blank form on return — while the ingest was really running.
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-committing', status: 'pending' });
    mockPreviewFile.mockResolvedValue({ ...VECTOR_PREVIEW, job_id: 'job-committing' });
    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((resolve) => {
        resolveCommit = resolve;
      }),
    );

    const user = userEvent.setup();
    const view = render(<UrlImportForm />);
    await user.type(
      screen.getByLabelText('urlImport.label'),
      'https://files.example.test/roads.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
    await waitFor(() =>
      expect(screen.getByTestId('metadata-form')).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    // The user switches tabs while the commit is still in flight, and
    // comes back BEFORE it settles — the r21 case: there is no outcome to
    // sample yet, so the mount must subscribe.
    view.unmount();
    expect(peekUrlImport()?.commit).not.toBeNull();
    render(<UrlImportForm />);
    resolveCommit({ job_id: 'job-committing', status: 'queued' });
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toHaveTextContent(
        'job-committing',
      ),
    );
    // ...without re-previewing (the API refuses a committed job with 400)
    // and without committing a second time.
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);
  });

  test('a commit that fails while unmounted leaves the job previewable again', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-recommit', status: 'pending' });
    mockPreviewFile.mockResolvedValue({ ...VECTOR_PREVIEW, job_id: 'job-recommit' });
    let rejectCommit!: (e: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectCommit = reject;
      }),
    );

    const user = userEvent.setup();
    const view = render(<UrlImportForm />);
    await user.type(
      screen.getByLabelText('urlImport.label'),
      'https://files.example.test/roads.geojson',
    );
    await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
    await waitFor(() =>
      expect(screen.getByTestId('metadata-form')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    // Remount FIRST, while the commit is still in flight — the mount
    // subscribes rather than sampling — and only then let it fail.
    view.unmount();
    render(<UrlImportForm />);
    rejectCommit(new Error('commit boom'));

    // The subscriber learns the real outcome: back to review, with the job
    // still previewable, instead of polling a job nothing will finish.
    await waitFor(() =>
      expect(screen.getByTestId('import-preview')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('job-progress')).not.toBeInTheDocument();
    expect(screen.getByText('urlImport.commitFailed')).toBeInTheDocument();
    // Re-previewed to rebuild review state; still exactly one commit.
    expect(mockPreviewFile).toHaveBeenCalledTimes(2);
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });
});
