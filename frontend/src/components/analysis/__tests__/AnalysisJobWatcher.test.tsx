import { act, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AnalysisJobWatcher } from '../AnalysisJobWatcher';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import {
  ANALYSIS_JOB_STORAGE_KEY,
  analysisAddToMap,
  useAnalysisAddedStore,
  useAnalysisJobStore,
} from '@/stores/analysis-job-store';
import { useAuthStore } from '@/stores/auth-store';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { ApiError } from '@/api/client';
import type { UserResponse } from '@/types/api';

const navigate = vi.fn();
vi.mock('react-router', () => ({ useNavigate: () => navigate }));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock('@/components/import/hooks/use-ingest', () => ({ useJobStatus: vi.fn() }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Interpolates every {{placeholder}} from options, not just one: the
    // assertions below check that real values (a dataset title, a job error)
    // reach the user, which a mock returning the raw template would fake.
    t: (key: string, options?: Record<string, unknown>) =>
      String(options?.defaultValue ?? key).replace(
        /\{\{(\w+)\}\}/g,
        (_match, name: string) => String(options?.[name] ?? ''),
      ),
  }),
}));

function renderWatcher() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <AnalysisJobWatcher />
    </QueryClientProvider>,
  );
}

function mockJob(data: unknown, error: unknown = null) {
  vi.mocked(useJobStatus).mockReturnValue({
    data,
    error,
  } as unknown as ReturnType<typeof useJobStatus>);
}

