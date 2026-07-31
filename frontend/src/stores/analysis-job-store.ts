import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { useAuthStore } from '@/stores/auth-store';

export interface TrackedAnalysisJob {
  jobId: string;
  /** Output dataset name, so a notification arriving minutes later has context. */
  title: string;
  /** Map the job was started from; enables the "Add to map" action. */
  mapId: string | null;
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
  at: number;
}

interface AnalysisJobState {
  job: TrackedAnalysisJob | null;
  completedAt: AnalysisCompletionClaim | null;
  setJob: (job: TrackedAnalysisJob | null) => void;
  /**
   * Try to become the one tab that reports this job's completion.
   *
   * Returns true exactly once across every open tab, and keeps returning true
   * for the tab that won (so a StrictMode double-invoke does not lose its own
   * claim). See the storage listener below for why a mirror alone is not
   * enough.
   */
  claimCompletion: (jobId: string) => boolean;
}

export const ANALYSIS_JOB_STORAGE_KEY = 'geolens-analysis-job';

/** Identifies this tab for the lifetime of the document. */
const TAB_ID =
  globalThis.crypto?.randomUUID?.() ?? `tab-${Math.random().toString(36).slice(2)}`;

/**
 * Read the claim straight out of storage rather than off in-memory state.
 *
 * The mirror below is event-driven and therefore always a beat behind; the
 * stored value is the only view that is current at the instant of the claim.
 */
function readPersistedClaim(): AnalysisCompletionClaim | null {
  try {
    const raw = localStorage.getItem(ANALYSIS_JOB_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as {
      state?: { completedAt?: AnalysisCompletionClaim | null };
    };
    return parsed.state?.completedAt ?? null;
  } catch {
    // Storage disabled, quota-exceeded, or a payload from a future version.
    // Losing the arbiter means duplicate toasts, not a broken app.
    return null;
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
    (set) => ({
      job: null,
      completedAt: null,
      setJob: (job) => set({ job }),
      claimCompletion: (jobId) => {
        const existing = readPersistedClaim();
        if (existing?.jobId === jobId) {
          // Someone already reported this one. Ours only if we were the one.
          return existing.tabId === TAB_ID;
        }
        set({ completedAt: { jobId, tabId: TAB_ID, at: Date.now() } });
        // Last writer wins, and the read-back is the arbiter: if two tabs got
        // past the check above simultaneously, only one of them reads its own
        // id back. Checking first AND re-reading is what makes it exactly one
        // — the check alone loses to a genuine race, and the read-back alone
        // lets a tab that writes and reads before the other tab writes come
        // out true as well.
        const settled = readPersistedClaim();
        return settled?.jobId === jobId && settled.tabId === TAB_ID;
      },
    }),
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
    useAnalysisJobStore.getState().setJob(null);
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
