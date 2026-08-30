import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { useAuthStore } from '@/stores/auth-store';

export interface TrackedAnalysisJob {
  jobId: string;
  /** Output dataset name, so a notification arriving minutes later has context. */
  title: string;
  /** Map the job was started from; enables the "Add to map" action. */
  mapId: string | null;
  /** fix(#1008 codex P2): who started it. The identity-change clear
   *  propagates now, so a dormant tab processing a stale auth event would
   *  otherwise delete the account that replaced it — including a run that is
   *  still going server-side. Stamped by `setJob`, not by callers. */
  userId?: string | null;
}

/**
 * feat(#1008): the written claim on a job's completion.
 *
 * Only the most recent one is kept — the store tracks a single job at a time,
 * so an older claim can never be consulted again.
 */
export interface AnalysisCompletionClaim {
  jobId: string;
  /** Whichever tab wrote it. Two tabs can observe the same terminal poll in
   *  the same millisecond, so the timestamp alone cannot identify a claimant. */
  tabId: string;
  /** fix(#1008 codex P2): how the run ended. A tab that never observed the
   *  terminal poll itself still has document-local cleanup to do once the
   *  claim reaches it, and complete and failed call for different cleanup.
   *  fix(#1677): 'cancelled' joined the set — cancel is a user-reachable
   *  terminal status for every job type now, analysis included. */
  status: 'complete' | 'failed' | 'cancelled';
  at: number;
}

/** The fields that reach storage; the actions below are not serializable. */
interface PersistedAnalysisJobState {
  job: TrackedAnalysisJob | null;
  completedAt: AnalysisCompletionClaim | null;
}

interface AnalysisJobState extends PersistedAnalysisJobState {
  setJob: (job: TrackedAnalysisJob | null) => Promise<void>;
  /**
   * Drop the tracked job, but only if it belongs to ``userId``.
   *
   * fix(#1008 codex P2): the identity-change clear used to be this tab's own
   * business. Now it propagates, so a delayed handler must not reach past the
   * account it is cleaning up after.
   */
  clearJobForUser: (userId: string | null) => Promise<void>;
  /**
   * Try to become the one tab that reports this job's completion.
   *
   * Resolves true exactly once across every open tab, and keeps resolving true
   * for the tab that won (so a StrictMode double-invoke does not lose its own
   * claim). See the storage listener below for why a mirror alone is not
   * enough.
   */
  claimCompletion: (
    jobId: string,
    status: 'complete' | 'failed' | 'cancelled',
  ) => Promise<boolean>;
  /**
   * Stop tracking ``jobId``, unless a newer run already owns the slot.
   *
   * fix(#1008 codex P1): the clear propagates now, so an unconditional one is
   * no longer this tab's business alone. A backgrounded tab whose timers were
   * throttled can process a terminal response long after another tab started
   * the NEXT analysis; clearing then erases the newer job everywhere and
   * re-enables Create while the server job is still running.
   */
  clearJobIfCurrent: (jobId: string) => Promise<void>;
}

export const ANALYSIS_JOB_STORAGE_KEY = 'geolens-analysis-job';

/** Identifies this tab for the lifetime of the document. */
const TAB_ID =
  globalThis.crypto?.randomUUID?.() ?? `tab-${Math.random().toString(36).slice(2)}`;

/** Web Locks name serializing every read-modify-write on this record. */
const ANALYSIS_JOB_LOCK = 'geolens-analysis-job-write';

/**
 * Read persisted state straight out of storage rather than off in-memory state.
 *
 * The mirror below is event-driven and therefore always a beat behind; the
 * stored value is the only view that is current at the instant of a claim or a
 * clear. Reaching for `localStorage` directly matches what the persist
 * middleware uses by default — if this store ever names a different storage,
 * this has to follow it.
 */
function readPersisted(): {
  job?: TrackedAnalysisJob | null;
  completedAt?: AnalysisCompletionClaim | null;
} {
  try {
    const raw = localStorage.getItem(ANALYSIS_JOB_STORAGE_KEY);
    if (!raw) return {};
    return (
      (JSON.parse(raw) as { state?: ReturnType<typeof readPersisted> }).state ?? {}
    );
  } catch {
    // Storage disabled, quota-exceeded, or a payload from a future version.
    // Losing this view means a duplicate toast, not a broken app.
    return {};
  }
}

/**
 * Choose between the persisted value and the in-memory one, preferring the
 * in-memory OBJECT whenever the two describe the same thing.
 *
 * `readPersisted` parses fresh objects out of JSON every call, so returning
 * them unconditionally would hand React a new identity on every write and
 * re-run every effect subscribed to this store — including the watcher's, for
 * a value that did not change. `undefined` means storage had nothing to say.
 */
function pick<T extends object>(
  persisted: T | null | undefined,
  current: T | null,
  same: (a: T, b: T) => boolean,
): T | null {
  if (persisted === undefined) return current;
  if (persisted && current && same(persisted, current)) return current;
  return persisted;
}

