import { create } from 'zustand';
import { useAuthStore } from '@/stores/auth-store';

interface SelectedFeature {
  gid: number;
  tdId: string;
  properties: Record<string, unknown>;
  /** The table_id the feature was read with, sent with every write to it. */
  tableId?: string | null;
}

interface DrawingState {
  isDrawing: boolean;
  activeMode: string | null;
  targetDatasetId: string | null;
  targetTableName: string | null;
  targetGeometryType: string | null;
  selectedFeature: SelectedFeature | null;
  isEditDirty: boolean;
  /** Any unsaved work on the mounted dataset map (a dirty or undoable
   *  selection, a sketch, a pending new geometry, an open attribute
   *  editor), as that map computes it, for the page's unsaved-changes guard. */
  hasUnsavedMapWork: boolean;
  /**
   * The identity that adopted the current target, for bookkeeping. NOT the write
   * gate (see `sessionEpoch`): comparing it to the live identity breaks down
   * once both sides are anonymous.
   */
  ownerId: string | null;
  /**
   * A monotonic counter, bumped ONLY by `bumpSessionEpoch()`, which only the
   * identity-change choke point (lib/auth-cache-reset.ts) calls.
   *
   * The store cannot gate stale writes itself: once a SECOND identity adopts its
   * own target, `setDrawing` would re-stamp any stored epoch to the live value,
   * and a pending mutation from the FIRST identity would compare the live epoch
   * to itself and be wrongly accepted. Only the original caller knows when its
   * request started, so the epoch travels through the call, captured before the
   * `await` (see `setSelectedFeature`).
   */
  sessionEpoch: number;
  setDrawing: (datasetId: string, tableName: string, geometryType: string) => void;
  setMode: (mode: string | null) => void;
  clearDrawing: () => void;
  /**
   * `epoch` is mandatory: `sessionEpoch` as read by the CALLER before its own
   * `await`, never re-read at call time. A call whose captured epoch no longer
   * matches the live one is refused, whatever the current target belongs to.
   */
  setSelectedFeature: (sf: SelectedFeature, epoch: number) => void;
  clearSelectedFeature: () => void;
  setEditDirty: (dirty: boolean) => void;
  setHasUnsavedMapWork: (unsaved: boolean) => void;
  /**
   * Invalidates every target/selection adopted before this call. Called ONLY
   * from lib/auth-cache-reset.ts's identity-change subscription, never from
   * component code and never from `clearDrawing()`, which ordinary component
   * lifecycle also calls: a lifecycle bump would stop "the epoch changed" from
   * meaning "the identity changed".
   */
  bumpSessionEpoch: () => void;
}

function currentUserId(): string | null {
  return useAuthStore.getState().user?.id ?? null;
}

/**
 * Shared by the initial state and clearDrawing, so a reset cannot drift from
 * what "nothing adopted" looks like. Excludes `sessionEpoch`, which an ordinary
 * clear must never reset.
 */
const CLEARED_STATE = {
  isDrawing: false,
  activeMode: null,
  targetDatasetId: null,
  targetTableName: null,
  targetGeometryType: null,
  selectedFeature: null,
  isEditDirty: false,
  hasUnsavedMapWork: false,
  ownerId: null,
} as const;

export const useDrawingStore = create<DrawingState>()((set, get) => ({
  ...CLEARED_STATE,
  sessionEpoch: 0,
  // The adoption point for a drawing target. Stamps the signed-in identity and
  // replaces selectedFeature/isEditDirty rather than merging, so a call under a
  // new identity self-heals even if the identity-change teardown has not run.
  // Its only caller is synchronous, so there is no pre-`await` epoch to capture.
  setDrawing: (datasetId, tableName, geometryType) =>
    set({
      isDrawing: true,
      activeMode: 'select',
      targetDatasetId: datasetId,
      targetTableName: tableName,
      targetGeometryType: geometryType,
      selectedFeature: null,
      isEditDirty: false,
      hasUnsavedMapWork: false,
      ownerId: currentUserId(),
    }),
  setMode: (mode) => set({ activeMode: mode }),
  clearDrawing: () => set({ ...CLEARED_STATE }),
  // The other adoption point, reachable by an in-flight edit:
  // handleEditAttributeSubmit and selectFeatureFromMap
  // (components/dataset/hooks/use-feature-editing.ts) read a feature, await a
  // request, then call this with the result. The caller passes the epoch it
  // captured before its `await` (see `sessionEpoch`). Refusing whenever there is
  // no active target covers a path that skips setDrawing.
  setSelectedFeature: (sf, epoch) => {
    const state = get();
    if (state.targetDatasetId === null) {
      // Nothing adopted: already the cleared shape.
      set({ ...CLEARED_STATE });
      return;
    }
    if (epoch !== state.sessionEpoch) {
      // A stale write for a target that may now belong to a LATER identity's
      // freshly-adopted session. Refuse by doing nothing so the active target is
      // not clobbered, and drop the stale payload.
      return;
    }
    set({ selectedFeature: sf, ownerId: currentUserId() });
  },
  clearSelectedFeature: () => set({ selectedFeature: null, isEditDirty: false }),
  setEditDirty: (dirty) => set({ isEditDirty: dirty }),
  setHasUnsavedMapWork: (unsaved) => set({ hasUnsavedMapWork: unsaved }),
  bumpSessionEpoch: () => set((state) => ({ sessionEpoch: state.sessionEpoch + 1 })),
}));
