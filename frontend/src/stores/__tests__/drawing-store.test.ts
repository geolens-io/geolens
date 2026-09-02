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

  it('setSelectedFeature stores a feature', () => {
    const feature = { gid: 42, tdId: 'td-1', properties: { name: 'Park' } };
    useDrawingStore.getState().setSelectedFeature(feature);

    expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
  });

  it('clearSelectedFeature clears feature and resets dirty flag', () => {
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
  // lib/__tests__/auth-cache-reset.test.ts for the teardown half.
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

    it('setSelectedFeature accepts a write from the identity that owns the target', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      const feature = { gid: 1, tdId: 'td-1', properties: { name: 'A' } };
      useDrawingStore.getState().setSelectedFeature(feature);

      expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
    });

    it('setSelectedFeature refuses and clears when the identity changed underneath it', () => {
      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      // Identity changes WITHOUT going through clearDrawing — the shape a
      // race with the identity-change teardown subscription would leave, or
      // (per #1713) an update mutation's .then resolving after the
      // subscription cleared the store: this is the case that resolution
      // must not resurrect.
      useAuthStore.setState({ user: { id: 'user-b' } as UserResponse });

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: { name: 'A' } });

      const state = useDrawingStore.getState();
      expect(state.selectedFeature).toBeNull();
      expect(state.targetDatasetId).toBeNull();
      expect(state.isDrawing).toBe(false);
      expect(state.ownerId).toBeNull();
    });

    it('setSelectedFeature refuses a write for a target adopted anonymously once someone signs in', () => {
      useAuthStore.setState({ user: null });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');

      useAuthStore.setState({ user: { id: 'user-a' } as UserResponse });

      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: {} });

      expect(useDrawingStore.getState().selectedFeature).toBeNull();
    });
  });
});
