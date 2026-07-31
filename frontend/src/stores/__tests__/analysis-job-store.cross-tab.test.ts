import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import {
  ANALYSIS_JOB_STORAGE_KEY,
  useAnalysisJobStore,
  type TrackedAnalysisJob,
} from '@/stores/analysis-job-store';

// feat(#1008): two mechanisms that are easy to conflate.
//
// The MIRROR keeps every tab's view of the in-flight job current, so a second
// builder knows a run is already going and its Create button is disabled
// (`analysisJobRunning` in the Analysis panel is a live store subscription).
//
// The CLAIM is what dedups. Three tabs mirroring the same job all still poll
// it to completion, and each has its own toaster, so the mirror alone yields
// three toasts and three cache invalidations. Exactly one tab may report, and
// the arbiter has to be a written value rather than whoever polled first.

const job: TrackedAnalysisJob = {
  jobId: 'job-1',
  title: 'Buffered parcels',
  mapId: 'map-1',
};

/** Write the payload another tab would have left behind. */
function seedStorage(state: Record<string, unknown>) {
  localStorage.setItem(
    ANALYSIS_JOB_STORAGE_KEY,
    JSON.stringify({ state, version: 1 }),
  );
}

function storedState(): Record<string, unknown> {
  return JSON.parse(localStorage.getItem(ANALYSIS_JOB_STORAGE_KEY)!).state;
}

/**
 * A second tab: a fresh module instance with its own tab id, sharing this
 * realm's localStorage. Importing the module again is the only way to get a
 * distinct claimant, since the store is a module singleton by design.
 */
async function openSecondTab() {
  vi.resetModules();
  return await import('@/stores/analysis-job-store');
}

describe('analysis-job-store cross-tab mirror', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null, completedAt: null });
    localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it('rehydrates when the analysis-job key changes in another tab', () => {
    const spy = vi
      .spyOn(useAnalysisJobStore.persist, 'rehydrate')
      .mockResolvedValue();

    window.dispatchEvent(
      new StorageEvent('storage', { key: ANALYSIS_JOB_STORAGE_KEY }),
    );

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('ignores storage events for unrelated keys', () => {
    const spy = vi
      .spyOn(useAnalysisJobStore.persist, 'rehydrate')
      .mockResolvedValue();

    window.dispatchEvent(new StorageEvent('storage', { key: 'geolens-auth' }));

    expect(spy).not.toHaveBeenCalled();
  });

  it('picks up a run another tab started, without a reload', async () => {
    expect(useAnalysisJobStore.getState().job).toBeNull();

    seedStorage({ job, completedAt: null });
    window.dispatchEvent(
      new StorageEvent('storage', { key: ANALYSIS_JOB_STORAGE_KEY }),
    );

    // The Analysis panel subscribes to `!!s.job`, so this is what disables its
    // Create button in the tab that did not start the run.
    await waitFor(() => expect(useAnalysisJobStore.getState().job).toEqual(job));
  });

  it('propagates a clear, so ending a run in one tab re-enables the others', async () => {
    useAnalysisJobStore.setState({ job });

    seedStorage({ job: null, completedAt: null });
    window.dispatchEvent(
      new StorageEvent('storage', { key: ANALYSIS_JOB_STORAGE_KEY }),
    );

    await waitFor(() => expect(useAnalysisJobStore.getState().job).toBeNull());
  });
});

describe('analysis-job-store completion claim', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null, completedAt: null });
    localStorage.clear();
  });

  it('is granted to the first caller and recorded in storage', () => {
    expect(useAnalysisJobStore.getState().claimCompletion('job-1')).toBe(true);
    expect(storedState().completedAt).toMatchObject({ jobId: 'job-1' });
  });

  it('stays granted to the tab that won it', () => {
    useAnalysisJobStore.getState().claimCompletion('job-1');

    // StrictMode invokes the watcher effect twice; the tab that already
    // reported must not silence itself on the second pass.
    expect(useAnalysisJobStore.getState().claimCompletion('job-1')).toBe(true);
  });

  it('grants each job its own claim', () => {
    expect(useAnalysisJobStore.getState().claimCompletion('job-1')).toBe(true);
    expect(useAnalysisJobStore.getState().claimCompletion('job-2')).toBe(true);
  });

  it('grants exactly one of two tabs the same completion', async () => {
    const tabB = await openSecondTab();

    const wonInA = useAnalysisJobStore.getState().claimCompletion('job-1');
    const wonInB = tabB.useAnalysisJobStore.getState().claimCompletion('job-1');

    expect(wonInA).toBe(true);
    expect(wonInB).toBe(false);
    // ...and the loser did not overwrite the winner's record on its way out.
    expect(storedState().completedAt).toMatchObject({ jobId: 'job-1' });
  });

  it('holds across a reload, so a returning tab does not report again', async () => {
    useAnalysisJobStore.getState().claimCompletion('job-1');

    // A reload is a new module instance reading the same storage — which is
    // exactly what the second tab above is, so it doubles as the durability
    // case the timing-based alternative could not give.
    const reloaded = await openSecondTab();

    expect(reloaded.useAnalysisJobStore.getState().claimCompletion('job-1')).toBe(
      false,
    );
  });

  it('reports no claim rather than throwing when storage is unreadable', () => {
    localStorage.setItem(ANALYSIS_JOB_STORAGE_KEY, 'not json');

    // A duplicate toast is a far better failure than a broken watcher effect.
    expect(() => useAnalysisJobStore.getState().claimCompletion('job-1')).not.toThrow();
  });
});
