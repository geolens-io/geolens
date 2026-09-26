import { render, screen } from '@/test/test-utils';
import { JobList } from '../JobList';

// fix(#2300): the badge used to render the raw stored value, so every locale
// showed the same English enum word regardless of language.

const { mockUseAdminJobs } = vi.hoisted(() => ({ mockUseAdminJobs: vi.fn() }));

vi.mock('@/hooks/use-admin', () => ({
  useAdminJobs: (...args: unknown[]) => mockUseAdminJobs(...args),
  useUserNames: () => ({ data: [] }),
  useRetryAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelAdminJob: () => ({ mutate: vi.fn(), isPending: false }),
}));

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 'job-1',
    status: 'fanned_out',
    source_filename: 'roads.geojson',
    dataset_id: null,
    error_message: null,
    can_retry: false,
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

function mockJobs(overrides: Record<string, unknown> = {}) {
  mockUseAdminJobs.mockReturnValue({
    data: { jobs: [job(overrides)], total: 1 },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

describe('JobList status badge', () => {
  it('shows the translated label for a fanned-out job instead of the raw value', () => {
    mockJobs({ status: 'fanned_out' });

    render(<JobList />);

    expect(screen.getByText('Fanned out')).toBeInTheDocument();
    expect(screen.queryByText('fanned_out')).not.toBeInTheDocument();
  });

  it('falls back to the unknown-status label for a value the page does not recognize', () => {
    mockJobs({ status: 'quarantined' });

    render(<JobList />);

    expect(screen.getByText('Unknown (quarantined)')).toBeInTheDocument();
  });
});
