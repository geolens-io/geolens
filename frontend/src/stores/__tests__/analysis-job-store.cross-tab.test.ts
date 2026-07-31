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

  it('is granted to the first caller and recorded in storage', async () => {
    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(true);
    expect(storedState().completedAt).toMatchObject({ jobId: 'job-1' });
  });

  it('stays granted to the tab that won it', async () => {
    await useAnalysisJobStore.getState().claimCompletion('job-1');

    // StrictMode invokes the watcher effect twice; the tab that already
    // reported must not silence itself on the second pass.
    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(true);
  });

  it('grants each job its own claim', async () => {
    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(true);
    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-2'),
    ).resolves.toBe(true);
  });

  it('grants exactly one of two tabs the same completion', async () => {
    const tabB = await openSecondTab();

    const wonInA = await useAnalysisJobStore.getState().claimCompletion('job-1');
    const wonInB = await tabB.useAnalysisJobStore
      .getState()
      .claimCompletion('job-1');

    expect(wonInA).toBe(true);
    expect(wonInB).toBe(false);
    // ...and the loser did not overwrite the winner's record on its way out.
    expect(storedState().completedAt).toMatchObject({ jobId: 'job-1' });
  });

  it('holds across a reload, so a returning tab does not report again', async () => {
    await useAnalysisJobStore.getState().claimCompletion('job-1');

    // A reload is a new module instance reading the same storage — which is
    // exactly what the second tab above is, so it doubles as the durability
    // case the timing-based alternative could not give.
    const reloaded = await openSecondTab();

    await expect(
      reloaded.useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(false);
  });

  it('reports no claim rather than throwing when storage is unreadable', async () => {
    localStorage.setItem(ANALYSIS_JOB_STORAGE_KEY, 'not json');

    // A duplicate toast is a far better failure than a broken watcher effect.
    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(true);
  });
});

describe('analysis-job-store claim atomicity', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null, completedAt: null });
    localStorage.clear();
  });
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'locks');
    vi.restoreAllMocks();
  });

  // fix(#1008 codex P2): the read/write/read sequence is not atomic by itself.
  // `A reads empty, B reads empty, A writes, A reads back A, B writes, B reads
  // back B` leaves both tabs holding a winning claim, and localStorage
  // serializing individual operations does not prevent it. Web Locks is what
  // makes the sequence mutually exclusive across documents.
  //
  // The race itself cannot be staged here — two tabs are two processes, and a
  // single JS realm runs `attempt()` to completion before the other caller
  // starts. So pin the mechanism: the claim must go through the lock.
  it('runs the claim inside a Web Lock', async () => {
    const request = vi.fn(
      <T,>(_name: string, callback: () => T | Promise<T>) =>
        Promise.resolve(callback()),
    );
    Object.defineProperty(navigator, 'locks', {
      value: { request },
      configurable: true,
    });

    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(true);

    expect(request).toHaveBeenCalledWith(
      'geolens-analysis-completion',
      expect.any(Function),
    );
  });

  it('still claims when Web Locks is unavailable', async () => {
    expect('locks' in navigator).toBe(false);

    // Older browsers and non-DOM environments lose the tie-breaking guarantee,
    // not the feature — a duplicate toast on a genuine tie is the behaviour
    // that shipped before any of this.
    await expect(
      useAnalysisJobStore.getState().claimCompletion('job-1'),
    ).resolves.toBe(true);
  });
});

describe('analysis-job-store guarded clear', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null, completedAt: null });
    localStorage.clear();
  });

  it('clears the job it was asked about', () => {
    useAnalysisJobStore.setState({ job });

    useAnalysisJobStore.getState().clearJobIfCurrent(job.jobId);

    expect(useAnalysisJobStore.getState().job).toBeNull();
  });

  // fix(#1008 codex P1): the clear propagates now, so an unconditional one is
  // no longer this tab's own business. A backgrounded tab whose timers were
  // throttled can process a terminal response long after another tab started
  // the NEXT run.
  it('leaves a newer run alone', () => {
    const newer = { jobId: 'job-2', title: 'Next run', mapId: 'map-1' };
    useAnalysisJobStore.setState({ job: newer });

    useAnalysisJobStore.getState().clearJobIfCurrent('job-1');

    expect(useAnalysisJobStore.getState().job).toEqual(newer);
    expect(storedState().job).toEqual(newer);
  });

  it('clears this tab even when storage tracks nothing', () => {
    // The mirror already carried another tab's clear through storage; this
    // tab's in-memory copy still has to go.
    useAnalysisJobStore.setState({ job });
    localStorage.setItem(
      ANALYSIS_JOB_STORAGE_KEY,
      JSON.stringify({ state: { job: null, completedAt: null }, version: 1 }),
    );

    useAnalysisJobStore.getState().clearJobIfCurrent(job.jobId);

    expect(useAnalysisJobStore.getState().job).toBeNull();
  });
});

// fix(#1008 codex P1): every write to this store persists the WHOLE snapshot,
// so a write meaning to change one field silently republishes this tab's copy
// of the other. Harmless in one tab; corrupting across several.
describe('analysis-job-store write merging', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null, completedAt: null });
    localStorage.clear();
  });

  it('does not resurrect a job another tab has already replaced', async () => {
    const newer = { jobId: 'job-2', title: 'Next run', mapId: 'map-1' };
    // This tab was throttled and still holds job-1...
    useAnalysisJobStore.setState({ job });
    // ...while another tab finished it, started job-2, and persisted that.
    seedStorage({ job: newer, completedAt: null });

    await useAnalysisJobStore.getState().claimCompletion(job.jobId);

    // Claiming must carry storage's job through rather than republish job-1.
    expect(storedState().job).toEqual(newer);

    // Which is what leaves the guarded clear able to see job-2 and stand down;
    // before the merge it read back its own job-1 and cleared it.
    useAnalysisJobStore.getState().clearJobIfCurrent(job.jobId);
    expect(storedState().job).toEqual(newer);
  });

  it('starting a run keeps a claim another tab wrote', () => {
    seedStorage({
      job: null,
      completedAt: { jobId: 'job-0', tabId: 'some-other-tab', at: 1 },
    });

    useAnalysisJobStore.getState().setJob(job);

    expect(storedState().job).toEqual(job);
    // Dropping the claim would re-arm a completion another tab already
    // reported, so the next tab to look would toast it a second time.
    expect(storedState().completedAt).toMatchObject({ jobId: 'job-0' });
  });
});
