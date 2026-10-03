import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobList } from '../JobList';

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
    source_filename: 'Roads',
    dataset_id: null,
    error_message: 'Import failed.',
    can_retry: false,
    retry_reason: 'Fresh service credentials are required.',
    user_metadata: null,
    created_by: 'user-1',
    username: 'editor',
    started_at: '2026-07-12T12:00:00Z',
    completed_at: '2026-07-12T12:01:00Z',
    created_at: '2026-07-12T11:59:00Z',
    ...overrides,
  };
}

function listJobs(...jobs: Record<string, unknown>[]) {
  mockUseAdminJobs.mockReturnValue({
    data: { jobs, total: jobs.length },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

describe('JobList start again', () => {
  it('links a refused service import to the service tab with a credential-free URL', async () => {
    listJobs(
      failedJob({
        restart_source: 'service',
        source_url: 'https://redacted@maps.example.com/wfs?token=%3Credacted%3E&v=2',
      }),
    );
    const user = userEvent.setup();

    render(<JobList />);
    await user.click(screen.getByTestId('job-details-toggle'));

    const href = screen.getByRole('link', { name: 'Start again' }).getAttribute('href') ?? '';
    const link = new URL(href, 'http://localhost');
    expect(link.searchParams.get('tab')).toBe('service');
    expect(link.searchParams.get('url')).toBe('https://maps.example.com/wfs?v=2');
  });

  it('links an unfinished URL download to the file URL tab', async () => {
    listJobs(failedJob({ restart_source: 'url', source_url: null }));
    const user = userEvent.setup();

    render(<JobList />);
    await user.click(screen.getByTestId('job-details-toggle'));

    expect(screen.getByRole('link', { name: 'Start again' })).toHaveAttribute(
      'href',
      '/import?tab=url',
    );
  });

  it('offers no start-again link when the server names no restart source', async () => {
    listJobs(failedJob({ restart_source: null }));
    const user = userEvent.setup();

    render(<JobList />);
    await user.click(screen.getByTestId('job-details-toggle'));

    expect(screen.queryByRole('link', { name: 'Start again' })).not.toBeInTheDocument();
  });

  it('hints on the collapsed row that a failed job can be retried', () => {
    listJobs(failedJob({ can_retry: true, retry_reason: null }));

    render(<JobList />);

    expect(screen.getByText('Retry available')).toBeInTheDocument();
  });
});
