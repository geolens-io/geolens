import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobProgress } from '../JobProgress';

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
