import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobList } from '../JobList';

// fix(#2035): a stored 'internal_error' must read the same operator-facing
// sentence as the CLI (cli/geolens_cli/refresh.py), not the generic fallback.

const { mockUseAdminJobs } = vi.hoisted(() => ({ mockUseAdminJobs: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useAdminJobs: (...args: unknown[]) => mockUseAdminJobs(...args),
  useUserNames: () => ({ data: [] }),
  useRetryAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
}));

function failedJob(overrides: Record<string, unknown> = {}) {
  return {
    id: 'job-1',
    status: 'failed',
    source_filename: 'roads.geojson',
    dataset_id: null,
    error_message: 'internal_error',
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

describe('JobList internal_error reason', () => {
  it('renders the CLI-matching sentence instead of the generic fallback', async () => {
    mockUseAdminJobs.mockReturnValue({
      data: { jobs: [failedJob()], total: 1 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    const user = userEvent.setup();

    render(<JobList />);
    await user.click(screen.getByTestId('job-details-toggle'));

    expect(
      screen.getByText(
        'The job failed for a reason the server could not report safely. Ask an operator to check the server log for this job.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('An unexpected error occurred')).not.toBeInTheDocument();
  });
});
