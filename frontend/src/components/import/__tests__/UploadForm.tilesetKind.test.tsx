/** The upload kind is a labelled radio choice made before the drop, and every upload carries it. */
import { render, screen, act, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UploadForm } from '../UploadForm';
import { clearPendingUploadFiles, clearUploadBatch } from '@/api/upload-session';
import type { FileEntry } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

vi.mock('@/api/ingest', () => ({
  uploadFile: vi.fn(),
  uploadPresigned: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
}));

let mockConfig: { data: unknown; isFetching: boolean } = { data: null, isFetching: false };
vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: () => mockConfig,
}));

vi.mock('../FileDropzone', async (importOriginal) => {
  const original = await importOriginal<typeof import('../FileDropzone')>();
  return {
    effectiveBatchLimit: original.effectiveBatchLimit,
    FileDropzone: ({
      onFilesAccepted,
      allowedExtensions,
      tileset,
    }: {
      onFilesAccepted: (files: File[]) => void;
      allowedExtensions?: string[];
      tileset?: boolean;
    }) => (
      <div
        data-testid="file-dropzone"
        data-allowed-extensions={String(allowedExtensions)}
        data-tileset={String(Boolean(tileset))}
      >
        <button type="button" data-testid="drop-zip" onClick={() => onFilesAccepted([new File(['PK'], 'campus.zip')])}>
          Drop zip
        </button>
      </div>
    ),
  };
});

