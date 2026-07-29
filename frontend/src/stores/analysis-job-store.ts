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

interface AnalysisJobState {
  job: TrackedAnalysisJob | null;
  setJob: (job: TrackedAnalysisJob | null) => void;
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
  persist((set) => ({ job: null, setJob: (job) => set({ job }) }), {
    name: 'geolens-analysis-job',
    version: 1,
  }),
);

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
