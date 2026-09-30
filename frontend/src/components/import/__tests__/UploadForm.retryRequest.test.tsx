/**
 * A refused commit must come back after a tab switch with the request the
 * user attempted, so a retry does not silently fall back to preview defaults.
 * Uses the real review list and metadata form.
 */
import { render, screen, act } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UploadForm } from '../UploadForm';
import { clearUploadBatch } from '@/api/upload-session';
import { ApiError } from '@/api/client';

const mockUploadFile = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();
let droppedFiles: File[];

vi.mock('@/api/ingest', () => ({
  uploadFile: (...args: unknown[]) => mockUploadFile(...args),
  uploadPresigned: (...args: unknown[]) => mockUploadFile(...args),
  previewFile: (...args: unknown[]) => mockPreviewFile(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
}));

vi.mock('@/api/datasets', () => ({
  commitFanOut: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => ({ data: null, isFetching: false }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useCanSetPublicVisibility: () => true,
}));

vi.mock('../FileDropzone', () => ({
  FileDropzone: ({ onFilesAccepted }: { onFilesAccepted: (files: File[]) => void }) => (
    <button data-testid="simulate-drop" onClick={() => onFilesAccepted(droppedFiles)}>
      Drop
    </button>
  ),
}));

vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: () => <div data-testid="bulk-tracking-list" />,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

const PREVIEW = {
  job_id: 'job-1',
  source_filename: 'roads.geojson',
  columns: [{ name: 'id', type: 'Integer' }],
  crs: null,
  geometry_type: 'LineString',
  feature_count: 3,
  sample_rows: [],
  layer_name: 'roads',
  layers: null,
  detected_geometry_columns: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  clearUploadBatch();
  droppedFiles = [new File(['{}'], 'roads.geojson')];
});

test('collapsed forms keep unsent edits and confirmed batch defaults ignore them', async () => {
  const user = userEvent.setup();
  droppedFiles.push(new File(['{}'], 'stations.geojson'));
  mockUploadFile.mockImplementation(async (file: File) => ({ job_id: file.name }));
  mockPreviewFile.mockImplementation(async (jobId: string) => ({ ...PREVIEW, job_id: jobId, source_filename: jobId }));
  mockCommitImport.mockResolvedValue({});
  render(<UploadForm />);
  await user.click(screen.getByTestId('simulate-drop'));
  const name = (await screen.findAllByLabelText('metadata.nameLabel'))[0];
  await user.clear(name);
  await user.type(name, 'Unsent title');
  await user.type(screen.getAllByLabelText('metadata.descriptionLabel')[0], 'Unsent notes');
  await user.click(screen.getAllByRole('button', { name: 'bulk.toggleDetails' })[1]);
  await user.click(screen.getAllByRole('button', { name: 'bulk.toggleDetails' })[0]);
  expect(screen.getAllByLabelText('metadata.nameLabel')[0]).toHaveValue('Unsent title');
  expect(screen.getAllByLabelText('metadata.descriptionLabel')[0]).toHaveValue('Unsent notes');
  await user.click(screen.getByRole('button', { name: 'bulk.importAllDefaults' }));
  expect(mockCommitImport).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'bulk.confirmDefaults' }));
  expect(mockCommitImport).toHaveBeenCalledWith('roads.geojson', { title: 'roads' });
  expect(mockCommitImport).toHaveBeenCalledWith('stations.geojson', { title: 'stations' });
});

afterEach(() => {
  clearUploadBatch();
});

test('a commit refused while unmounted comes back with the edits the user made', async () => {
  const user = userEvent.setup();
  mockUploadFile.mockResolvedValue({ job_id: 'job-1', status: 'pending' });
  mockPreviewFile.mockResolvedValue(PREVIEW);
  let rejectCommit!: (reason: unknown) => void;
  mockCommitImport.mockReturnValueOnce(
    new Promise((_resolve, reject) => {
      rejectCommit = reject;
    }),
  );

  const view = render(<UploadForm />);
  await user.click(screen.getByTestId('simulate-drop'));
  const name = await screen.findByLabelText('metadata.nameLabel');
  await user.clear(name);
  await user.type(name, 'Edited roads');
  await user.type(screen.getByLabelText('metadata.descriptionLabel'), 'Survey notes');
  await user.type(screen.getByLabelText('metadata.crsLabel'), '3857');
  await user.click(screen.getByRole('button', { name: 'metadata.importDataset' }));

  const attempted = mockCommitImport.mock.calls[0][1];
  expect(attempted).toMatchObject({ title: 'Edited roads', summary: 'Survey notes', srid_override: 3857 });

  view.unmount();
  await act(async () => {
    rejectCommit(new ApiError('Title already in use', 409));
  });

  render(<UploadForm />);
  expect(await screen.findByLabelText('metadata.nameLabel')).toHaveValue('Edited roads');
  expect(screen.getByLabelText('metadata.descriptionLabel')).toHaveValue('Survey notes');
  expect(screen.getByLabelText('metadata.crsLabel')).toHaveValue(3857);
  expect(screen.getByText('Title already in use')).toBeInTheDocument();

  mockCommitImport.mockResolvedValueOnce({});
  await user.click(screen.getByRole('button', { name: 'metadata.importDataset' }));
  expect(mockCommitImport).toHaveBeenCalledTimes(2);
  expect(mockCommitImport).toHaveBeenLastCalledWith('job-1', attempted);
});
