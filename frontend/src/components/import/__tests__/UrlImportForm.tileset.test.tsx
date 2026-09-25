/** The File URL form imports a 3D Tiles archive: it sends the kind, previews and commits the tileset, and shows a refusal's reason. */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UrlImportForm } from '../UrlImportForm';
import type { CommitImportRequest } from '@/types/api';
import { clearUrlImport, startUrlImport } from '@/api/url-import-session';
import { useAuthStore } from '@/stores/auth-store';

const mockUploadFromUrl = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();
const mockGetJobStatus = vi.fn();
const mockGetUploadConfig = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
  getJobStatus: (...args: unknown[]) => mockGetJobStatus(...args),
  cancelJob: vi.fn(),
  getUploadConfig: (...args: unknown[]) => mockGetUploadConfig(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

let metadataProps: { isTileset?: boolean; defaultName: string } | null = null;
vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: (props: {
    isTileset?: boolean;
    defaultName: string;
    onCommit: (m: CommitImportRequest) => void;
  }) => {
    metadataProps = props;
    return (
      <button type="button" onClick={() => props.onCommit({ title: 'Campus' })}>
        commit-stub
      </button>
    );
  },
}));

vi.mock('../JobProgress', () => ({
  JobProgress: ({ jobId }: { jobId: string }) => <div data-testid="job-progress">{jobId}</div>,
}));

const TILESET_PREVIEW = {
  job_id: 'job-t',
  source_filename: 'campus.3tz',
  version: '1.1',
  geometric_error: 500,
  bounding_volume: 'region',
  extent_bbox: [-75.61, 40.04, -75.6, 40.05],
  unpacked_bytes: 2048,
  entry_count: 3,
};

function uploadConfig(allowedExtensions: string) {
  return {
    max_file_size_bytes: 1024 * 1024 * 1024,
    allowed_extensions: allowedExtensions,
    presigned_uploads: false,
    remaining_dataset_quota: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  metadataProps = null;
  useAuthStore.setState({ token: 'test-token' });
  mockGetJobStatus.mockResolvedValue({ job_id: 'job-t', status: 'pending' });
  mockGetUploadConfig.mockResolvedValue(uploadConfig('.geojson,.zip,.3tz'));
  clearUrlImport();
});

afterEach(() => {
  clearUrlImport();
});

async function submit(user: ReturnType<typeof userEvent.setup>, url: string) {
  await user.type(screen.getByLabelText('urlImport.label'), url);
  await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
}

describe('UrlImportForm with a 3D Tiles archive', () => {
  test('the tileset choice sends kind=tiles3d with the URL', async () => {
    mockUploadFromUrl.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    render(<UrlImportForm />);

    await user.click(screen.getByRole('radio', { name: 'upload.kindTileset' }));
    await submit(user, 'https://files.example.test/campus.3tz');

    expect(mockUploadFromUrl).toHaveBeenCalledWith(
      'https://files.example.test/campus.3tz',
      undefined,
      'tiles3d',
    );
  });

  test('the tileset choice is unavailable when the deployment allows neither archive', async () => {
    mockGetUploadConfig.mockResolvedValue(uploadConfig('.geojson,.gpkg'));
    render(<UrlImportForm />);

    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'upload.kindTileset' })).toBeDisabled(),
    );
    expect(screen.getByText('upload.kindTilesetUnavailable')).toBeInTheDocument();
  });

  test('a tileset preview renders its facts and commits through the tileset metadata form', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-t', status: 'running' });
    mockPreviewFile.mockResolvedValue(TILESET_PREVIEW);
    mockCommitImport.mockResolvedValue({ job_id: 'job-t', status: 'queued' });
    const user = userEvent.setup();
    render(<UrlImportForm />);

    await user.click(screen.getByRole('radio', { name: 'upload.kindTileset' }));
    await submit(user, 'https://files.example.test/campus.3tz');

    await waitFor(() => expect(screen.getByText('detect.tilesetInfo')).toBeInTheDocument());
    expect(screen.getByText('campus.3tz')).toBeInTheDocument();
    expect(screen.getByText('detect.labels.version').nextSibling).toHaveTextContent('1.1');
    expect(metadataProps).toMatchObject({ isTileset: true, defaultName: 'campus.3tz' });

    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(screen.getByTestId('job-progress')).toHaveTextContent('job-t'));
    expect(mockCommitImport).toHaveBeenCalledWith('job-t', { title: 'Campus' });
  });

  test('a refused archive shows the reason the download job stored', async () => {
    const refusal = 'An entry in the archive has an absolute path. Every entry must sit below the archive root.';
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-t', status: 'running' });
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-t', status: 'failed', error_message: refusal });
    const user = userEvent.setup();
    render(<UrlImportForm />);

    await user.click(screen.getByRole('radio', { name: 'upload.kindTileset' }));
    await submit(user, 'https://files.example.test/campus.3tz');

    await waitFor(() => expect(screen.getByText(refusal)).toBeInTheDocument());
    expect(screen.getByRole('radio', { name: 'upload.kindTileset' })).toBeChecked();
  });

  test('a download failure stored as the internal code shows the localized fallback', async () => {
    mockUploadFromUrl.mockResolvedValue({ job_id: 'job-t', status: 'running' });
    mockGetJobStatus.mockResolvedValue({ job_id: 'job-t', status: 'failed', error_message: 'internal_error' });
    const user = userEvent.setup();
    render(<UrlImportForm />);

    await submit(user, 'https://files.example.test/campus.3tz');

    await waitFor(() =>
      expect(screen.getByText('common:errors.internalFailureReason')).toBeInTheDocument(),
    );
    expect(screen.queryByText('internal_error')).not.toBeInTheDocument();
  });

  test('a remount restores the kind its session was started with', async () => {
    mockUploadFromUrl.mockRejectedValue(new Error('offline'));
    startUrlImport('https://files.example.test/campus.3tz', undefined, 'tiles3d');

    render(<UrlImportForm />);

    await waitFor(() => expect(screen.getByText('urlImport.fetchFailed')).toBeInTheDocument());
    expect(screen.getByRole('radio', { name: 'upload.kindTileset' })).toBeChecked();
  });
});
