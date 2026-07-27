import { render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AnalysisJobWatcher } from '../AnalysisJobWatcher';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import { analysisAddToMap, useAnalysisJobStore } from '@/stores/analysis-job-store';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { ApiError } from '@/api/client';

const navigate = vi.fn();
vi.mock('react-router', () => ({ useNavigate: () => navigate }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
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
