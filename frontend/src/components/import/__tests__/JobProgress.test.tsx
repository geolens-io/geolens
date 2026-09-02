import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobProgress } from '../JobProgress';
import { ApiError } from '@/api/client';

const { mockUseJobStatus, mockRetry } = vi.hoisted(() => ({
  mockUseJobStatus: vi.fn(),
  mockRetry: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useJobStatus: (...args: unknown[]) => mockUseJobStatus(...args),
  useRetryJob: () => ({
    mutateAsync: mockRetry,
    isPending: false,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

function failedJob(overrides: Record<string, unknown> = {}) {
  return {
    id: 'job-1',
    status: 'failed',
    dataset_id: null,
    source_filename: 'roads.geojson',
    error_message: 'Import failed.',
    can_retry: true,
    retry_reason: null,
    warning_message: null,
    warnings: [],
    progress: null,
    current_step: null,
    rows_processed: null,
    archive_failed: false,
    temporal_parse_errors: {},
    started_at: '2026-07-12T12:00:00Z',
    completed_at: '2026-07-12T12:01:00Z',
    created_at: '2026-07-12T11:59:00Z',
    ...overrides,
  };
}

describe('JobProgress retry capability', () => {
  beforeEach(() => {
    mockUseJobStatus.mockReset();
    mockRetry.mockReset();
  });

  it('shows Retry when the failed job retains a retryable source', async () => {
    mockUseJobStatus.mockReturnValue({ data: failedJob(), isLoading: false });
    mockRetry.mockResolvedValue({});
    const user = userEvent.setup();

    render(<JobProgress jobId="job-1" onReset={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(mockRetry).toHaveBeenCalledWith('job-1');
  });

  it('explains why retry is unavailable and hides Retry', () => {
    mockUseJobStatus.mockReturnValue({
      data: failedJob({
        can_retry: false,
        retry_reason: 'Fresh service credentials are required.',
      }),
      isLoading: false,
    });

    render(<JobProgress jobId="job-1" onReset={vi.fn()} />);

    expect(screen.getByText('Fresh service credentials are required.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Over' })).toBeInTheDocument();
  });
});

// fix(#1778): a failing GET /jobs/{id} used to fall into the isLoading/!job
// branch (undefined data, isLoading false after retries exhaust), rendering
// "Loading job status..." forever instead of a real error state.
describe('JobProgress error branch', () => {
  beforeEach(() => {
    mockUseJobStatus.mockReset();
    mockRetry.mockReset();
  });

  it('renders a failure card instead of an indefinite spinner when the status read errors', () => {
    mockUseJobStatus.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ApiError('Job not found', 404),
    });

    render(<JobProgress jobId="job-1" onReset={vi.fn()} />);

    expect(screen.queryByText('Loading job status...')).not.toBeInTheDocument();
    expect(screen.getByText('Job not found')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Over' })).toBeInTheDocument();
  });
});
