import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { JobProgress } from '../JobProgress';
import { ApiError } from '@/api/client';

const { mockUseJobStatus, mockRetry, mockCancel } = vi.hoisted(() => ({
  mockUseJobStatus: vi.fn(),
  mockRetry: vi.fn(),
  mockCancel: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useJobStatus: (...args: unknown[]) => mockUseJobStatus(...args),
  useRetryJob: () => ({
    mutateAsync: mockRetry,
    isPending: false,
  }),
  useCancelJob: () => ({
    mutate: mockCancel,
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

function runningJob(overrides: Record<string, unknown> = {}) {
  return {
    ...failedJob({ status: 'running', error_message: null, started_at: null, completed_at: null }),
    ...overrides,
  };
}

function cancelledJob(overrides: Record<string, unknown> = {}) {
  return {
    ...failedJob({ status: 'cancelled', error_message: null, retry_reason: null }),
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

// fix(#1778): #1709 granted job-creator cancel server-side, but JobProgress —
// the terminal render for every import path — offered no way to reach it.
describe('JobProgress owner cancel', () => {
  beforeEach(() => {
    mockUseJobStatus.mockReset();
    mockCancel.mockReset();
  });

  it('shows Cancel on a running job and calls the cancel mutation with the job id', async () => {
    mockUseJobStatus.mockReturnValue({ data: runningJob(), isLoading: false });
    const user = userEvent.setup();

    render(<JobProgress jobId="job-1" onReset={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(mockCancel).toHaveBeenCalledWith('job-1', expect.anything());
  });

  it('hides Cancel once the job is terminal', () => {
    mockUseJobStatus.mockReturnValue({ data: failedJob(), isLoading: false });

    render(<JobProgress jobId="job-1" onReset={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });
});

// fix(review #1800 P2): a successful Cancel drives the job to `cancelled`,
// hiding the Cancel button — but the terminal blocks below only covered
// `complete` and `failed`, so JobProgress then rendered no action at all.
// ServiceUrlForm and VrtCreatorForm render bare <JobProgress> with no other
// escape hatch, so this stranded them on a dead job with nothing to click.
describe('JobProgress cancelled state', () => {
  beforeEach(() => {
    mockUseJobStatus.mockReset();
  });

  it('renders a status line and the reset action for a cancelled job', async () => {
    const onReset = vi.fn();
    mockUseJobStatus.mockReturnValue({ data: cancelledJob(), isLoading: false });
    const user = userEvent.setup();

    render(<JobProgress jobId="job-1" onReset={onReset} />);

    expect(screen.getByText('This job was cancelled.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start Over' }));

    expect(onReset).toHaveBeenCalledTimes(1);
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
