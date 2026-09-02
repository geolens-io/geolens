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
   * bookkeeping. NOT the write gate below (see `sessionEpoch`) — fix(#1761
   * review P1) found that comparing this to the live identity directly
   * breaks down once both sides are anonymous.
   */
  ownerId: string | null;
  /**
   * fix(#1761 review P1): a monotonic counter, bumped ONLY by
   * `bumpSessionEpoch()`, which only the identity-change choke point
   * (lib/auth-cache-reset.ts) calls.
   *
   * fix(#1761 review round 2 P1): round 1 stored the adopting epoch ON THE
   * STORE (`targetEpoch`) and compared it to the live counter inside
   * `setSelectedFeature`. That still had a hole: once a SECOND identity
   * adopts its own target after the identity change, its `setDrawing` call
   * re-stamps that stored epoch to the (now current) live value, so a
   * write from the FIRST identity's still-pending mutation — which reads
   * `selectedFeature` before its `await` and writes again after — compares
   * the live epoch to itself and is wrongly accepted, carrying the first
   * identity's captured properties into the second identity's target.
   * There is no way to fix this from inside the store: the store cannot
   * tell "the live epoch matches because nothing changed" apart from "the
   * live epoch matches because something else changed twice". Only the
   * ORIGINAL caller knows which one is true, because it alone knows when
   * its own request started. So the epoch this check needs is not
   * something the store can keep — it has to travel through the call,
   * captured by the caller before the `await` (see `setSelectedFeature`).
   */
  sessionEpoch: number;
  setDrawing: (datasetId: string, tableName: string, geometryType: string) => void;
  setMode: (mode: string | null) => void;
  clearDrawing: () => void;
  /**
   * fix(#1761 review round 2 P1): `epoch` is mandatory and must be
   * `useDrawingStore.getState().sessionEpoch` read by the CALLER before
   * its own `await` — never re-read at call time, which is exactly what
   * broke in round 1 (see `sessionEpoch`'s doc comment). A call whose
   * captured epoch no longer matches the live one is refused, whatever the
   * store's current target belongs to.
   */
  setSelectedFeature: (sf: SelectedFeature, epoch: number) => void;
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
} as const;

export const useDrawingStore = create<DrawingState>()((set, get) => ({
  ...CLEARED_STATE,
  sessionEpoch: 0,
  // fix(#1713): the adoption point for a drawing target. Stamps the
  // signed-in identity at the moment the target is set, and — because this
  // always replaces selectedFeature/isEditDirty rather than merging with
  // whatever was there — a call under a new identity self-heals the store
  // even if the identity-change teardown (lib/auth-cache-reset.ts) somehow
  // hasn't run yet. Its only caller (DatasetMap.tsx's draw button) is fully
  // synchronous, so unlike setSelectedFeature there is no "before the
  // await" moment to capture an epoch from — nothing here can go stale.
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
  // reach asynchronously — handleEditAttributeSubmit and selectFeatureFromMap
  // (components/dataset/hooks/use-feature-editing.ts) both read/derive a
  // feature, await a request, then call this with the result.
  //
  // fix(#1761 review P1, then round 2): round 1 refused on
  // `ownerId !== currentUserId()`, which broke down right after a logout
  // (both read null). Storing an adopted-at epoch on the target and
  // comparing it to the live counter fixed that, but not the case where a
  // SECOND identity adopts its OWN new target before the first identity's
  // stale write lands: the stored epoch gets re-stamped to the (now
  // current) live value by that second adoption, so the stale write's
  // check passes by comparing the live epoch to itself. The caller is the
  // only one who can tell its own request apart from a coincidentally
  // fresh-looking target, so the epoch travels through the call instead —
  // captured by the caller before its `await`, passed in here, and
  // compared against the live counter. Refusing whenever there is no
  // active target closes the same hole even if some future caller adds a
  // path that skips setDrawing.
  setSelectedFeature: (sf, epoch) => {
    const state = get();
    if (state.targetDatasetId === null) {
      // Nothing adopted: already the cleared shape, but explicit for
      // anyone reaching this with a target that was never set up.
      set({ ...CLEARED_STATE });
      return;
    }
    if (epoch !== state.sessionEpoch) {
      // fix(#1761 review round 2 P1): a stale write for a target that may
      // now belong to a DIFFERENT, later identity than the one that issued
      // it. That target could be a second identity's own legitimate,
      // freshly-adopted session — clearing it would let this stale write
      // do collateral damage instead of just failing to apply. Refuse by
      // doing nothing: leave whatever is currently active exactly as it
      // is, and drop the stale payload.
      return;
    }
    set({ selectedFeature: sf, ownerId: currentUserId() });
  },
  clearSelectedFeature: () => set({ selectedFeature: null, isEditDirty: false }),
  setEditDirty: (dirty) => set({ isEditDirty: dirty }),
  bumpSessionEpoch: () => set((state) => ({ sessionEpoch: state.sessionEpoch + 1 })),
}));
