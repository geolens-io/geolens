import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import { useRefreshDataset } from '@/components/dataset/hooks/use-dataset';
import { ApiError } from '@/api/client';
import { REFRESHABLE_ORIGINS, SourceRefreshAction } from '../SourceRefreshAction';
import type { DatasetRefreshWatch } from '@/components/dataset/hooks/use-dataset';
import type { DatasetResponse } from '@/types/api';

// fix(#1285 codex round 4): SourceRefreshAction no longer owns run-tracking
// (that moved to useDatasetRefreshWatch, mounted at the page level so it
// survives a tab switch away from "sources" — see use-dataset.ts). This
// component only dispatches and reports the run_id to a `watch` prop, so
// useDatasetRefreshRuns no longer needs mocking here at all.
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useRefreshDataset: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// fix(#1285 codex round 6): mirrors the mock convention DatasetPage's own
// tests use (DatasetPage.edit-affordances.test.tsx) for this same store.
const drawingStoreState = vi.hoisted(() => ({
  selectedFeature: null as { gid: number; tdId: string; properties: Record<string, unknown> } | null,
  isEditDirty: false,
  targetDatasetId: null as string | null,
}));

vi.mock('@/stores/drawing-store', () => ({
  useDrawingStore: (selector: (state: typeof drawingStoreState) => unknown) =>
    selector(drawingStoreState),
}));

const mockUseRefreshDataset = vi.mocked(useRefreshDataset);
const mutateAsync = vi.fn();
const trackDispatchedRun = vi.fn();

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
    attribution: null,
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

