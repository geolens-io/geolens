import { useDrawingStore } from '@/stores/drawing-store';

const initialState = useDrawingStore.getState();

describe('useDrawingStore', () => {
  beforeEach(() => {
    useDrawingStore.setState(initialState, true);
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
});
