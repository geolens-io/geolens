import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import { useDatasetRefreshWatch } from '@/components/dataset/hooks/use-dataset';
import { SourceRefreshAction } from '../SourceRefreshAction';
import type { DatasetRefreshRunListResponse, DatasetRefreshResponse, DatasetResponse } from '@/types/api';

/**
 * fix(#1285 codex round 4): the root-cause test. SourceRefreshAction used to
 * own its dispatched-run tracking and poll directly, but it lives inside the
 * "sources" Radix TabsContent, which unmounts on tab switch — a refresh that
 * finished while the user was on another tab never invalidated anything.
 * useDatasetRefreshWatch is meant to be mounted at the dataset PAGE level
 * instead, where it survives every tab switch. This test proves that
 * end-to-end: mount the watch in a harness that stands in for the page,
 * dispatch through the real dialog, unmount SourceRefreshAction (the tab
 * switch), let the run complete off-screen, and confirm the trigger
 * re-enables the moment the tab (and SourceRefreshAction) comes back —
 * which is only possible if `watch`, not the unmounted component, tracked
 * the completion.
 */
vi.mock('@/api/datasets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/datasets')>();
  return {
    ...actual,
    refreshDataset: vi.fn(),
    getDatasetRefreshRuns: vi.fn(),
  };
});

import { refreshDataset, getDatasetRefreshRuns } from '@/api/datasets';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockRefreshDataset = vi.mocked(refreshDataset);
const mockGetDatasetRefreshRuns = vi.mocked(getDatasetRefreshRuns);

function makeDataset(): DatasetResponse {
  return {
    id: 'dataset-1',
    record_id: 'record-1',
    table_name: 'roads',
    title: 'Roads',
    summary: null,
    srid: 4326,
    geometry_type: 'LineString',
    feature_count: 40,
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
  };
}

const dataset = makeDataset();

/**
 * Stands in for DatasetPage: useDatasetRefreshWatch mounted here, once, for
 * the harness's whole lifetime. SourceRefreshAction is rendered only while
 * `showSourceTab` is true, mirroring how DetailPanel only mounts it inside
 * the active "sources" TabsContent.
 */
function Harness({ showSourceTab }: { showSourceTab: boolean }) {
  const watch = useDatasetRefreshWatch(dataset.id);
  return (
    <>
      {showSourceTab && <SourceRefreshAction dataset={dataset} watch={watch} />}
      <div data-testid="is-busy">{String(watch.isBusy)}</div>
    </>
  );
}

function makeRun(status: string): DatasetRefreshRunListResponse {
  return {
    runs: [
      {
        id: 'run-tab-switch',
        dataset_id: 'dataset-1',
        dataset_version_id: status === 'succeeded' ? 'version-2' : null,
        ingest_job_id: 'job-1',
        origin_kind: 'service',
        trigger: 'api',
        status,
        triggered_by: null,
        triggered_by_username: null,
        started_at: '2026-08-05T00:00:00Z',
        claimed_at: '2026-08-05T00:00:01Z',
        finished_at: status === 'succeeded' ? '2026-08-05T00:00:05Z' : null,
        feature_count_before: 40,
        feature_count_after: status === 'succeeded' ? 42 : null,
        schema_diff: null,
        error_code: null,
        error_message: null,
      },
    ],
    total: 1,
  };
}

describe('SourceRefreshAction + useDatasetRefreshWatch (tab-switch survival)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('the trigger re-enables after a dispatched run completes while the Source tab was unmounted', async () => {
    // fix(#831 precedent, VerifyEmailPage.test.tsx): shouldAdvanceTime keeps
    // the mocked promise chains progressing while fake timers still control
    // TanStack's refetchInterval; delay: null keeps userEvent synchronous
    // under them.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });

    mockGetDatasetRefreshRuns.mockResolvedValue({ runs: [], total: 0 });
    const dispatchResponse: DatasetRefreshResponse = {
      run_id: 'run-tab-switch',
      job_id: 'job-1',
      dataset_id: 'dataset-1',
      origin_kind: 'service',
      trigger: 'api',
      status: 'pending',
      message: 'Refresh queued from the stored source',
    };
    mockRefreshDataset.mockResolvedValue(dispatchResponse);

    const { rerender } = render(<Harness showSourceTab />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockGetDatasetRefreshRuns).toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Refresh from source' }));
    await screen.findByRole('dialog');

    // useRefreshDataset's onSuccess invalidates refreshRunsPrefix, which
    // triggers an immediate refetch — arrange for that refetch to already
    // see the run as active, since it lands within the same tick as dispatch.
    mockGetDatasetRefreshRuns.mockResolvedValue(makeRun('running'));
    await user.click(screen.getByRole('button', { name: 'Start refresh' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // feat(#1746 B4): refreshDataset gained a third `auth` argument; this
    // dataset is a 'wfs' origin with no credential entered, so it is
    // undefined same as `token`.
    expect(mockRefreshDataset).toHaveBeenCalledWith('dataset-1', undefined, undefined);
    expect(screen.getByTestId('is-busy')).toHaveTextContent('true');

    // Switch away from the Source tab. In the real app this is Radix Tabs
    // unmounting the inactive TabsContent; here it's just not rendering
    // SourceRefreshAction — the harness (standing in for the page) stays up.
    rerender(<Harness showSourceTab={false} />);
    expect(screen.queryByRole('button', { name: 'Refresh from source' })).not.toBeInTheDocument();

    // The run finishes off-screen. useDatasetRefreshRuns polls every 5s
    // (see use-dataset.ts) regardless of which tab is showing, because the
    // watch that owns it is still mounted in the harness.
    mockGetDatasetRefreshRuns.mockResolvedValue(makeRun('succeeded'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(screen.getByTestId('is-busy')).toHaveTextContent('false');

    // Switch back. The trigger must already be enabled — proving `watch`
    // (never unmounted) tracked the completion, not the component that was
    // gone when it happened.
    rerender(<Harness showSourceTab />);
    expect(screen.getByRole('button', { name: 'Refresh from source' })).not.toBeDisabled();
  });
});
