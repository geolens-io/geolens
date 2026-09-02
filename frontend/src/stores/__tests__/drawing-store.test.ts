import { useDrawingStore } from '@/stores/drawing-store';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

const initialState = useDrawingStore.getState();
const initialAuthState = useAuthStore.getState();

describe('useDrawingStore', () => {
  beforeEach(() => {
    useDrawingStore.setState(initialState, true);
    useAuthStore.setState(initialAuthState, true);
  });

  it('has correct initial state', () => {
    const state = useDrawingStore.getState();
    expect(state.isDrawing).toBe(false);
    expect(state.activeMode).toBeNull();
    expect(state.targetDatasetId).toBeNull();
    expect(state.targetTableName).toBeNull();
    expect(state.targetGeometryType).toBeNull();
    expect(state.selectedFeature).toBeNull();
    expect(state.isEditDirty).toBe(false);
  });

  it('setDrawing enables drawing with target info', () => {
    useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

    const state = useDrawingStore.getState();
    expect(state.isDrawing).toBe(true);
    expect(state.activeMode).toBe('select');
    expect(state.targetDatasetId).toBe('ds-1');
    expect(state.targetTableName).toBe('my_table');
    expect(state.targetGeometryType).toBe('Polygon');
  });

  it('setMode updates activeMode', () => {
    useDrawingStore.getState().setMode('polygon');

    expect(useDrawingStore.getState().activeMode).toBe('polygon');
  });

  it('setMode accepts null to clear mode', () => {
    useDrawingStore.getState().setMode('point');
    useDrawingStore.getState().setMode(null);

    expect(useDrawingStore.getState().activeMode).toBeNull();
  });

  it('setSelectedFeature stores a feature for the active target', () => {
    useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
    const feature = { gid: 42, tdId: 'td-1', properties: { name: 'Park' } };
    useDrawingStore.getState().setSelectedFeature(feature, useDrawingStore.getState().sessionEpoch);

    expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
  });

  it('clearSelectedFeature clears feature and resets dirty flag', () => {
    useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
    useDrawingStore
      .getState()
      .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} }, useDrawingStore.getState().sessionEpoch);
    useDrawingStore.getState().setEditDirty(true);
    useDrawingStore.getState().clearSelectedFeature();

    expect(useDrawingStore.getState().selectedFeature).toBeNull();
    expect(useDrawingStore.getState().isEditDirty).toBe(false);
  });

  it('setEditDirty tracks dirty state', () => {
    expect(useDrawingStore.getState().isEditDirty).toBe(false);

    useDrawingStore.getState().setEditDirty(true);
    expect(useDrawingStore.getState().isEditDirty).toBe(true);

    useDrawingStore.getState().setEditDirty(false);
    expect(useDrawingStore.getState().isEditDirty).toBe(false);
  });

  it('clearDrawing resets all state', () => {
    // Set everything
    useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Point');
    useDrawingStore.getState().setMode('point');
    useDrawingStore
      .getState()
      .setSelectedFeature({ gid: 5, tdId: 'td-2', properties: { a: 1 } }, useDrawingStore.getState().sessionEpoch);
    useDrawingStore.getState().setEditDirty(true);

    useDrawingStore.getState().clearDrawing();

    const state = useDrawingStore.getState();
    expect(state.isDrawing).toBe(false);
    expect(state.activeMode).toBeNull();
    expect(state.targetDatasetId).toBeNull();
    expect(state.targetTableName).toBeNull();
    expect(state.targetGeometryType).toBeNull();
    expect(state.selectedFeature).toBeNull();
    expect(state.isEditDirty).toBe(false);
  });

  // fix(#1713): the ownership check at the adoption point — the structural
  // half that holds even if the identity-change teardown in
  // lib/auth-cache-reset.ts is skipped or races an in-flight write. See
  // lib/__tests__/auth-cache-reset.test.ts for the end-to-end teardown
  // tests (including the late-write races these unit tests exercise
  // directly, via bumpSessionEpoch rather than the auth choke point).
  describe('identity ownership', () => {
    it('setDrawing records the signed-in identity as the owner', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      expect(useDrawingStore.getState().ownerId).toBe('user-a');
    });

    it('setDrawing records a null owner for an anonymous session', () => {
      useAuthStore.setState({ user: null });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      expect(useDrawingStore.getState().ownerId).toBeNull();
    });

    it('setSelectedFeature accepts a write whose captured epoch still matches the live one', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const epoch = useDrawingStore.getState().sessionEpoch;

      const feature = { gid: 1, tdId: 'td-1', properties: { name: 'A' } };
      useDrawingStore.getState().setSelectedFeature(feature, epoch);

      expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
    });

    it('setSelectedFeature refuses and clears when there is no active target', () => {
      // fix(#1761 review P1): the second, independent guard — refuses even
      // when nothing has adopted a target yet, so a caller that reaches
      // setSelectedFeature without ever calling setDrawing cannot attach a
      // feature to nothing. Nothing is active to preserve here, so a full
      // clear and a no-op read the same.
      const epoch = useDrawingStore.getState().sessionEpoch;

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} }, epoch);

      expect(useDrawingStore.getState().selectedFeature).toBeNull();
    });

    it('bumpSessionEpoch advances the counter without touching other state', () => {
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const before = useDrawingStore.getState().sessionEpoch;

      useDrawingStore.getState().bumpSessionEpoch();

      const state = useDrawingStore.getState();
      expect(state.sessionEpoch).toBe(before + 1);
      // A plain bump is not a clear: it is the auth choke point's job to
      // also call clearDrawing() (see lib/auth-cache-reset.ts).
      expect(state.targetDatasetId).toBe('ds-1');
    });

    // fix(#1761 review round 2 P1): the race round 1's design missed.
    // Round 1 stored the adopting epoch ON THE TARGET and compared it to
    // the live counter, which broke once a SECOND identity adopted its own
    // fresh target: that adoption re-stamped the stored epoch to the (now
    // current) live value, so a stale write from the FIRST identity's
    // still-pending mutation compared the live epoch to itself and was
    // wrongly accepted. The fix passes the epoch through the CALL instead —
    // captured by the caller before its own await (see
    // handleEditAttributeSubmit / selectFeatureFromMap in
    // components/dataset/hooks/use-feature-editing.ts) — so a second
    // identity's fresh target can never launder a first identity's stale
    // write. This pins that directly: capture an epoch, bump it (an
    // identity change), adopt a brand new target (a second identity's own
    // legitimate session), then submit the ORIGINAL stale epoch — refused,
    // and the second identity's active session is left completely alone.
    it('refuses a write captured before the session epoch moved, even after a new target is adopted', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const staleEpoch = useDrawingStore.getState().sessionEpoch;

      // Identity changes (the auth choke point bumps the epoch)...
      useDrawingStore.getState().bumpSessionEpoch();
      useAuthStore.setState({ user: { id: 'user-b' } as UserResponse });
      // ...and user B adopts their OWN new target and selection. Its epoch
      // is current by construction, which is exactly what let the stale
      // write through in round 1.
      useDrawingStore.getState().setDrawing('ds-2', 'other_table', 'Point');
      useDrawingStore
        .getState()
        .setSelectedFeature(
          { gid: 9, tdId: 'td-9', properties: { name: 'B' } },
          useDrawingStore.getState().sessionEpoch,
        );
      const beforeStaleWrite = useDrawingStore.getState();

      // User A's stale continuation lands, carrying the OLD epoch.
      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: { name: 'A' } }, staleEpoch);

      // Refused, and user B's active session is untouched by it.
      expect(useDrawingStore.getState()).toEqual(beforeStaleWrite);
    });

    it('setSelectedFeature refuses a stale write without disturbing the currently active target', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const staleEpoch = useDrawingStore.getState().sessionEpoch;

      // The session epoch moves (what the auth choke point does on any
      // identity change) WITHOUT a clearDrawing() call — the shape a race
      // between that subscription and an in-flight write could leave.
      useDrawingStore.getState().bumpSessionEpoch();

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: { name: 'A' } }, staleEpoch);

      const state = useDrawingStore.getState();
      // Refused: the write did not land.
      expect(state.selectedFeature).toBeNull();
      // NOT cleared: a stale write must not be able to blow away whatever
      // session is currently active either, only fail to attach itself.
      expect(state.targetDatasetId).toBe('ds-1');
      expect(state.isDrawing).toBe(true);
      expect(state.ownerId).toBe('user-a');
    });

    it('setSelectedFeature refuses a stale write from a target that was adopted anonymously', () => {
      useAuthStore.setState({ user: null });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const staleEpoch = useDrawingStore.getState().sessionEpoch;

      useDrawingStore.getState().bumpSessionEpoch();
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} }, staleEpoch);

      expect(useDrawingStore.getState().selectedFeature).toBeNull();
    });
  });
});
