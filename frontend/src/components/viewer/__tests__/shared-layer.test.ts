import type { MapLayerResponse } from '@/types/api';
import { toSharedLayer } from '../shared-layer';

describe('toSharedLayer', () => {
  it('keeps the dataset tile allowlist, which decides where a dashboard offers picks', () => {
    const layer = { id: 'l1', dataset_id: 'd1', dataset_tile_columns: ['kind'] } as MapLayerResponse;
    expect(toSharedLayer(layer).dataset_tile_columns).toEqual(['kind']);
    expect(toSharedLayer({ ...layer, dataset_tile_columns: undefined }).dataset_tile_columns).toBeNull();
  });
});
