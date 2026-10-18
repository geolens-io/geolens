import { create } from 'zustand';

/**
 * Whether a builder draw mode currently owns the map pointer.
 *
 * The analysis clip mask runs its own TerraDraw instance over the live map. A
 * vertex click places its vertex and then falls through to BuilderMap's click
 * handler, which would open a popup for the feature under the cursor.
 *
 * Deliberately separate from `drawing-store`, which is dataset-edit-specific:
 * its `setDrawing` requires a target dataset, table, and geometry type that an
 * analysis mask has none of.
 */
interface MapDrawState {
  drawActive: boolean;
  setDrawActive: (active: boolean) => void;
}

export const useMapDrawStore = create<MapDrawState>()((set) => ({
  drawActive: false,
  setDrawActive: (drawActive) => set({ drawActive }),
}));
