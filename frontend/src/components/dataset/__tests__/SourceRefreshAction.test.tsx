import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import { useRefreshDataset } from '@/components/dataset/hooks/use-dataset';
import { ApiError } from '@/api/client';
import { arcgisSignIn } from '@/api/arcgis-signin';
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

// fix(#1755 item 4): lane A1's sign-in endpoint. Mocked here per the plan's
// contract (portal_url/username/password in, token/expires_at out) since
// this lane builds against that contract rather than a live backend.
vi.mock('@/api/arcgis-signin', () => ({
  arcgisSignIn: vi.fn(),
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
const mockArcgisSignIn = vi.mocked(arcgisSignIn);
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

  // fix(#1755 item 4, plan 3.7): the refresh door's own 422 detail. The
  // `message` field is a diagnostic sentence aimed at an API client, not UI
  // copy -- it must never reach the DOM, and this suite pins that alongside
  // the credential prompt it triggers instead.
  const RAW_SERVICE_TOKEN_MESSAGE =
    "This dataset's source needed a service token the last time it was imported or refreshed, and this request carries none. Send the token again in the request body's `token` field; tokens are request-only and are never stored between runs. If the source is public now, re-import it through the re-upload dialog without a token to clear the requirement.";

  function serviceTokenRequiredError() {
    return new ApiError('service_token_required', 422, {
      code: 'service_token_required',
      message: RAW_SERVICE_TOKEN_MESSAGE,
    });
  }

  // codex #1759 round 2: the ArcGIS credential block now schedules a clear
  // for `expires_at` minus a safety margin, so any test that mints a token
  // without exercising expiry itself needs an `expires_at` safely in the
  // future relative to whenever the suite actually runs -- a fixed literal
  // date goes stale (and the timer fires almost immediately, wiping the
  // "Signed in" state before an assertion ever sees it).
  const FAR_FUTURE_EXPIRY = new Date(Date.now() + 60 * 60 * 1000).toISOString();

  describe('service_token_required credential prompt', () => {
    it('keeps the dialog open on the 422 and never echoes the raw response text into the DOM', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      const user = userEvent.setup();
      render(<SourceRefreshAction dataset={makeDataset({ source_format: 'wfs' })} watch={makeWatch()} />);

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      await screen.findByText(
        'This source refused the refresh outright because it needs a credential. Send the token again below.',
      );
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(document.body.textContent).not.toContain(RAW_SERVICE_TOKEN_MESSAGE);
    });

    it('shows the ArcGIS sign-in taxonomy for an arcgis_featureserver origin, not the WFS escape hatch', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      expect(await screen.findByLabelText('Authentication method')).toBeInTheDocument();
      expect(
        screen.queryByText(/refused the refresh outright/i),
      ).not.toBeInTheDocument();
    });

    it('shows the outright-refusal copy and the re-upload escape hatch for a WFS origin, not the ArcGIS select', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      const user = userEvent.setup();
      render(<SourceRefreshAction dataset={makeDataset({ source_format: 'wfs' })} watch={makeWatch()} />);

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      expect(
        await screen.findByText(
          'This source refused the refresh outright because it needs a credential. Send the token again below.',
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          'If the source is public now, re-import it through the Re-Upload dialog with no token to clear this requirement.',
        ),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText('Authentication method')).not.toBeInTheDocument();
    });

    it('sends the freshly typed token on retry after a WFS refusal', async () => {
      mutateAsync
        .mockRejectedValueOnce(serviceTokenRequiredError())
        .mockResolvedValueOnce({
          run_id: 'run-7',
          job_id: 'job-7',
          dataset_id: 'dataset-1',
          origin_kind: 'service',
          trigger: 'api',
          status: 'pending',
          message: 'Refresh queued from the stored source',
        });
      const user = userEvent.setup();
      render(<SourceRefreshAction dataset={makeDataset({ source_format: 'wfs' })} watch={makeWatch()} />);

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      await screen.findByText(
        'This source refused the refresh outright because it needs a credential. Send the token again below.',
      );

      await user.type(screen.getByLabelText('Access token (optional)'), 'fresh-bearer-token');
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      await waitFor(() => {
        expect(mutateAsync).toHaveBeenLastCalledWith({
          datasetId: 'dataset-1',
          token: 'fresh-bearer-token',
        });
      });
    });

    it('mints an ArcGIS token via sign-in, clears the password once it lands, and sends the token on retry', async () => {
      mutateAsync
        .mockRejectedValueOnce(serviceTokenRequiredError())
        .mockResolvedValueOnce({
          run_id: 'run-9',
          job_id: 'job-9',
          dataset_id: 'dataset-1',
          origin_kind: 'service',
          trigger: 'api',
          status: 'pending',
          message: 'Refresh queued from the stored source',
        });
      mockArcgisSignIn.mockResolvedValue({
        token: 'minted-token-xyz',
        expires_at: FAR_FUTURE_EXPIRY,
      });
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      const methodSelect = await screen.findByLabelText('Authentication method');
      await user.selectOptions(methodSelect, 'signin');

      await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
      await user.type(screen.getByLabelText('Username'), 'alice');
      await user.type(screen.getByLabelText('Password'), 'hunter2');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));

      await screen.findByText('Signed in. The token below is ready to use.');
      expect(mockArcgisSignIn).toHaveBeenCalledWith({
        portal_url: 'https://myorg.maps.arcgis.com',
        username: 'alice',
        password: 'hunter2',
      });
      expect(screen.getByLabelText('Password')).toHaveValue('');

      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      await waitFor(() => {
        expect(mutateAsync).toHaveBeenLastCalledWith({
          datasetId: 'dataset-1',
          token: 'minted-token-xyz',
        });
      });
    });

    // codex #1759 round 3, P2: "Start refresh" clears the parent's `token`
    // state before awaiting the refresh request, win or lose. Before this
    // fix, the credential block's own `signedIn` flag did not know that --
    // a rejected refresh left it still claiming "Signed in" while the next
    // retry silently submitted no token at all.
    it('reverts to its own sign-in state, with no token, after a rejected refresh that follows a mint', async () => {
      const remoteError = new ApiError('Remote service returned an error', 503);
      mutateAsync
        .mockRejectedValueOnce(serviceTokenRequiredError())
        .mockRejectedValueOnce(remoteError)
        .mockRejectedValue(remoteError);
      mockArcgisSignIn.mockResolvedValue({
        token: 'minted-token-xyz',
        expires_at: FAR_FUTURE_EXPIRY,
      });
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      const methodSelect = await screen.findByLabelText('Authentication method');
      await user.selectOptions(methodSelect, 'signin');
      await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
      await user.type(screen.getByLabelText('Username'), 'alice');
      await user.type(screen.getByLabelText('Password'), 'hunter2');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));
      await screen.findByText('Signed in. The token below is ready to use.');

      // The refresh itself is refused (a transient 503 here; an invalid or
      // expired token on the origin's own side reads the same way to this
      // dialog). The dialog stays open on any refusal.
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      await waitFor(() => {
        expect(
          screen.queryByText('Signed in. The token below is ready to use.'),
        ).not.toBeInTheDocument();
      });
      // Still offering the sign-in method -- not reset to the taxonomy's
      // default -- but with nothing left to submit.
      expect(screen.getByLabelText('Authentication method')).toHaveValue('signin');

      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      await waitFor(() => {
        expect(mutateAsync).toHaveBeenLastCalledWith({ datasetId: 'dataset-1', token: undefined });
      });
    });

    it('maps a rejected ArcGIS sign-in to this component\'s own copy, never the raw response, and never auto-retries', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      mockArcgisSignIn.mockRejectedValue(
        new ApiError('arcgis_signin_rejected', 400, { code: 'arcgis_signin_rejected', message: 'raw' }),
      );
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      const methodSelect = await screen.findByLabelText('Authentication method');
      await user.selectOptions(methodSelect, 'signin');
      await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
      await user.type(screen.getByLabelText('Username'), 'alice');
      await user.type(screen.getByLabelText('Password'), 'wrong-password');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));

      expect(
        await screen.findByText(
          'ArcGIS did not accept that sign-in. Check the username and password, including capitalization. Too many failed attempts also lock an ArcGIS account temporarily.',
        ),
      ).toBeInTheDocument();
      // Exactly one attempt: nothing in this component retries a rejected
      // sign-in automatically (plan 3.2 -- a retry loop can lock the
      // customer's real ArcGIS account).
      expect(mockArcgisSignIn).toHaveBeenCalledTimes(1);
    });

    // codex #1759 round 1, P1: a late arcgisSignIn response landing after
    // the dialog (and this credential block, which SourceRefreshAction
    // unmounts on close) is dismissed must not resurrect a token the user
    // already dismissed.
    it('drops a late ArcGIS sign-in response after the dialog is closed, leaving no token behind', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      let resolveSignIn!: (value: { token: string; expires_at: string }) => void;
      mockArcgisSignIn.mockReturnValue(
        new Promise((resolve) => {
          resolveSignIn = resolve;
        }),
      );
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      const methodSelect = await screen.findByLabelText('Authentication method');
      await user.selectOptions(methodSelect, 'signin');
      await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
      await user.type(screen.getByLabelText('Username'), 'alice');
      await user.type(screen.getByLabelText('Password'), 'hunter2');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));

      // Dismiss the dialog while the sign-in is still in flight. This
      // unmounts ArcgisCredentialBlock (SourceRefreshAction renders it
      // conditionally on `serviceTokenRequired`, which handleOpenChange
      // resets to false on close).
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

      // The response lands after close.
      await act(async () => {
        resolveSignIn({ token: 'late-minted-token', expires_at: FAR_FUTURE_EXPIRY });
        await Promise.resolve();
        await Promise.resolve();
      });

      await openDialog(user);
      expect(screen.getByLabelText('Access token (optional)')).toHaveValue('');
    });

    // codex #1759 round 1, P2: a token minted for one set of credentials
    // must not survive editing those credentials or a rejected retry.
    it('clears a previously minted token as soon as a sign-in field changes, before any new attempt', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      mockArcgisSignIn.mockResolvedValue({
        token: 'first-token',
        expires_at: FAR_FUTURE_EXPIRY,
      });
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      const methodSelect = await screen.findByLabelText('Authentication method');
      await user.selectOptions(methodSelect, 'signin');
      await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
      await user.type(screen.getByLabelText('Username'), 'alice');
      await user.type(screen.getByLabelText('Password'), 'hunter2');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));
      await screen.findByText('Signed in. The token below is ready to use.');

      // Edit a field but do NOT attempt sign-in again -- the field-change
      // handler itself, not only the next attempt's start, must drop the
      // token that no longer describes what's typed.
      await user.type(screen.getByLabelText('Username'), 'x');
      expect(
        screen.queryByText('Signed in. The token below is ready to use.'),
      ).not.toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      await waitFor(() => {
        expect(mutateAsync).toHaveBeenLastCalledWith({ datasetId: 'dataset-1', token: undefined });
      });
    });

    it('clears a previously minted token once a sign-in field changes, so a rejected retry submits nothing', async () => {
      mutateAsync.mockRejectedValue(serviceTokenRequiredError());
      mockArcgisSignIn
        .mockResolvedValueOnce({ token: 'first-token', expires_at: FAR_FUTURE_EXPIRY })
        .mockRejectedValueOnce(
          new ApiError('arcgis_signin_rejected', 400, { code: 'arcgis_signin_rejected', message: 'raw' }),
        );
      const user = userEvent.setup();
      render(
        <SourceRefreshAction
          dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
          watch={makeWatch()}
        />,
      );

      await openDialog(user);
      await user.click(screen.getByRole('button', { name: 'Start refresh' }));
      const methodSelect = await screen.findByLabelText('Authentication method');
      await user.selectOptions(methodSelect, 'signin');
      await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
      await user.type(screen.getByLabelText('Username'), 'alice');
      await user.type(screen.getByLabelText('Password'), 'hunter2');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));
      await screen.findByText('Signed in. The token below is ready to use.');

      // Editing a field after a successful mint invalidates that token --
      // the fields no longer describe the account it was minted for.
      await user.clear(screen.getByLabelText('Username'));
      await user.type(screen.getByLabelText('Username'), 'bob');
      await user.type(screen.getByLabelText('Password'), 'wrong-password');
      await user.click(screen.getByRole('button', { name: 'Sign in' }));

      await screen.findByText(
        'ArcGIS did not accept that sign-in. Check the username and password, including capitalization. Too many failed attempts also lock an ArcGIS account temporarily.',
      );

      await user.click(screen.getByRole('button', { name: 'Start refresh' }));

      await waitFor(() => {
        expect(mutateAsync).toHaveBeenLastCalledWith({ datasetId: 'dataset-1', token: undefined });
      });
    });

    // codex #1759 round 2: the refresh door only stages a credential and
    // queues the worker, so a dialog left open past the minted token's
    // lifetime would otherwise submit one already dead on the wire, and
    // the failure would only surface later in the background.
    describe('ArcGIS token expiry', () => {
      afterEach(() => {
        vi.useRealTimers();
      });

      async function signInSuccessfully(user: ReturnType<typeof userEvent.setup>, expiresAt: string) {
        mockArcgisSignIn.mockResolvedValue({ token: 'short-lived-token', expires_at: expiresAt });
        await openDialog(user);
        await user.click(screen.getByRole('button', { name: 'Start refresh' }));
        const methodSelect = await screen.findByLabelText('Authentication method');
        await user.selectOptions(methodSelect, 'signin');
        await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
        await user.type(screen.getByLabelText('Username'), 'alice');
        await user.type(screen.getByLabelText('Password'), 'hunter2');
        await user.click(screen.getByRole('button', { name: 'Sign in' }));
        await screen.findByText('Signed in. The token below is ready to use.');
      }

      it('expires a minted token while the dialog stays open, clearing it and swapping the copy', async () => {
        mutateAsync.mockRejectedValue(serviceTokenRequiredError());
        // fix(#831 precedent, VerifyEmailPage.test.tsx): shouldAdvanceTime
        // keeps the mocked arcgisSignIn promise progressing while fake
        // timers also control the scheduled expiry; delay: null keeps
        // userEvent synchronous under them.
        vi.useFakeTimers({ shouldAdvanceTime: true });
        const user = userEvent.setup({ delay: null });
        render(
          <SourceRefreshAction
            dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
            watch={makeWatch()}
          />,
        );

        await signInSuccessfully(user, new Date(Date.now() + 60_000).toISOString());

        // Past expires_at minus the 30s safety margin, but before the raw
        // expiry itself -- proves the margin, not just the raw timestamp,
        // drives the clear.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(31_000);
        });

        expect(
          screen.queryByText('Signed in. The token below is ready to use.'),
        ).not.toBeInTheDocument();
        expect(
          await screen.findByText('The token expired. Sign in again to continue.'),
        ).toBeInTheDocument();

        await user.click(screen.getByRole('button', { name: 'Start refresh' }));
        await waitFor(() => {
          expect(mutateAsync).toHaveBeenLastCalledWith({ datasetId: 'dataset-1', token: undefined });
        });
      });

      it('clears the scheduled expiry timer when the dialog closes, so it never fires', async () => {
        mutateAsync.mockRejectedValue(serviceTokenRequiredError());
        vi.useFakeTimers({ shouldAdvanceTime: true });
        const user = userEvent.setup({ delay: null });
        const setTimeoutSpy = vi.spyOn(global, 'setTimeout');
        const clearTimeoutSpy = vi.spyOn(global, 'clearTimeout');
        render(
          <SourceRefreshAction
            dataset={makeDataset({ source_format: 'arcgis_featureserver' })}
            watch={makeWatch()}
          />,
        );

        // A long-lived token so the expiry timer's delay (minutes) is
        // unambiguous against whatever short-delay timers userEvent/jsdom
        // themselves schedule under fake timers.
        await signInSuccessfully(user, new Date(Date.now() + 60 * 60 * 1000).toISOString());

        const expiryTimerCallIndex = setTimeoutSpy.mock.calls.findIndex(
          ([, delay]) => typeof delay === 'number' && delay > 10_000,
        );
        expect(expiryTimerCallIndex).toBeGreaterThanOrEqual(0);
        const expiryTimerId = setTimeoutSpy.mock.results[expiryTimerCallIndex]?.value;

        await user.click(screen.getByRole('button', { name: 'Cancel' }));
        // Not just "cleared something" -- cleared THIS timer specifically.
        expect(clearTimeoutSpy).toHaveBeenCalledWith(expiryTimerId);

        // Advancing well past the original expiry raises nothing further --
        // the block that owned the timer is gone.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(2 * 60 * 60 * 1000);
        });
      });
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
