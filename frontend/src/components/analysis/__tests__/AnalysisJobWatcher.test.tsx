import { render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AnalysisJobWatcher } from '../AnalysisJobWatcher';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import { analysisAddToMap, useAnalysisAddedStore, useAnalysisJobStore } from '@/stores/analysis-job-store';
import { useAuthStore } from '@/stores/auth-store';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { ApiError } from '@/api/client';
import type { UserResponse } from '@/types/api';

const navigate = vi.fn();
vi.mock('react-router', () => ({ useNavigate: () => navigate }));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
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
    useAnalysisJobStore.setState({ job: null });
    useAnalysisAddedStore.setState({ addedDatasetIds: [] });
    analysisAddToMap.current = null;
    analysisAddToMap.mapId = null;
  });

  it('fix(#793 review): a completed job clears the remembered form title for its map', async () => {
    useAnalysisFormStore.getState().save('m1', {
      layerId: 'l1', operation: 'buffer', distance: '500', distanceUnit: 'm',
      mask: null, maskLayerId: '__none__', byField: '__none__',
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
    useAnalysisAddedStore.getState().markAdded('ds9');
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
