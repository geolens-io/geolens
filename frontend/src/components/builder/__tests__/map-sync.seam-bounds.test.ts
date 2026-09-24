// Both input adapters pass an antimeridian-crossing extent through unconverted,
// in the RFC 7946 form (west > east); the source description spans it.
import { describe, expect, it } from 'vitest';
import { toSyncInput } from '../map-sync';
import { toViewerSyncInput } from '@/components/viewer/ViewerMap';
import { savedLayer, toSharedLayer } from '@/test/fixtures/saved-layers';

// Fiji crosses the antimeridian.
const FIJI_SPEC_BBOX = [178.5, -20, -178.5, -15];

describe('antimeridian bounds through the sync input', () => {
  const layer = savedLayer({ dataset_extent_bbox: FIJI_SPEC_BBOX });

  it('carries the crossing bbox through toSyncInput unconverted', () => {
    expect(toSyncInput(layer).bounds).toEqual(FIJI_SPEC_BBOX);
  });

  it('carries the crossing bbox through toViewerSyncInput unconverted', () => {
    expect(toViewerSyncInput(toSharedLayer(layer), layer.id, new Set()).bounds).toEqual(FIJI_SPEC_BBOX);
  });
});
