import { create } from 'zustand';

/**
 * fix(#726): whether a builder draw mode currently owns the map pointer.
 *
 * The analysis clip mask runs its own TerraDraw instance over the live map
 * (AnalysisPanel). A vertex click places its vertex and then falls through to
 * BuilderMap's click handler, which resolves the feature under the cursor and
 * opens its popup — so drawing a five-point mask left five popups behind, the
 * last one sitting on top of the result.
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