vi.mock('../BulkUploadProgress', () => ({
  BulkUploadProgress: ({ entries }: { entries: FileEntry[] }) => (
    <div data-testid="bulk-upload-progress" data-upload-kinds={entries.map((e) => e.uploadKind).join(',')} />
  ),
}));
vi.mock('../BulkReviewList', () => ({
  BulkReviewList: () => <div data-testid="bulk-review-list" />,
}));
vi.mock('../BulkTrackingList', () => ({
  BulkTrackingList: () => <div data-testid="bulk-tracking-list" />,
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

import { uploadFile, uploadPresigned, previewFile } from '@/api/ingest';
import { toast } from 'sonner';

const CONFIG = {
  presigned_uploads: false,
  presigned_threshold_bytes: 0,
  max_file_size_bytes: 500 * 1024 * 1024,
  allowed_extensions: '.geojson,.gpkg,.zip',
  remaining_dataset_quota: null,
};

const NO_ZIP_CONFIG = { ...CONFIG, allowed_extensions: '.geojson,.gpkg' };
const WITH_3TZ_CONFIG = { ...CONFIG, allowed_extensions: '.geojson,.gpkg,.zip,.3tz,.laz' };

function tilesetRadio() {
  return within(screen.getByRole('group', { name: 'upload.kindLegend' })).getByRole('radio', {
    name: 'upload.kindTileset',
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  clearUploadBatch();
  clearPendingUploadFiles();
  mockConfig = { data: CONFIG, isFetching: false };
  vi.mocked(uploadFile).mockResolvedValue({ job_id: 'job-1' } as never);
  vi.mocked(uploadPresigned).mockResolvedValue({ job_id: 'job-1' } as never);
  vi.mocked(previewFile).mockResolvedValue({ job_id: 'job-1' } as never);
});

afterEach(() => {
  clearUploadBatch();
  clearPendingUploadFiles();
});

describe('UploadForm upload kind', () => {
  it('offers geospatial files or a tileset as a labelled radio group reachable by keyboard', async () => {
    const user = userEvent.setup();
    render(<UploadForm />);
    const group = screen.getByRole('group', { name: 'upload.kindLegend' });
    const files = within(group).getByRole('radio', { name: 'upload.kindFiles' });

    expect(files).toBeChecked();
    expect(tilesetRadio()).toHaveAccessibleDescription('upload.kindTilesetHint');
    await user.tab();
    expect(files).toHaveFocus();
    await user.keyboard('{ArrowDown}');

    expect(tilesetRadio()).toBeChecked();
    const dropzone = screen.getByTestId('file-dropzone');
    expect(dropzone).toHaveAttribute('data-tileset', 'true');
    expect(dropzone).toHaveAttribute('data-allowed-extensions', '.zip');
  });

  it('uploads a tileset through the multipart door with kind tiles3d', async () => {
    const user = userEvent.setup();
    render(<UploadForm />);

    await user.click(tilesetRadio());
    await user.click(screen.getByTestId('drop-zip'));

    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect(vi.mocked(uploadFile).mock.calls[0][2]).toBe('tiles3d');
  });

  it('uploads a tileset through the presigned door with kind tiles3d', async () => {
    mockConfig = { data: { ...CONFIG, presigned_uploads: true }, isFetching: false };
    const user = userEvent.setup();
    render(<UploadForm />);

    await user.click(tilesetRadio());
    await user.click(screen.getByTestId('drop-zip'));

    await waitFor(() => expect(uploadPresigned).toHaveBeenCalledTimes(1));
    expect(vi.mocked(uploadPresigned).mock.calls[0][2]).toBe('tiles3d');
  });

  it('sends no kind for geospatial files', async () => {
    const user = userEvent.setup();
    render(<UploadForm />);

    await user.click(screen.getByTestId('drop-zip'));

    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect(vi.mocked(uploadFile).mock.calls[0][2]).toBeNull();
  });

  it('keeps the kind of a drop queued behind the config fetch across a remount', async () => {
    mockConfig = { data: null, isFetching: true };
    const user = userEvent.setup();
    const first = render(<UploadForm />);
    await user.click(tilesetRadio());
    await user.click(screen.getByTestId('drop-zip'));
    expect(uploadFile).not.toHaveBeenCalled();
    first.unmount();

    const second = render(<UploadForm />);
    expect(tilesetRadio()).toBeChecked();
    expect(tilesetRadio()).toBeDisabled();

    mockConfig = { data: CONFIG, isFetching: false };
    await act(async () => {
      second.rerender(<UploadForm />);
    });

    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect(vi.mocked(uploadFile).mock.calls[0][2]).toBe('tiles3d');
  });

  it('keeps the tileset kind on an uploading entry, including after a remount adopts it', async () => {
    vi.mocked(uploadFile).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    const first = render(<UploadForm />);
    await user.click(tilesetRadio());
    await user.click(screen.getByTestId('drop-zip'));

    expect(screen.getByTestId('bulk-upload-progress')).toHaveAttribute('data-upload-kinds', 'tiles3d');
    first.unmount();

    render(<UploadForm />);
    expect(screen.getByTestId('bulk-upload-progress')).toHaveAttribute('data-upload-kinds', 'tiles3d');
  });

  it('disables the tileset option and says why when the deployment allows neither .zip nor .3tz', () => {
    mockConfig = { data: NO_ZIP_CONFIG, isFetching: false };
    render(<UploadForm />);

    expect(tilesetRadio()).toBeDisabled();
    expect(tilesetRadio()).toHaveAccessibleDescription('upload.kindTilesetUnavailable');
    expect(screen.getByText('upload.kindTilesetUnavailable')).toBeVisible();
  });

  it('checks a queued tileset drop as files when the config that arrives allows no tileset archive', async () => {
    mockConfig = { data: null, isFetching: true };
    const user = userEvent.setup();
    const view = render(<UploadForm />);
    await user.click(tilesetRadio());
    await user.click(screen.getByTestId('drop-zip'));

    mockConfig = { data: NO_ZIP_CONFIG, isFetching: false };
    await act(async () => {
      view.rerender(<UploadForm />);
    });

    expect(toast.error).toHaveBeenCalledWith('dropzone.fileRejected');
    expect(uploadFile).not.toHaveBeenCalled();
    expect(screen.getByRole('radio', { name: 'upload.kindFiles' })).toBeChecked();
  });

  it('takes .zip and .3tz in tileset mode when the deployment allows both', async () => {
    mockConfig = { data: WITH_3TZ_CONFIG, isFetching: false };
    const user = userEvent.setup();
    render(<UploadForm />);

    await user.click(tilesetRadio());

    expect(screen.getByTestId('file-dropzone')).toHaveAttribute('data-allowed-extensions', '.zip,.3tz');
  });

  it('leaves .3tz and .laz out of the geospatial files choice', () => {
    mockConfig = { data: WITH_3TZ_CONFIG, isFetching: false };
    render(<UploadForm />);

    expect(screen.getByTestId('file-dropzone')).toHaveAttribute('data-allowed-extensions', '.geojson,.gpkg,.zip');
  });

  it('offers the tileset choice when the deployment allows only .3tz', async () => {
    mockConfig = { data: { ...CONFIG, allowed_extensions: '.geojson,.3tz' }, isFetching: false };
    const user = userEvent.setup();
    render(<UploadForm />);

    expect(tilesetRadio()).toBeEnabled();
    await user.click(tilesetRadio());

    expect(screen.getByTestId('file-dropzone')).toHaveAttribute('data-allowed-extensions', '.3tz');
  });

  it('rejects every file in files mode when the deployment allows only .3tz', async () => {
    mockConfig = { data: null, isFetching: true };
    const user = userEvent.setup();
    const view = render(<UploadForm />);
    await user.click(screen.getByTestId('drop-zip'));

    mockConfig = { data: { ...CONFIG, allowed_extensions: '.3tz' }, isFetching: false };
    await act(async () => {
      view.rerender(<UploadForm />);
    });

    expect(screen.getByTestId('file-dropzone')).toHaveAttribute('data-allowed-extensions', '');
    expect(toast.error).toHaveBeenCalledWith('dropzone.fileRejected');
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it('says why the kind is locked while a drop waits for the config', async () => {
    mockConfig = { data: null, isFetching: true };
    const user = userEvent.setup();
    render(<UploadForm />);
    const group = screen.getByRole('group', { name: 'upload.kindLegend' });
    expect(group).not.toHaveAccessibleDescription();

    await user.click(screen.getByTestId('drop-zip'));

    expect(group).toBeDisabled();
    expect(group).toHaveAccessibleDescription('upload.kindLocked');
    expect(screen.getByText('upload.kindLocked')).toBeVisible();
  });
});
