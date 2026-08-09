import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import { useDatasetRefreshRuns, useRefreshDataset } from '@/components/dataset/hooks/use-dataset';
import { ApiError } from '@/api/client';
import { queryKeys } from '@/lib/query-keys';
import { REFRESHABLE_ORIGINS, SourceRefreshAction } from '../SourceRefreshAction';
import type { DatasetRefreshRunResponse, DatasetResponse } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useRefreshDataset: vi.fn(),
  useDatasetRefreshRuns: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockUseRefreshDataset = vi.mocked(useRefreshDataset);
const mockUseDatasetRefreshRuns = vi.mocked(useDatasetRefreshRuns);
const mutateAsync = vi.fn();

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'dataset-1',
    record_id: 'record-1',
    table_name: 'roads',
    title: 'Roads',
    summary: null,
    srid: 4326,
    geometry_type: 'LineString',
    feature_count: 42,
    extent_bbox: null,
    column_info: null,
    license: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'wfs',
    source_filename: null,
    tile_columns: null,
    original_srid: 4326,
    visibility: 'public',
    created_by: 'user-1',
    created_by_display: 'editor-user',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    last_edited_by_display: null,
    last_edited_at: null,
    record_status: 'published',
    lineage_summary: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: null,
    owner_org: null,
    published_at: null,
    updated_by: null,
    current_version: 1,
    source_url: null,
    origin: 'service',
    origin_uri: null,
    origin_ref: null,
    last_refreshed_at: null,
    last_checked_at: null,
    source_health: 'healthy',
    source_health_detail: null,
    schema_drift_status: 'none',
    source_freshness: 'fresh',
    quality_statement: null,
    collections: null,
    record_type: 'vector_dataset',
    raster: null,
    ...overrides,
  };
}

