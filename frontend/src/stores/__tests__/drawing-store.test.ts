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
    useDrawingStore.getState().setSelectedFeature(feature);

    expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
  });

  it('clearSelectedFeature clears feature and resets dirty flag', () => {
    useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
    useDrawingStore.getState().setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} });
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
    useDrawingStore.getState().setSelectedFeature({ gid: 5, tdId: 'td-2', properties: { a: 1 } });
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

    it('setSelectedFeature accepts a write while the session epoch has not moved', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      const feature = { gid: 1, tdId: 'td-1', properties: { name: 'A' } };
      useDrawingStore.getState().setSelectedFeature(feature);

      expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
    });

    it('setSelectedFeature refuses and clears when there is no active target', () => {
      // fix(#1761 review P1): the second, independent guard — refuses even
      // when nothing has adopted a target yet, so a caller that reaches
      // setSelectedFeature without ever calling setDrawing cannot attach a
      // feature to nothing.
      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} });

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

    // fix(#1761 review P1): `ownerId === currentUserId()` was the original
    // (broken) check. After a logout both sides read null and the write was
    // wrongly accepted. bumpSessionEpoch() is what lib/auth-cache-reset.ts
    // calls on every real identity change (see that file, and its tests for
    // the end-to-end version of this race through the actual choke point);
    // called directly here to pin the store's own refusal in isolation.
    it('setSelectedFeature refuses and clears once the session epoch has moved, regardless of identity', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      // The session epoch moves (what the auth choke point does on any
      // identity change) WITHOUT a clearDrawing() call — the shape a race
      // between that subscription and an in-flight write could leave.
      useDrawingStore.getState().bumpSessionEpoch();

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: { name: 'A' } });

      const state = useDrawingStore.getState();
      expect(state.selectedFeature).toBeNull();
      expect(state.targetDatasetId).toBeNull();
      expect(state.isDrawing).toBe(false);
      expect(state.ownerId).toBeNull();
    });

    it('setSelectedFeature refuses a write for a target adopted anonymously once the session epoch has moved', () => {
      useAuthStore.setState({ user: null });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      useDrawingStore.getState().bumpSessionEpoch();

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} });

      expect(useDrawingStore.getState().selectedFeature).toBeNull();
    });
  });
});
