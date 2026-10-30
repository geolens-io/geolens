import { useMapSelectionStore } from '@/stores/map-selection-store';

describe('map selection store', () => {
  beforeEach(() => useMapSelectionStore.getState().clear());

  it('gives each selection a new nonce, the same feature again included', () => {
    const { select } = useMapSelectionStore.getState();
    select('l1', 5);
    const first = useMapSelectionStore.getState().selection;
    select('l1', 5);
    const second = useMapSelectionStore.getState().selection;

    expect(second).toMatchObject({ layerId: 'l1', featureId: 5 });
    expect(second!.nonce).toBeGreaterThan(first!.nonce);
  });

  it('clears the selection', () => {
    useMapSelectionStore.getState().select('l1', 5);
    useMapSelectionStore.getState().clear();

    expect(useMapSelectionStore.getState().selection).toBeNull();
  });
});
