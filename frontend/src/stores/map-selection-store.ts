import { create } from 'zustand';

/**
 * The feature last picked on a map (the Builder's or a viewer's), for the table beside it.
 * Each selection gets a new nonce, so picking the same feature again is still
 * a change to subscribers.
 */
interface MapSelection {
  layerId: string;
  featureId: number;
  nonce: number;
}

interface MapSelectionState {
  selection: MapSelection | null;
  select: (layerId: string, featureId: number) => void;
  clear: () => void;
}

export const useMapSelectionStore = create<MapSelectionState>()((set, get) => ({
  selection: null,
  select: (layerId, featureId) =>
    set({ selection: { layerId, featureId, nonce: (get().selection?.nonce ?? 0) + 1 } }),
  clear: () => set({ selection: null }),
}));
