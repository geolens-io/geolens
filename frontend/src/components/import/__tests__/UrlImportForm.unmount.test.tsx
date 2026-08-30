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

vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

vi.mock('../ImportPreview', () => ({
  ImportPreview: () => <div data-testid="import-preview" />,
}));
vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: () => <div data-testid="metadata-form" />,
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
});