/**
 * Run a read-modify-write on the shared record under mutual exclusion.
 *
 * Web Locks is the only primitive that serializes a SEQUENCE of storage
 * operations across same-origin documents; localStorage serializes each
 * operation on its own and nothing more.
 *
 * fix(#1008 codex P2): never rejects. The watcher awaits these, and a
 * rejection there would leave a finished job neither reported nor cleared,
 * with Create disabled until a reload. `fallback` is what a broken storage
 * layer should degrade to — for a claim that is `true`, because a duplicate
 * notification beats never telling the user their dataset is ready.
 */
async function withLock<T>(run: () => T, fallback: T): Promise<T> {
  try {
    const locks = globalThis.navigator?.locks;
    // No Web Locks (older browser, or a non-DOM environment). The sequence is
    // still right in every staggered case, which is the common one; the
    // residual loss is a duplicate toast on a genuine tie, i.e. the behaviour
    // that shipped before any of this.
    if (!locks) return run();
    return await locks.request(ANALYSIS_JOB_LOCK, run);
  } catch {
    return fallback;
  }
}

/**
 * The one in-flight materialize job being tracked for notification.
 *
 * Persisted because the whole point is surviving what a long job outlives:
 * closing the Analysis panel, navigating off the builder, or reloading the
 * tab. The job itself always completes server-side — this only carries the
 * id needed to tell the user about it. AnalysisJobWatcher (mounted in
 * RootLayout) owns polling and clears this on any terminal status.
 *
 * Singular by design: the API allows one active analysis job per user.
 */
export const useAnalysisJobStore = create<AnalysisJobState>()(
  persist(
    (set, get) => {
      /**
       * fix(#1008 codex P1): every `set` here persists the WHOLE snapshot, so
       * a write that means to change one field silently republishes this tab's
       * copy of the other. Harmless in one tab, corrupting across several: a
       * throttled tab still holding `job1` would restore it over another tab's
       * newer `job2` just by claiming a completion.
       *
       * Takes the snapshot the caller already read, so a decision and the
       * write it justifies can never straddle two different reads.
       *
       * Falls back to in-memory when storage has nothing to offer (first write
       * of the session, or an unreadable read) — the alternative is nulling a
       * field on the strength of a failed read.
       */
      const mergeWith = (
        persisted: ReturnType<typeof readPersisted>,
        patch: Partial<PersistedAnalysisJobState>,
      ) => {
        const current = get();
        return {
          job: pick(persisted.job, current.job, (a, b) => a.jobId === b.jobId),
          completedAt: pick(
            persisted.completedAt,
            current.completedAt,
            (a, b) => a.jobId === b.jobId && a.tabId === b.tabId,
          ),
          ...patch,
        };
      };
      return {
        job: null,
        completedAt: null,
        setJob: (job) => {
          // fix(#1008 codex P2): read the identity NOW, not inside the lock
          // callback. That callback can wait behind another tab's write, and
          // an account switch in the meantime would stamp this run as
          // belonging to whoever arrived — which the scoped clear below would
          // then dutifully preserve for them.
          //
          // Stamped here rather than by callers: every caller would have to
          // remember, and forgetting reads as "belongs to nobody".
          const owned = job
            ? { ...job, userId: useAuthStore.getState().user?.id ?? null }
            : null;
          // fix(#1008 codex P1): a job START has to serialize against a clear
          // too, or a clear that read "no newer job" moments earlier overwrites
          // this one with null.
          return withLock(() => {
            set(mergeWith(readPersisted(), { job: owned }));
          }, undefined);
        },
        clearJobForUser: (userId) =>
          withLock(() => {
            const persisted = readPersisted();
            const tracked = persisted.job;
            // A job with no owner predates the stamp, so its provenance is
            // unknown — clearing is the safe reading, since the alternative
            // leaves the previous account's run tracked under a new one.
            if (tracked && tracked.userId !== undefined && tracked.userId !== userId) {
              return;
            }
            set(mergeWith(persisted, { job: null }));
          }, undefined),
        claimCompletion: (jobId, status) =>
          // fix(#1008 codex P2): the read/write/read below is NOT atomic on its
          // own, and the tempting argument that it is does not survive contact
          // with an interleaving. localStorage serializes individual
          // operations, not a sequence of them, so `A reads empty, B reads
          // empty, A writes, A reads back A, B writes, B reads back B` leaves
          // both tabs holding what looks like a winning claim — exactly the
          // simultaneous completion this exists to dedup.
          withLock(() => {
            const persisted = readPersisted();
            const existing = persisted.completedAt;
            if (existing?.jobId === jobId) {
              // Already reported. Ours only if we were the one who did it.
              return existing.tabId === TAB_ID;
            }
            // fix(#1008 codex P2): a claim naming a DIFFERENT run, while the
            // tracked run is not ours either, means this tab is late — a
            // throttled tab resuming after the run it is holding was cleared
            // and a later one already completed. Overwriting would re-report a
            // finished run and re-arm the newer one for a second claim.
            if (existing && persisted.job?.jobId !== jobId) return false;
            set(
              mergeWith(persisted, {
                completedAt: { jobId, tabId: TAB_ID, status, at: Date.now() },
              }),
            );
            const settled = readPersisted().completedAt;
            return settled?.jobId === jobId && settled.tabId === TAB_ID;
          }, true),
        clearJobIfCurrent: (jobId) =>
          withLock(() => {
            const persisted = readPersisted();
            // Only stand down when storage names a DIFFERENT run: a null there
            // means nothing is tracked and this tab's copy still has to go.
            if (persisted.job && persisted.job.jobId !== jobId) return;
            set(mergeWith(persisted, { job: null }));
          }, undefined),
      };
    },
    {
      name: ANALYSIS_JOB_STORAGE_KEY,
      // Deliberately NOT bumped for `completedAt`: the default shallow merge
      // leaves the field at its initial null when an older payload omits it,
      // and a bump would discard a job that was in flight across the deploy.
      version: 1,
    },
  ),
);

