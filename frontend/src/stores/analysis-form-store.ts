import { create } from 'zustand';
import { useAuthStore } from '@/stores/auth-store';
import type { AnalysisOperation } from '@/types/api';

/** fix(#757): the AnalysisPanel form fields that must survive the panel's
 *  conditional unmount — a rail-panel switch, Escape, or crossing the 800px
 *  breakpoint all unmount it, and losing a hand-drawn clip mask or a typed
 *  dataset name to a stray click is data loss. One snapshot PER MAP
 *  (fix(#793 review): a single shared slot let map B's save overwrite map
 *  A's draft within the same session). Deliberately NOT persisted: a reload
 *  starts the form fresh; the tracked JOB is what survives reloads, via
 *  analysis-job-store. */
export interface SavedAnalysisForm {
  layerId: string;
  operation: AnalysisOperation;
  distance: string;
  distanceUnit: 'm' | 'km' | 'ft' | 'mi';
  mask: GeoJSON.Polygon | null;
  maskLayerId: string;
  byField: string;
  outputTitle: string;
  /** fix(#793 review): true when the form was edited AFTER the last run
   *  started — the run (and its completion) no longer owns these fields, so
   *  a late-landing job must stay ambient and a finishing run must not clear
   *  the title, even one that coincidentally reuses the same name. */
  runDisowned?: boolean;
}

interface AnalysisFormState {
  forms: Record<string, SavedAnalysisForm>;
  save: (mapId: string, form: SavedAnalysisForm) => void;
  /** fix(#793 review): called by AnalysisJobWatcher when a tracked job completes
   *  (or its status becomes unreadable) — the remembered title must not
   *  survive into the next mount, or Create re-enables with the finished
   *  run's name and one click creates an identically-named dataset. Guarded
   *  by the form's runDisowned flag, not title equality: a draft edited
   *  after the run started is the user's, even when it deliberately reuses
   *  the same permitted, non-unique name. */
  clearTitleForMap: (mapId: string | null) => void;
}

export const useAnalysisFormStore = create<AnalysisFormState>()((set) => ({
  forms: {},
  save: (mapId, form) =>
    set((s) => ({ forms: { ...s.forms, [mapId]: form } })),
  clearTitleForMap: (mapId) =>
    set((s) => {
      if (mapId == null) return s;
      const form = s.forms[mapId];
      if (!form || form.runDisowned) return s;
      return { forms: { ...s.forms, [mapId]: { ...form, outputTitle: '' } } };
    }),
}));

// fix(#793 review): the slot is per-tab module state — without this it survives a
// logout and restores one account's dataset name, parameters, and drawn mask
// to whoever signs in next on the same map. Keyed on user identity, not
// token: routine refresh-token rotation must not wipe an in-progress form.
useAuthStore.subscribe((s, prev) => {
  if (s.user?.id !== prev.user?.id) {
    useAnalysisFormStore.setState({ forms: {} });
  }
});
