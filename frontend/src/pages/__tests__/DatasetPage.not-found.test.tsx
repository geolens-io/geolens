// A dataset that does not exist is a dead end: no retry button, and nothing
// that depends on the dataset keeps querying.
import { useParams } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { ApiError } from '@/api/client';
import { useDataset, useDatasetRefreshWatch, useValidation } from '@/components/dataset/hooks/use-dataset';
import { useDatasetJobStatus } from '@/components/import/hooks/use-ingest';
import { useAuthStore } from '@/stores/auth-store';
import { DatasetPage } from '@/pages/DatasetPage';

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: vi.fn() };
});

vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: () => false }),
}));

vi.mock('@/hooks/use-unsaved-guard', () => ({
  useUnsavedGuard: () => ({ state: 'unblocked', reset: vi.fn(), proceed: vi.fn() }),
}));

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDataset: vi.fn(),
  useUpdateDataset: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetTargetStatus: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useValidation: vi.fn(() => ({ data: undefined })),
  useDatasetRefreshWatch: vi.fn(() => ({ latestRun: undefined, isBusy: false, trackDispatchedRun: vi.fn() })),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useDatasetJobStatus: vi.fn(() => ({ data: undefined })),
}));

vi.mock('@/hooks/use-settings', () => ({
  useFeatureFlags: () => ({ data: undefined }),
}));

function mockDatasetError(error: Error) {
  vi.mocked(useParams).mockReturnValue({ id: 'missing-id' });
  vi.mocked(useDataset).mockReturnValue({
    data: undefined,
    isLoading: false,
    error,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useDataset>);
}

describe('DatasetPage load failures', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ token: 'token' });
  });

  it('offers no retry and stops dependent queries on a 404', () => {
    mockDatasetError(new ApiError('Dataset not found', 404));

    render(<DatasetPage />);

    expect(screen.getByRole('alert')).toHaveTextContent('Dataset not found');
    expect(screen.queryByRole('button', { name: /retry|try again/i })).not.toBeInTheDocument();
    expect(useValidation).toHaveBeenLastCalledWith(undefined);
    expect(useDatasetJobStatus).toHaveBeenLastCalledWith(null);
    expect(useDatasetRefreshWatch).toHaveBeenLastCalledWith('');
  });

  it('keeps the retry button for other errors', () => {
    mockDatasetError(new ApiError('Server error', 500));

    render(<DatasetPage />);

    expect(screen.getByRole('button', { name: /retry|try again/i })).toBeInTheDocument();
    expect(useValidation).toHaveBeenLastCalledWith('missing-id');
  });
});