/**
 * feat(#1008): cross-tab mirror.
 *
 * Two builders open on the same map each poll the same materialize job, and
 * neither knows about the other: the second tab's Create button stays enabled
 * and earns a 429 rendered as generic rate limiting. The `storage` event fires
 * only in the tabs that did NOT write, so rehydrating here is what lets tab B
 * learn that tab A started a run — `analysisJobRunning` in the Analysis panel
 * is a live subscription, so the button disables without a reload. It also
 * propagates the identity-change clear.
 *
 * The mirror on its own dedups nothing: three tabs mirroring the same job all
 * still poll it to completion, and each raises its own toast (`toastId` is
 * per-job, and each tab has its own toaster). That is what `claimCompletion`
 * above is for.
 *
 * No write-back loop here, which is worth stating because it is the obvious
 * worry: zustand's `hydrate()` applies the storage payload through the store's
 * RAW setter and only calls `setItem` when a migration ran. A rehydrate is
 * therefore silent, so it cannot bounce a storage event back at the tab that
 * started it.
 */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== ANALYSIS_JOB_STORAGE_KEY) return;
    void useAnalysisJobStore.persist.rehydrate();
  });
}

// The tracked job is persisted browser state — without this it survives a
// logout and the next account on the same browser inherits the previous
// user's run (its title included), whose status endpoint then 401/403s
// forever until the sweep. Keyed on user identity, not token, mirroring
// analysis-form-store's guard: routine refresh-token rotation must not drop
// a job mid-run.
useAuthStore.subscribe((s, prev) => {
  if (s.user?.id !== prev.user?.id) {
    void useAnalysisJobStore.getState().clearJobForUser(prev.user?.id ?? null);
  }
});

/**
 * Add-to-map handler registered by MapBuilderPage while it is mounted.
 *
 * A module ref rather than store state: it is a live callback (not
 * serializable, and re-rendering the watcher when it changes is pointless).
 * The watcher offers "Add to map" only when a builder for the job's own map
 * is mounted, and falls back to navigating to the dataset otherwise.
 */
export const analysisAddToMap: {
  current: ((datasetId: string) => void) | null;
  mapId: string | null;
} = { current: null, mapId: null };

/**
 * fix(#833): dataset ids already added to a map through an analysis
 * "Add to map" affordance. A completed run raises TWO affordances (the
 * watcher's toast action and the Analysis panel's button); each used to keep
 * its own single-use flag, so clicking both added the layer twice. Shared
 * here so either click retires both. A store (not a module Set) so the panel
 * button re-renders to its "Added to map" state when the toast action does
 * the add. Session-scoped and keyed on dataset id on purpose: a NEW run's
 * completion re-enables both affordances, and adding the same dataset again
 * via other surfaces stays legitimate.
 */
interface AnalysisAddedState {
  /** Confirmed on the map — the add mutation succeeded (any surface). */
  addedDatasetIds: string[];
  /**
   * fix(#833 codex P2): claimed by an analysis affordance whose add mutation
   * is still in flight. The claim happens BEFORE the mutation starts (so a
   * double-click can't add twice); success confirms it, failure clears it so
   * the affordances re-arm. Split from addedDatasetIds so a FAILED add from a
   * non-analysis surface (catalog/chat/drag never claim a pending entry) can
   * never un-retire a confirmed one.
   */
  pendingAddIds: string[];
  markPending: (datasetId: string) => void;
  confirmAdded: (datasetId: string) => void;
  clearPending: (datasetId: string) => void;
}

export const useAnalysisAddedStore = create<AnalysisAddedState>()((set) => ({
  addedDatasetIds: [],
  pendingAddIds: [],
  markPending: (datasetId) =>
    set((s) =>
      s.pendingAddIds.includes(datasetId)
        ? s
        : { pendingAddIds: [...s.pendingAddIds, datasetId] },
    ),
  confirmAdded: (datasetId) =>
    set((s) => ({
      pendingAddIds: s.pendingAddIds.filter((id) => id !== datasetId),
      addedDatasetIds: s.addedDatasetIds.includes(datasetId)
        ? s.addedDatasetIds
        : [...s.addedDatasetIds, datasetId],
    })),
  clearPending: (datasetId) =>
    set((s) =>
      s.pendingAddIds.includes(datasetId)
        ? { pendingAddIds: s.pendingAddIds.filter((id) => id !== datasetId) }
        : s,
    ),
}));
