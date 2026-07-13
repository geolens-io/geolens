import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobList } from '../JobList';

const { mockUseAdminJobs, mockRetry } = vi.hoisted(() => ({
  mockUseAdminJobs: vi.fn(),
  mockRetry: vi.fn(),
}));

vi.mock('@/hooks/use-admin', () => ({
  useAdminJobs: (...args: unknown[]) => mockUseAdminJobs(...args),
  useUserNames: () => ({ data: [] }),
  useRetryAdminJob: () => ({
    mutate: mockRetry,
    isPending: false,
  }),
}));

function failedJob(overrides: Record<string, unknown> = {}) {
  return {
    id: 'job-1',
    status: 'failed',
    source_filename: 'roads.geojson',
    dataset_id: null,
    error_message: 'Import failed.',
    can_retry: true,
    retry_reason: null,
    user_metadata: null,
    created_by: 'user-1',
    username: 'editor',
    started_at: '2026-07-12T12:00:00Z',
    completed_at: '2026-07-12T12:01:00Z',
    created_at: '2026-07-12T11:59:00Z',
    ...overrides,
  };
}

describe('JobList retry capability', () => {
  beforeEach(() => {
    mockRetry.mockReset();
  });

  it('hides retry and displays the server reason for a non-retryable job', async () => {
    mockUseAdminJobs.mockReturnValue({
      data: {
        jobs: [
          failedJob({
            can_retry: false,
            retry_reason: 'Fresh service credentials are required.',
          }),
        ],
        total: 1,
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    const user = userEvent.setup();

    render(<JobList />);
    await user.click(screen.getByTestId('job-details-toggle'));

    expect(screen.getByText('Fresh service credentials are required.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('offers retry when the server marks the failed job retryable', async () => {
    mockUseAdminJobs.mockReturnValue({
      data: { jobs: [failedJob()], total: 1 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    const user = userEvent.setup();

    render(<JobList />);
    await user.click(screen.getByTestId('job-details-toggle'));
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(mockRetry).toHaveBeenCalledWith('job-1');
  });
});