function makeWatch(overrides: Partial<DatasetRefreshWatch> = {}): DatasetRefreshWatch {
  return {
    latestRun: undefined,
    isBusy: false,
    trackDispatchedRun,
    ...overrides,
  };
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
    drawingStoreState.selectedFeature = null;
    drawingStoreState.isEditDirty = false;
    drawingStoreState.targetDatasetId = null;
  });

  it('opens a confirm dialog with an optional token field for a service origin', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);

    expect(screen.getByLabelText('Access token (optional)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start refresh' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  // fix(#1746): this is a request-only service token, not a login credential.
  // autoComplete="off" alone does not stop Chrome from offering a saved
  // password on a password-type field, so every password manager needs an
  // explicit opt-out.
  it('opts every password manager out of the refresh token field', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);

    const input = screen.getByLabelText('Access token (optional)');
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(input).toHaveAttribute('data-bwignore');
  });

  // fix(#1285 codex round 3): _dispatch_postgis_refresh() rejects ANY
  // nonempty token with 422 credential_not_applicable — a registered table
  // needs no service credential. Offering the field here invites a
  // guaranteed failure, so it must not render for this origin.
  it('does not offer a token field for a postgis origin', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset({ origin: 'postgis' })} watch={makeWatch()} />);

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
    render(<SourceRefreshAction dataset={makeDataset({ origin: 'postgis' })} watch={makeWatch()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({ datasetId: 'dataset-1', token: undefined });
    });
  });

  it('dispatches the refresh, closes the dialog, reports the run to the watch, and clears the token from rendered output and state', async () => {
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
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);
    const secretToken = 'super-secret-token-value';
    await user.type(screen.getByLabelText('Access token (optional)'), secretToken);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    expect(mutateAsync).toHaveBeenCalledWith({ datasetId: 'dataset-1', token: secretToken });
    // fix(#1285 codex round 4): the component no longer tracks the dispatched
    // run itself — it must hand the run_id to the page-level watch instead.
    expect(trackDispatchedRun).toHaveBeenCalledWith('run-42');
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
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({ datasetId: 'dataset-1', token: undefined });
    });
  });

  it('clears a typed token on cancel without submitting it', async () => {
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);
    await user.type(screen.getByLabelText('Access token (optional)'), 'abandoned-token');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(trackDispatchedRun).not.toHaveBeenCalled();
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
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    // The dialog stays open on failure — the user can fix and retry (e.g.
    // origin_changed) without losing the flow.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
    expect(trackDispatchedRun).not.toHaveBeenCalled();
  });

  it('shows the dynamic token-policy text for invalid_service_token without a static fallback', async () => {
    mutateAsync.mockRejectedValue(
      new ApiError(
        'The token was rejected: This service requires a base64url token (letters, digits, "-", "_").',
        422,
      ),
    );
    const user = userEvent.setup();
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    expect(
      await screen.findByText(
        'The token was rejected: This service requires a base64url token (letters, digits, "-", "_").',
      ),
    ).toBeInTheDocument();
  });

  it('disables the trigger and explains why when watch.isBusy is true', () => {
    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch({ isBusy: true })} />);

    expect(screen.getByRole('button', { name: 'Refresh from source' })).toBeDisabled();
    expect(
      screen.getByText('A refresh is already in progress. See refresh history below.'),
    ).toBeInTheDocument();
  });

  // fix(#1285 codex round 6, widened on completion): DatasetMap stays
  // mounted above DetailPanel regardless of tab, so a feature selection
  // survives a switch to the Source tab. The hazard does not need an
  // in-progress edit — handleDeleteFeature acts on a merely-selected
  // feature immediately, and a later save would too — so the guard blocks
  // on SELECTION presence, not edit dirtiness. isEditDirty is irrelevant to
  // the gate; both values are exercised below to prove that.
  it('disables the trigger and explains why for a dirty, selected feature edit on this dataset', () => {
    drawingStoreState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingStoreState.isEditDirty = true;
    drawingStoreState.targetDatasetId = 'dataset-1';

    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    expect(screen.getByRole('button', { name: 'Refresh from source' })).toBeDisabled();
    expect(
      screen.getByText('Finish editing or deselect the feature before refreshing.'),
    ).toBeInTheDocument();
  });

  it('also disables for a feature that is merely selected, with no unsaved edit', () => {
    // The completion of the round-6 fix: a clean selection retains the
    // pre-refresh GID just as much as a dirty one, and delete acts on a
    // selection with no dirtiness required at all.
    drawingStoreState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingStoreState.isEditDirty = false;
    drawingStoreState.targetDatasetId = 'dataset-1';

    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    expect(screen.getByRole('button', { name: 'Refresh from source' })).toBeDisabled();
    expect(
      screen.getByText('Finish editing or deselect the feature before refreshing.'),
    ).toBeInTheDocument();
  });

  it('does not block on a feature selection that belongs to a different dataset', () => {
    drawingStoreState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingStoreState.isEditDirty = true;
    drawingStoreState.targetDatasetId = 'a-different-dataset';

    render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    expect(screen.getByRole('button', { name: 'Refresh from source' })).not.toBeDisabled();
  });

  it('re-enables once the feature is saved, deselected, or discarded (selection cleared)', () => {
    drawingStoreState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingStoreState.isEditDirty = true;
    drawingStoreState.targetDatasetId = 'dataset-1';

    const { rerender } = render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);
    expect(screen.getByRole('button', { name: 'Refresh from source' })).toBeDisabled();

    // Mirrors what a save, deselect, or discard does to the store:
    // clearSelectedFeature resets both selectedFeature and isEditDirty.
    drawingStoreState.selectedFeature = null;
    drawingStoreState.isEditDirty = false;
    rerender(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    expect(screen.getByRole('button', { name: 'Refresh from source' })).not.toBeDisabled();
    expect(
      screen.queryByText('Finish editing or deselect the feature before refreshing.'),
    ).not.toBeInTheDocument();
  });

  // fix(#1285 codex round 4): the whole point of lifting tracking into a
  // page-level watch — a dispatch that resolves AFTER the user has already
  // switched away from the Source tab (unmounting this component) must
  // still reach the watch, since it is the caller's (not this component's)
  // state that has to survive.
  it('reports the dispatched run to the watch even if this component unmounts before the request resolves', async () => {
    let resolveMutation!: (value: {
      run_id: string;
      job_id: string;
      dataset_id: string;
      origin_kind: string;
      trigger: string;
      status: string;
      message: string;
    }) => void;
    mutateAsync.mockReturnValue(
      new Promise((resolve) => {
        resolveMutation = resolve;
      }),
    );
    const user = userEvent.setup();
    const { unmount } = render(<SourceRefreshAction dataset={makeDataset()} watch={makeWatch()} />);

    await openDialog(user);
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));

    // Simulate a tab switch away from Source while the request is in flight.
    unmount();
    expect(trackDispatchedRun).not.toHaveBeenCalled();

    resolveMutation({
      run_id: 'run-slow',
      job_id: 'job-slow',
      dataset_id: 'dataset-1',
      origin_kind: 'service',
      trigger: 'api',
      status: 'pending',
      message: 'Refresh queued from the stored source',
    });

    await waitFor(() => {
      expect(trackDispatchedRun).toHaveBeenCalledWith('run-slow');
    });
  });
});

describe('REFRESHABLE_ORIGINS', () => {
  it('mirrors the refresh door dispatch table — the three kinds with a strategy', () => {
    // fix(#1285 codex round 1): router_refresh.py routes every origin it does
    // not name through _resolve_service_origin(), which refuses upload and
    // created with 409 refresh_not_applicable. This is the value DetailPanel
    // gates on; a widened set here without a matching backend strategy would
    // put the "Refresh from source" control back where round 1 found it.
    // feat(#1266): stac gained one.
    expect([...REFRESHABLE_ORIGINS].sort()).toEqual(['postgis', 'service', 'stac']);
  });
});