function makeRun(overrides: Partial<DatasetRefreshRunResponse> = {}): DatasetRefreshRunResponse {
  return {
    id: 'run-1',
    dataset_id: 'dataset-1',
    dataset_version_id: null,
    ingest_job_id: 'job-1',
    origin_kind: 'service',
    trigger: 'api',
    status: 'running',
    triggered_by: null,
    triggered_by_username: null,
    started_at: '2026-08-05T00:00:00Z',
    claimed_at: '2026-08-05T00:00:01Z',
    finished_at: null,
    feature_count_before: 42,
    feature_count_after: null,
    schema_diff: null,
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

function mockNoActiveRun() {
  mockUseDatasetRefreshRuns.mockReturnValue({
    data: { runs: [], total: 0 },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useDatasetRefreshRuns>);
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Refresh from source' }));
  await screen.findByRole('dialog');
}

describe('SourceRefreshAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseRefreshDataset.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshDataset>);
    mockNoActiveRun();
  });

  it('opens a confirm dialog with an optional token field for a service origin', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} />);

    await openDialog(user);

    expect(screen.getByLabelText('Access token (optional)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start refresh' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  // fix(#1285 codex round 3): _dispatch_postgis_refresh() rejects ANY
  // nonempty token with 422 credential_not_applicable — a registered table
  // needs no service credential. Offering the field here invites a
  // guaranteed failure, so it must not render for this origin.
  it('does not offer a token field for a postgis origin', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset({ origin: 'postgis' })} />);

    await openDialog(user);

    expect(screen.queryByLabelText('Access token (optional)')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start refresh' })).toBeInTheDocument();
  });

  it('dispatches a postgis refresh with no token, since none was ever offered', async () => {
    mutateAsync.mockResolvedValue({
      run_id: 'run-1',
      job_id: 'job-1',
      dataset_id: 'dataset-1',
      origin_kind: 'postgis',
      trigger: 'api',
      status: 'pending',
      message: 'Refresh queued from the registered table',
    });
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset({ origin: 'postgis' })} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({ datasetId: 'dataset-1', token: undefined });
    });
  });

  it('dispatches the refresh, closes the dialog, and clears the token from rendered output and component state', async () => {
    mutateAsync.mockResolvedValue({
      run_id: 'run-42',
      job_id: 'job-42',
      dataset_id: 'dataset-1',
      origin_kind: 'service',
      trigger: 'api',
      status: 'pending',
      message: 'Refresh queued from the stored source',
    });
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} />);

    await openDialog(user);
    const secretToken = 'super-secret-token-value';
    await user.type(screen.getByLabelText('Access token (optional)'), secretToken);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    expect(mutateAsync).toHaveBeenCalledWith({ datasetId: 'dataset-1', token: secretToken });
    // The token must not survive anywhere reachable from the DOM once the
    // request has been dispatched — not in a toast, not in the closed
    // dialog's last-known markup.
    expect(document.body.textContent).not.toContain(secretToken);
    expect(screen.queryByDisplayValue(secretToken)).not.toBeInTheDocument();

    // Reopening proves the field was reset in component state, not just
    // hidden by the dialog closing.
    await openDialog(user);
    expect(screen.getByLabelText('Access token (optional)')).toHaveValue('');
  });

  it('sends no token when the field is left blank', async () => {
    mutateAsync.mockResolvedValue({
      run_id: 'run-1',
      job_id: 'job-1',
      dataset_id: 'dataset-1',
      origin_kind: 'postgis',
      trigger: 'api',
      status: 'pending',
      message: 'Refresh queued from the registered table',
    });
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({ datasetId: 'dataset-1', token: undefined });
    });
  });

  it('clears a typed token on cancel without submitting it', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} />);

    await openDialog(user);
    await user.type(screen.getByLabelText('Access token (optional)'), 'abandoned-token');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(mutateAsync).not.toHaveBeenCalled();
    await openDialog(user);
    expect(screen.getByLabelText('Access token (optional)')).toHaveValue('');
  });

  it.each([
    [
      'dataset_busy',
      'A refresh is already running for this dataset. Wait for it to finish, then try again.',
    ],
    [
      'origin_changed',
      "This dataset's source changed while the refresh was being queued. Review the source and try again.",
    ],
    [
      'credential_store_unavailable',
      "This install can't stage a service credential right now. Refreshing without a token still works for public sources.",
    ],
  ])('renders the %s refusal as a distinct inline message, not a toast', async (_code, message) => {
    const { toast } = await import('sonner');
    mutateAsync.mockRejectedValue(new ApiError(message, 409));
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    // The dialog stays open on failure — the user can fix and retry (e.g.
    // origin_changed) without losing the flow.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('shows the dynamic token-policy text for invalid_service_token without a static fallback', async () => {
    mutateAsync.mockRejectedValue(
      new ApiError(
        'The token was rejected: This service requires a base64url token (letters, digits, "-", "_").',
        422,
      ),
    );
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    expect(
      await screen.findByText(
        'The token was rejected: This service requires a base64url token (letters, digits, "-", "_").',
      ),
    ).toBeInTheDocument();
  });

  it('disables the trigger and explains why while a run is already active', () => {
    mockUseDatasetRefreshRuns.mockReturnValue({
      data: { runs: [makeRun({ status: 'running' })], total: 1 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRefreshRuns>);

    render(<SourceRefreshAction dataset={makeDataset()} />);

    expect(screen.getByRole('button', { name: 'Refresh from source' })).toBeDisabled();
    expect(
      screen.getByText('A refresh is already in progress. See refresh history below.'),
    ).toBeInTheDocument();
  });

  // fix(#1285 codex round 2): round 1 invalidated dataset detail on an
  // observed active→terminal TRANSITION, which never fires if the run is
  // already terminal on the first poll after dispatch — a fast strategy
  // (postgis remeasurement can finish in ~1s) can beat the refetch. Fixed by
  // tracking the run_id from the 202 response and invalidating the first
  // time THAT run is observed terminal, whether or not it was ever seen
  // active. `dispatchRefresh` below drives the real dialog flow so
  // dispatchedRunIdRef is populated the way production code populates it,
  // not injected directly.
  async function dispatchRefresh(user: ReturnType<typeof userEvent.setup>, runId: string) {
    mutateAsync.mockResolvedValue({
      run_id: runId,
      job_id: 'job-x',
      dataset_id: 'dataset-1',
      origin_kind: 'service',
      trigger: 'api',
      status: 'pending',
      message: 'Refresh queued from the stored source',
    });
    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  }

  it('re-enables the trigger and invalidates the dataset detail query once OUR dispatched run turns terminal', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const user = userEvent.setup();
    mockNoActiveRun();

    const { rerender } = rtlRender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );

    await dispatchRefresh(user, 'run-99');
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: queryKeys.datasets.detail('dataset-1') });

    // First poll after dispatch: our run shows up active.
    mockUseDatasetRefreshRuns.mockReturnValue({
      data: { runs: [makeRun({ id: 'run-99', status: 'running' })], total: 1 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRefreshRuns>);
    rerender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('button', { name: 'Refresh from source' })).toBeDisabled();
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: queryKeys.datasets.detail('dataset-1') });

    // Next poll: terminal.
    mockUseDatasetRefreshRuns.mockReturnValue({
      data: {
        runs: [makeRun({ id: 'run-99', status: 'succeeded', finished_at: '2026-08-05T00:02:00Z', feature_count_after: 44 })],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRefreshRuns>);
    rerender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Refresh from source' })).not.toBeDisabled();
    });
    const invalidationCount = (queryKey: unknown) =>
      invalidateSpy.mock.calls.filter(
        ([call]) => JSON.stringify(call?.queryKey) === JSON.stringify(queryKey),
      ).length;
    expect(invalidationCount(queryKeys.datasets.detail('dataset-1'))).toBe(1);
    // fix(#1285 codex round 3): a successful service refresh writes a new
    // DatasetVersion; the 120s staleTime on the versions query means
    // nothing else refetches it.
    expect(invalidationCount(queryKeys.datasets.versionsPrefix('dataset-1'))).toBe(1);

    // A later poll re-observing the SAME terminal run (nothing changed)
    // must not invalidate a second time — invalidatedRunIdRef's job.
    rerender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );
    expect(invalidationCount(queryKeys.datasets.detail('dataset-1'))).toBe(1);
    expect(invalidationCount(queryKeys.datasets.versionsPrefix('dataset-1'))).toBe(1);
  });

  it('invalidates the dataset detail query even when our dispatched run is already terminal on first observation', async () => {
    // The exact race codex flagged: nothing ever samples this run as
    // pending/running — the first data the component sees for run_id
    // "run-fast" already reports it done.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const user = userEvent.setup();
    mockNoActiveRun();

    const { rerender } = rtlRender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );

    await dispatchRefresh(user, 'run-fast');

    mockUseDatasetRefreshRuns.mockReturnValue({
      data: { runs: [makeRun({ id: 'run-fast', status: 'succeeded', feature_count_after: 44 })], total: 1 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRefreshRuns>);
    rerender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.datasets.detail('dataset-1') });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.datasets.versionsPrefix('dataset-1') });
  });

  it('does not invalidate for a run this component never dispatched, even if it is already terminal on mount', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    mockUseDatasetRefreshRuns.mockReturnValue({
      data: { runs: [makeRun({ status: 'succeeded' })], total: 1 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRefreshRuns>);

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <SourceRefreshAction dataset={makeDataset()} />
      </QueryClientProvider>,
    );

    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});

describe('REFRESHABLE_ORIGINS', () => {
  it('mirrors the refresh door dispatch table — service and postgis only, today', () => {
    // fix(#1285 codex round 1): router_refresh.py routes every non-postgis
    // origin through _resolve_service_origin(), which refuses upload,
    // created, and stac with 409 refresh_not_applicable. This is the value
    // DetailPanel gates on; a widened set here without a matching backend
    // strategy would put the "Refresh from source" control back where round
    // 1 found it.
    expect([...REFRESHABLE_ORIGINS].sort()).toEqual(['postgis', 'service']);
  });
});
