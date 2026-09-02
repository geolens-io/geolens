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
   * fix(#1713): the identity that adopted the current target, for
   * bookkeeping. NOT the write gate below (see `sessionEpoch`/`targetEpoch`)
   * — fix(#1761 review P1) found that comparing this to the live identity
   * directly breaks down once both sides are anonymous (see
   * `setSelectedFeature`).
   */
  ownerId: string | null;
  /**
   * fix(#1761 review P1): a monotonic counter, bumped ONLY by
   * `bumpSessionEpoch()`, which only the identity-change choke point
   * (lib/auth-cache-reset.ts) calls. `targetEpoch` below snapshots this at
   * adoption time. Comparing two counters instead of two identities means
   * an identity change is never mistaken for "no change" merely because the
   * old and new identity happen to both be anonymous (`null === null`) —
   * the counter has no such degenerate case: it only ever moves forward on
   * a real change.
   */
  sessionEpoch: number;
  /** The `sessionEpoch` that was live when the current target was adopted;
   *  `null` when nothing is adopted. */
  targetEpoch: number | null;
  setDrawing: (datasetId: string, tableName: string, geometryType: string) => void;
  setMode: (mode: string | null) => void;
  clearDrawing: () => void;
  setSelectedFeature: (sf: SelectedFeature) => void;
  clearSelectedFeature: () => void;
  setEditDirty: (dirty: boolean) => void;
  /**
   * fix(#1761 review P1): invalidates every target/selection adopted before
   * this call. Called ONLY from lib/auth-cache-reset.ts's identity-change
   * subscription — never from component code, and never folded into
   * `clearDrawing()`, which ordinary component lifecycle (DatasetMap.tsx)
   * also calls for reasons that have nothing to do with identity. If a
   * lifecycle clear also bumped this counter, "the epoch changed" would
   * stop meaning "the identity changed".
   */
  bumpSessionEpoch: () => void;
}

function currentUserId(): string | null {
  return useAuthStore.getState().user?.id ?? null;
}

/**
 * fix(#1713): shared by the initial state and clearDrawing, so a reset can
 * never drift from what "nothing adopted" looks like.
 *
 * fix(#1761 review P1): deliberately excludes `sessionEpoch` — see its
 * doc comment for why the counter must never be reset by an ordinary clear.
 */
const CLEARED_STATE = {
  isDrawing: false,
  activeMode: null,
  targetDatasetId: null,
  targetTableName: null,
  targetGeometryType: null,
  selectedFeature: null,
  isEditDirty: false,
  ownerId: null,
  targetEpoch: null,
} as const;

export const useDrawingStore = create<DrawingState>()((set, get) => ({
  ...CLEARED_STATE,
  sessionEpoch: 0,
  // fix(#1713): the adoption point for a drawing target. Stamps the
  // signed-in identity and the live session epoch at the moment the target
  // is set, and — because this always replaces selectedFeature/isEditDirty
  // rather than merging with whatever was there — a call under a new
  // identity self-heals the store even if the identity-change teardown
  // (lib/auth-cache-reset.ts) somehow hasn't run yet.
  setDrawing: (datasetId, tableName, geometryType) =>
    set((state) => ({
      isDrawing: true,
      activeMode: 'select',
      targetDatasetId: datasetId,
      targetTableName: tableName,
      targetGeometryType: geometryType,
      selectedFeature: null,
      isEditDirty: false,
      ownerId: currentUserId(),
      targetEpoch: state.sessionEpoch,
    })),
  setMode: (mode) => set({ activeMode: mode }),
  clearDrawing: () => set({ ...CLEARED_STATE }),
  // fix(#1713): the other adoption point, and the one an in-flight edit can
  // reach asynchronously — handleEditAttributeSubmit reads `selectedFeature`
  // before an update mutation, then calls this again after the mutation
  // resolves.
  //
  // fix(#1761 review P1): refusing on `ownerId !== currentUserId()` alone
  // broke down right after a logout: clearDrawing() sets ownerId to null,
  // and an anonymous currentUserId() is ALSO null, so the comparison saw
  // two nulls as equal and accepted a write that belonged to the signed-out
  // user, re-populating selectedFeature for whoever views the still-mounted
  // dataset route next. `targetEpoch !== sessionEpoch` has no such
  // degenerate case: the epoch only advances via bumpSessionEpoch(), called
  // once per real identity change, so a stale write's captured epoch can
  // never coincide with the live one after such a change, whatever the
  // next identity turns out to be (anonymous or not). Refusing whenever
  // there is no active target closes the same hole even if some future
  // caller adds a path that skips setDrawing.
  setSelectedFeature: (sf) => {
    const state = get();
    if (state.targetDatasetId === null || state.targetEpoch !== state.sessionEpoch) {
      set({ ...CLEARED_STATE });
      return;
    }
    set({ selectedFeature: sf, ownerId: currentUserId() });
  },
  clearSelectedFeature: () => set({ selectedFeature: null, isEditDirty: false }),
  setEditDirty: (dirty) => set({ isEditDirty: dirty }),
  bumpSessionEpoch: () => set((state) => ({ sessionEpoch: state.sessionEpoch + 1 })),
}));
