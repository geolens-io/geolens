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

const mockUploadFromUrl = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
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
