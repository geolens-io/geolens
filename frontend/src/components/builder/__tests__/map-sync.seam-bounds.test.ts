import { describe, expect, it, vi } from 'vitest';
import { syncLayersToMap, toSyncInput } from '../map-sync';
import type { TileToken } from '@/api/tiles';
import type { MapLayerResponse } from '@/types/api';

vi.mock('@/lib/tile-utils', () => ({
  getMvtSourceLayerName: (table: string) => `data.${table}`,
  buildSignedTileUrl: vi.fn(() => '/tiles/mock/{z}/{x}/{y}.pbf'),
  buildClusterTileUrl: vi.fn(() => '/tiles/clusters/mock/{z}/{x}/{y}.pbf'),
}));

// fix(#1112): the producer (maps/_router_helpers.py) now sends
// `dataset_extent_bbox` in the RFC 7946 §5.2 spec form, so a seam-crossing
// dataset arrives as `west > east` instead of the world-wide span it used to be
// flattened to. Two properties have to hold together, and neither is provable
// from the backend test alone:
//
//   1. `toSyncInput` passes the crossing pair through UNCONVERTED, so the
//      builder's #903 fit guards still see the seam they were written for.
//   2. It is nonetheless spanned by the time it reaches a MapLibre source
//      `bounds`, where an inverted pair matches no tile and the layer renders
//      blank. `normalizeRasterBounds` (layer-adapters/shared.ts) owns that
//      conversion; this pins that the source path actually goes through it.
//
// Fiji: [178.5, -20, -178.5, -15] crossing, [-180, -20, 180, -15] spanned.
const FIJI_SPEC_BBOX = [178.5, -20, -178.5, -15];
const FIJI_SPAN_BBOX = [-180, -20, 180, -15];

function makeMockMap() {
  const sources = new Map<string, { type: string }>();
  const layerIds = new Set<string>();

  return {
    getSource: vi.fn((id: string) => sources.get(id) ?? null),
    addSource: vi.fn((id: string, spec: { type: string }) => {
      sources.set(id, { ...spec });
    }),
    removeSource: vi.fn((id: string) => { sources.delete(id); }),
    addLayer: vi.fn((layer: { id: string }) => { layerIds.add(layer.id); }),
    getLayer: vi.fn((id: string) => layerIds.has(id) ? { id } : null),
    removeLayer: vi.fn((id: string) => { layerIds.delete(id); }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    getPaintProperty: vi.fn(),
    getFilter: vi.fn().mockReturnValue(null),
    setFilter: vi.fn(),
    setLayerZoomRange: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getStyle: vi.fn(() => ({ layers: Array.from(layerIds).map((id) => ({ id })) })),
    moveLayer: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

function makeSeamLayer(bbox: number[] | null): MapLayerResponse {
  return {
    id: 'seam-1',
    dataset_id: 'ds-seam',
    dataset_table_name: 'fiji_reefs',
    dataset_geometry_type: 'MultiPoint',
    dataset_extent_bbox: bbox,
    opacity: 1,
    visible: true,
    paint: { 'circle-color': '#2255aa' },
    layout: {},
    filter: null,
  } as unknown as MapLayerResponse;
}

/** Sync one layer and return the vector source spec it created. The source id
 *  is deliberately not asserted — the SF-04 dedupe keys it by dataset table, and
 *  this test is about the bounds value, not the naming scheme. */
function syncAndReadSourceSpec(bbox: number[] | null): Record<string, unknown> {
  const map = makeMockMap();
  syncLayersToMap(
    map,
    [toSyncInput(makeSeamLayer(bbox))],
    new Map<string, TileToken>([['ds-seam', VECTOR_TOKEN]]),
    undefined,
    { current: new Set() },
    { current: '' },
  );
  return (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<string, unknown>;
}

const VECTOR_TOKEN: TileToken = {
  kind: 'vector',
  sig: 'mock',
  exp: 9999999999,
  scope: 'test',
  expires_in: 3600,
};

describe('antimeridian bounds through the builder sync path (#1112)', () => {
  it('carries the crossing bbox through toSyncInput unconverted', () => {
    expect(toSyncInput(makeSeamLayer(FIJI_SPEC_BBOX)).bounds).toEqual(FIJI_SPEC_BBOX);
  });

  it('spans the crossing bbox by the time it reaches the vector source', () => {
    const spec = syncAndReadSourceSpec(FIJI_SPEC_BBOX);
    expect(spec.type).toBe('vector');
    expect(spec.bounds).toEqual(FIJI_SPAN_BBOX);
  });

  it('leaves a non-crossing bbox alone on the same path', () => {
    const nyc = [-74.5, 40.5, -73.5, 41.5];
    expect(syncAndReadSourceSpec(nyc).bounds).toEqual(nyc);
  });

  it('omits bounds entirely when the dataset has no extent', () => {
    expect(syncAndReadSourceSpec(null)).not.toHaveProperty('bounds');
  });
});
