import { create } from 'zustand';
import { useAuthStore } from '@/stores/auth-store';

interface SelectedFeature {
  gid: number;
  tdId: string;
  properties: Record<string, unknown>;
}

interface DrawingState {
  isDrawing: boolean;
  activeMode: string | null;
  targetDatasetId: string | null;
  targetTableName: string | null;
  targetGeometryType: string | null;
  selectedFeature: SelectedFeature | null;
  isEditDirty: boolean;
  /**
   * fix(#1713): the identity that adopted the current target/selection,
   * captured at `setDrawing`/`setSelectedFeature` time. Not surfaced to
   * consumers — it exists so those two setters can refuse a write that
   * belongs to a different identity than the one that opened the target
   * (see `setSelectedFeature` below).
   */
  ownerId: string | null;
  setDrawing: (datasetId: string, tableName: string, geometryType: string) => void;
  setMode: (mode: string | null) => void;
  clearDrawing: () => void;
  setSelectedFeature: (sf: SelectedFeature) => void;
  clearSelectedFeature: () => void;
  setEditDirty: (dirty: boolean) => void;
}

function currentUserId(): string | null {
  return useAuthStore.getState().user?.id ?? null;
}

/** fix(#1713): shared by the initial state and clearDrawing, so a reset can
 *  never drift from what "nothing adopted" looks like. */
const CLEARED_STATE = {
  isDrawing: false,
  activeMode: null,
  targetDatasetId: null,
  targetTableName: null,
  targetGeometryType: null,
  selectedFeature: null,
  isEditDirty: false,
  ownerId: null,
} as const;

export const useDrawingStore = create<DrawingState>()((set, get) => ({
  ...CLEARED_STATE,
  // fix(#1713): the adoption point for a drawing target. Stamps the
  // signed-in identity at the moment the target is set, and — because this
  // always replaces selectedFeature/isEditDirty rather than merging with
  // whatever was there — a call under a new identity self-heals the store
  // even if the identity-change teardown (lib/auth-cache-reset.ts) somehow
  // hasn't run yet.
  setDrawing: (datasetId, tableName, geometryType) =>
    set({
      isDrawing: true,
      activeMode: 'select',
      targetDatasetId: datasetId,
      targetTableName: tableName,
      targetGeometryType: geometryType,
      selectedFeature: null,
      isEditDirty: false,
      ownerId: currentUserId(),
    }),
  setMode: (mode) => set({ activeMode: mode }),
  clearDrawing: () => set({ ...CLEARED_STATE }),
  // fix(#1713): the other adoption point, and the one an in-flight edit can
  // reach asynchronously — handleEditAttributeSubmit reads `selectedFeature`
  // before an update mutation, then calls this again after the mutation
  // resolves. If sign-out/sign-in happens in between, that resolution can
  // land after the identity-change teardown already cleared the store, and
  // it would otherwise re-populate `selectedFeature` with the previous
  // identity's row for whoever is signed in now. Refuse whenever the
  // adopting identity does not match who owns the current target (including
  // the just-cleared case, where the target's owner is null and a signed-in
  // identity is not), clearing rather than partially applying the stale
  // write.
  setSelectedFeature: (sf) => {
    const uid = currentUserId();
    if (get().ownerId !== uid) {
      set({ ...CLEARED_STATE });
      return;
    }
    set({ selectedFeature: sf, ownerId: uid });
  },
  clearSelectedFeature: () => set({ selectedFeature: null, isEditDirty: false }),
  setEditDirty: (dirty) => set({ isEditDirty: dirty }),
}));