describe('AnalysisJobWatcher', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAnalysisJobStore.setState({ job: null, completedAt: null });
    localStorage.removeItem(ANALYSIS_JOB_STORAGE_KEY);
    useAnalysisAddedStore.setState({ addedDatasetIds: [], pendingAddIds: [] });
    analysisAddToMap.current = null;
    analysisAddToMap.mapId = null;
  });

  it('fix(#793 review): a completed job clears the remembered form title for its map', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Walkshed', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();
    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    // Restoring the finished run's name would re-enable Create with it and
    // invite an identically-named duplicate; the rest of the form survives.
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('');
    expect(useAnalysisFormStore.getState().forms['m1']?.distance).toBe('500');
  });

  it('fix(#793 review): a FAILED job keeps the remembered title for the retry', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Walkshed', mapId: 'm1' } });
    mockJob({ status: 'failed', dataset_id: null, error_message: 'no features' });
    renderWatcher();
    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    // Nothing was created — re-entering the name to retry would be pure loss.
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('Walkshed');
  });

  it('fix(#793 review): a title edited after the run started is not cleared', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'My next run',
      // The panel stamps this whenever the form changes mid-run.
      runDisowned: true,
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Walkshed', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();
    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('My next run');
  });

  it('fix(#793 review): a disowned draft reusing the run name survives completion', async () => {
    // Title equality is NOT ownership: the next draft may deliberately reuse
    // the same permitted, non-unique dataset name.
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
      runDisowned: true,
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Walkshed', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();
    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('Walkshed');
  });

  it('fix(#793 review): a swept (404) job also clears the remembered title', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Walkshed', mapId: 'm1' } });
    mockJob(undefined, new ApiError('Not Found', 404));
    renderWatcher();
    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    // The run may have completed before the retention sweep — restoring its
    // name would re-enable Create with it, the duplicate-creation state.
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('');
  });

  it('does nothing while the job is still running', () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    renderWatcher();
    expect(toast.success).not.toHaveBeenCalled();
    expect(useAnalysisJobStore.getState().job).not.toBeNull();
  });

  // fix(#1677): the cancel control made `cancelled` a reachable TERMINAL
  // status for every job type. `useJobStatus` already stopped polling on it,
  // but this watcher cleared only on complete/failed — so a cancelled
  // analysis job stayed in the PERSISTED store forever, survived reloads, and
  // the Analysis panel's Create button (gated on `!!s.job`) never re-enabled
  // short of logging out or clearing site data.
  it('treats a cancelled job as terminal: clears the store and releases the gate', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'cancelled', dataset_id: null });
    renderWatcher();

    await waitFor(() =>
      expect(useAnalysisJobStore.getState().job).toBeNull(),
    );
    // The gate the panel reads is the store slot itself.
    expect(useAnalysisJobStore.getState().job).toBeNull();
    // Cancelling is not a failure — the user asked for it.
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalled();
    expect(vi.mocked(toast.info).mock.calls[0][0]).toBe('“Buffered” was cancelled');
  });

  it('persists the cleared state so a reload does not resurrect the gate', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'cancelled', dataset_id: null });
    renderWatcher();

    await waitFor(() =>
      expect(useAnalysisJobStore.getState().job).toBeNull(),
    );
    // The bug's teeth were persistence: the store is zustand/persist-backed,
    // so a stuck job outlived the tab. Assert storage agrees with memory.
    const raw = localStorage.getItem(ANALYSIS_JOB_STORAGE_KEY);
    expect(raw ? JSON.parse(raw).state.job : null).toBeNull();
  });

  it('raises a non-expiring named toast on completion and stops tracking', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const [message, options] = vi.mocked(toast.success).mock.calls[0];
    expect(message).toBe('“Buffered” is ready');
    // A long job lands after attention has moved on — the notification has to wait.
    expect(options?.duration).toBe(Infinity);
    expect(useAnalysisJobStore.getState().job).toBeNull();
  });

  // feat(#1008): two builders open means two watchers polling the same job.
  // Without a claim each raises its own toast and its own invalidation — the
  // per-job toastId only collapses StrictMode's double invoke within one tab.
  it('stays silent when another tab already claimed the completion', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    // Seeded AFTER the setState above, which writes the store through and
    // would otherwise flatten the foreign claim back to null.
    localStorage.setItem(
      ANALYSIS_JOB_STORAGE_KEY,
      JSON.stringify({
        state: {
          job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' },
          completedAt: { jobId: 'j1', tabId: 'some-other-tab', at: Date.now() },
        },
        version: 1,
      }),
    );
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    mockJob({ status: 'complete', dataset_id: 'ds9' });

    renderWatcher();

    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    expect(toast.success).not.toHaveBeenCalled();
    // fix(#1008 codex P2): the claim dedups REPORTING, not refreshing. This
    // tab has its own QueryClient and focus-refetch is off, so skipping the
    // invalidation would leave it showing a catalog without the new dataset.
    expect(invalidate).toHaveBeenCalledTimes(2);
    // The local cleanup still runs: this tab's Create button has to re-enable,
    // and the finished run's name must not come back with it.
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('');
    invalidate.mockRestore();
  });

  it('stays silent on a FAILED job another tab already claimed', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    localStorage.setItem(
      ANALYSIS_JOB_STORAGE_KEY,
      JSON.stringify({
        state: {
          job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' },
          completedAt: { jobId: 'j1', tabId: 'some-other-tab', at: Date.now() },
        },
        version: 1,
      }),
    );
    mockJob({ status: 'failed', dataset_id: null, error_message: 'no features' });

    renderWatcher();

    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('reports exactly once and invalidates its own caches when it wins', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    mockJob({ status: 'complete', dataset_id: 'ds9' });

    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    // Datasets and search, one apiece.
    expect(invalidate).toHaveBeenCalledTimes(2);
    invalidate.mockRestore();
  });

  // fix(#1008 codex P2): a tab throttled through the terminal poll never sees
  // it — the job simply vanishes when the reporting tab's clear propagates.
  // Its QueryClient and its remembered form title are document-local, so
  // without this it keeps a catalog that omits the new dataset and reopens the
  // form with the finished run's name.
  it('runs its local cleanup when another tab clears a completed job', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    // Still running as far as this tab knows.
    mockJob({ status: 'running', dataset_id: null });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    renderWatcher();
    expect(invalidate).not.toHaveBeenCalled();

    // The reporting tab's claim and clear arrive together through the mirror.
    act(() => {
      useAnalysisJobStore.setState({
        job: null,
        completedAt: {
          jobId: 'j1',
          tabId: 'some-other-tab',
          status: 'complete',
          at: Date.now(),
        },
      });
    });

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('');
    // Reporting still belongs to the tab that claimed it.
    expect(toast.success).not.toHaveBeenCalled();
    invalidate.mockRestore();
  });

  // fix(#1008 codex P2, second pass): a resuming tab rehydrates from the
  // latest payload, so it can go straight from job1 to job2 without ever
  // rendering null. job1's cleanup is owed all the same.
  it('runs the cleanup when a completed job is replaced by the next one', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    renderWatcher();

    act(() => {
      useAnalysisJobStore.setState({
        job: { jobId: 'j2', title: 'Next run', mapId: 'm1' },
        completedAt: {
          jobId: 'j1',
          tabId: 'some-other-tab',
          status: 'complete',
          at: Date.now(),
        },
      });
    });

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('');
    // ...and the replacement run is still being tracked.
    expect(useAnalysisJobStore.getState().job?.jobId).toBe('j2');
    invalidate.mockRestore();
  });

  it('waits for the claim when it arrives after the job is replaced', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    renderWatcher();

    // The two storage writes need not land on one render.
    act(() => {
      useAnalysisJobStore.setState({ job: { jobId: 'j2', title: 'Next', mapId: 'm1' } });
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      useAnalysisJobStore.setState({
        completedAt: {
          jobId: 'j1',
          tabId: 'some-other-tab',
          status: 'complete',
          at: Date.now(),
        },
      });
    });

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    invalidate.mockRestore();
  });

  // fix(#1008 codex P2, third pass): a tab suspended across two whole runs
  // resumes to a claim naming the second while it still remembers the first.
  // Refreshing is not job-specific — one invalidation re-reads the whole
  // catalog — so it has to fire on the claim it can see, not on an id match.
  it('refreshes on a claim for a run it never tracked', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    renderWatcher();

    // It slept through j1 finishing, j2 starting, and j2 finishing.
    act(() => {
      useAnalysisJobStore.setState({
        job: null,
        completedAt: {
          jobId: 'j2',
          tabId: 'some-other-tab',
          status: 'complete',
          at: Date.now(),
        },
      });
    });

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    invalidate.mockRestore();
  });

  // fix(#1008 codex P2, fourth pass): claim and clear are separate persisted
  // writes and arrive in either order, and a swept job departs with no claim
  // at all. Retiring the remembered title therefore keys on the departure of
  // the run this tab was showing, not on a claim turning up to explain it.
  it('retires the remembered title when the claim lands before the clear', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    renderWatcher();

    // The claim's storage event is processed first...
    act(() => {
      useAnalysisJobStore.setState({
        completedAt: {
          jobId: 'j1',
          tabId: 'some-other-tab',
          status: 'complete',
          at: Date.now(),
        },
      });
    });
    // ...and the clear arrives on its own.
    act(() => {
      useAnalysisJobStore.setState({ job: null });
    });

    await waitFor(() =>
      expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe(''),
    );
  });

  it('retires the remembered title when a swept job departs with no claim', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    renderWatcher();

    // Another tab got the 401/403/404 and cleared. No claim is ever written
    // for a swept run, so waiting for one would keep the name forever.
    act(() => {
      useAnalysisJobStore.setState({ job: null });
    });

    await waitFor(() =>
      expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe(''),
    );
  });

  it('keeps the remembered title when the claim says the run failed', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
      joinLayerId: '__none__', joinField: '__none__',
      outputTitle: 'Walkshed',
    });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    renderWatcher();

    act(() => {
      useAnalysisJobStore.setState({
        job: null,
        completedAt: {
          jobId: 'j1',
          tabId: 'some-other-tab',
          status: 'failed',
          at: Date.now(),
        },
      });
    });

    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    // Nothing was created — re-entering the name to retry would be pure loss.
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('Walkshed');
  });

  // fix(#1008 codex P2, fifth pass): a tab suspended while one run succeeded
  // and a later one failed resumes to the failed claim only. Gating the
  // refresh on the status would leave it a catalog missing the first run's
  // dataset, with nothing to correct it.
  it('refreshes on a failed claim too, since an earlier run may have succeeded', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    renderWatcher();

    act(() => {
      useAnalysisJobStore.setState({
        job: null,
        completedAt: {
          jobId: 'j2',
          tabId: 'some-other-tab',
          status: 'failed',
          at: Date.now(),
        },
      });
    });

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    invalidate.mockRestore();
  });

  it('does not refresh when the job is cleared without a completion claim', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'running', dataset_id: null });
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    renderWatcher();

    // A logout or an identity change clears the job with no claim behind it —
    // nothing was created, so there is nothing to refresh.
    act(() => {
      useAnalysisJobStore.setState({ job: null, completedAt: null });
    });

    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    expect(invalidate).not.toHaveBeenCalled();
    invalidate.mockRestore();
  });

  it('offers Add to map only when a builder for that map is mounted', async () => {
    const onAdd = vi.fn();
    analysisAddToMap.current = onAdd;
    analysisAddToMap.mapId = 'm1';
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const action = vi.mocked(toast.success).mock.calls[0][1]?.action as {
      label: string;
      onClick: () => void;
    };
    expect(action.label).toBe('Add to map');
    action.onClick();
    expect(onAdd).toHaveBeenCalledWith('ds9');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('falls back to viewing the dataset when the builder is gone', async () => {
    analysisAddToMap.mapId = 'a-different-map';
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: '', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(toast.success).mock.calls[0][0]).toBe('Dataset created');
    const action = vi.mocked(toast.success).mock.calls[0][1]?.action as {
      label: string;
      onClick: () => void;
    };
    expect(action.label).toBe('View dataset');
    action.onClick();
    expect(navigate).toHaveBeenCalledWith('/datasets/ds9');
  });

  it('reports failures with the job error message', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'failed', dataset_id: null, error_message: 'no features' });
    renderWatcher();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0][0]).toContain('no features');
    expect(useAnalysisJobStore.getState().job).toBeNull();
  });

  it('the Add to map toast action adds only once', async () => {
    // Sonner dismisses the toast on action click, but the exit animation
    // leaves a window for a second click — the add must not repeat.
    const onAdd = vi.fn();
    analysisAddToMap.current = onAdd;
    analysisAddToMap.mapId = 'm1';
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const action = vi.mocked(toast.success).mock.calls[0][1]?.action as {
      label: string;
      onClick: () => void;
    };
    action.onClick();
    action.onClick();
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  // fix(#833): the single-use guard is shared with the Analysis panel's own
  // "Add to map" button — each affordance used to dedupe only against itself,
  // so clicking the toast action and then the panel button added twice.
  it('the toast action shares its single-use marker via useAnalysisAddedStore', async () => {
    const onAdd = vi.fn();
    analysisAddToMap.current = onAdd;
    analysisAddToMap.mapId = 'm1';
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9' });
    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const action = vi.mocked(toast.success).mock.calls[0][1]?.action as {
      label: string;
      onClick: () => void;
    };

    // The panel button already added this dataset — the toast must not repeat.
    useAnalysisAddedStore.getState().confirmAdded('ds9');
    action.onClick();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('surfaces the persisted warning_message beside the completion toast', async () => {
    // The backend stores a collision note (e.g. a renamed output) in
    // warning_message; the watcher is the only completion surface once the
    // panel is closed, so it has to say so — mirrors JobProgress's upload
    // warning toast.
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({
      status: 'complete',
      dataset_id: 'ds9',
      warning_message: 'Renamed to “Buffered (2)” to avoid a collision',
    });
    renderWatcher();

    await waitFor(() => expect(toast.warning).toHaveBeenCalled());
    expect(vi.mocked(toast.warning).mock.calls[0][0]).toContain('Renamed');
    // The success toast still fires alongside it.
    expect(toast.success).toHaveBeenCalled();
  });

  it('raises no warning toast when the job completed clean', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'complete', dataset_id: 'ds9', warning_message: null });
    renderWatcher();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.warning).not.toHaveBeenCalled();
  });

  it('offers an Open map recovery action on the failure toast', async () => {
    // The failure toast dead-ended with no way back to the run; the success
    // branch has an action, so the failure branch mirrors it. The remembered
    // form keeps the failed run's name for the retry.
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: 'm1' } });
    mockJob({ status: 'failed', dataset_id: null, error_message: 'no features' });
    renderWatcher();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const options = vi.mocked(toast.error).mock.calls[0][1] as {
      action?: { label: string; onClick: () => void };
    };
    expect(options.action?.label).toBe('Open map');
    options.action?.onClick();
    expect(navigate).toHaveBeenCalledWith('/maps/m1');
  });

  it('omits the recovery action when the failed job has no map', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'Buffered', mapId: null } });
    mockJob({ status: 'failed', dataset_id: null, error_message: 'no features' });
    renderWatcher();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const options = vi.mocked(toast.error).mock.calls[0][1] as {
      action?: { label: string; onClick: () => void };
    };
    expect(options.action).toBeUndefined();
  });

  it('clears the tracked job when the signed-in user changes', () => {
    // The store persists across reloads, so without the identity guard the
    // next account on this browser inherits the previous user's run.
    useAuthStore.setState({ user: { id: 'u1' } as UserResponse });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'x', mapId: null } });
    useAuthStore.setState({ user: { id: 'u2' } as UserResponse });
    expect(useAnalysisJobStore.getState().job).toBeNull();
  });

  it('keeps the tracked job through a token rotation for the same user', () => {
    // Keyed on user identity, not token — refresh-token rotation must not
    // drop a job mid-run.
    useAuthStore.setState({ user: { id: 'u1' } as UserResponse, token: 't1' });
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'x', mapId: null } });
    useAuthStore.setState({ token: 't2' });
    expect(useAnalysisJobStore.getState().job).not.toBeNull();
  });

  it('stops tracking a job that is gone instead of polling forever', async () => {
    useAnalysisJobStore.setState({ job: { jobId: 'gone', title: 'x', mapId: null } });
    mockJob(undefined, new ApiError('Not Found', 404));
    renderWatcher();

    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('keeps tracking through a transient failure (fix(#682) review)', () => {
    // A 5xx or dropped connection after a reload must not discard the job:
    // polling continues, so tracking recovers on the next good response.
    useAnalysisJobStore.setState({ job: { jobId: 'j1', title: 'x', mapId: null } });
    mockJob(undefined, new ApiError('Service Unavailable', 503));
    renderWatcher();

    expect(useAnalysisJobStore.getState().job).not.toBeNull();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('keeps tracking a long-running job — no client staleness rule (fix(#682) review)', () => {
    // Deliberately mirrors the API's cap, which also has no staleness window.
    // Dropping a job on elapsed time loses its completion notification for
    // good, and the endpoint would still refuse a replacement anyway.
    useAnalysisJobStore.setState({ job: { jobId: 'slow', title: 'x', mapId: null } });
    mockJob({ status: 'running' });
    renderWatcher();

    expect(useAnalysisJobStore.getState().job).not.toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
