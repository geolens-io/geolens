import { create } from 'zustand';
import { useAuthStore } from '@/stores/auth-store';
import type { AnalysisOperation } from '@/types/api';

/** The AnalysisPanel form fields that must survive the panel's conditional
 *  unmount (rail-panel switch, Escape, crossing the 800px breakpoint); losing a
 *  hand-drawn clip mask or a typed dataset name is data loss. One snapshot PER
 *  MAP, so one map's save cannot overwrite another's draft. Deliberately NOT
 *  persisted: a reload starts the form fresh; the tracked JOB survives reloads
 *  via analysis-job-store. */
export interface SavedAnalysisForm {
  layerId: string;
  operation: AnalysisOperation;
  distance: string;
  distanceUnit: 'm' | 'km' | 'ft' | 'mi';
  mask: GeoJSON.Polygon | null;
  maskLayerId: string;
  byField: string;
  /** The spatial-join inputs persist for the same reason maskLayerId does;
   *  otherwise a restored spatial-join form comes back unrunnable with its
   *  required layer cleared. */
  joinLayerId: string;
  joinField: string;
  outputTitle: string;
  /** True when the form was edited AFTER the last run started: the run no
   *  longer owns these fields, so a late-landing job must stay ambient and a
   *  finishing run must not clear the title, even one that reuses the name. */
  runDisowned?: boolean;
}

interface AnalysisFormState {
  forms: Record<string, SavedAnalysisForm>;
  save: (mapId: string, form: SavedAnalysisForm) => void;
  /** Called by AnalysisJobWatcher when a tracked job completes (or its status
   *  becomes unreadable), so the finished run's name does not re-enable Create
   *  and produce an identically-named dataset. Guarded by the form's
   *  runDisowned flag, not title equality: a draft edited after the run started
   *  is the user's, even when it reuses the same name. */
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

// The slot is per-tab module state, so without this it survives a logout and
// restores one account's dataset name, parameters and drawn mask to whoever
// signs in next on the same map. Keyed on user identity, not token: routine
// refresh-token rotation must not wipe an in-progress form.
useAuthStore.subscribe((s, prev) => {
  if (s.user?.id !== prev.user?.id) {
    useAnalysisFormStore.setState({ forms: {} });
  }
});
