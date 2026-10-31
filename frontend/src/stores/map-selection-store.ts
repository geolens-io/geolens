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

// Never reset, so a selection after `clear()` is still new to a subscriber
// that handled an earlier one.
let lastNonce = 0;

export const useMapSelectionStore = create<MapSelectionState>()((set) => ({
  selection: null,
  select: (layerId, featureId) => set({ selection: { layerId, featureId, nonce: ++lastNonce } }),
  clear: () => set({ selection: null }),
}));
