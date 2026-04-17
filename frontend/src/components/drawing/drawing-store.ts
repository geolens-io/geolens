import { create } from 'zustand';

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
  setDrawing: (datasetId: string, tableName: string, geometryType: string) => void;
  setMode: (mode: string | null) => void;
  clearDrawing: () => void;
  setSelectedFeature: (sf: SelectedFeature) => void;
  clearSelectedFeature: () => void;
  setEditDirty: (dirty: boolean) => void;
}

export const useDrawingStore = create<DrawingState>()((set) => ({
  isDrawing: false,
  activeMode: null,
  targetDatasetId: null,
  targetTableName: null,
  targetGeometryType: null,
  selectedFeature: null,
  isEditDirty: false,
  setDrawing: (datasetId, tableName, geometryType) =>
    set({
      isDrawing: true,
      activeMode: 'select',
      targetDatasetId: datasetId,
      targetTableName: tableName,
      targetGeometryType: geometryType,
      selectedFeature: null,
      isEditDirty: false,
    }),
  setMode: (mode) => set({ activeMode: mode }),
  clearDrawing: () =>
    set({
      isDrawing: false,
      activeMode: null,
      targetDatasetId: null,
      targetTableName: null,
      targetGeometryType: null,
      selectedFeature: null,
      isEditDirty: false,
    }),
  setSelectedFeature: (sf) => set({ selectedFeature: sf }),
  clearSelectedFeature: () => set({ selectedFeature: null, isEditDirty: false }),
  setEditDirty: (dirty) => set({ isEditDirty: dirty }),
}));
