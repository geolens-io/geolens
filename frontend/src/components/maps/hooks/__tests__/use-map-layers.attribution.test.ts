/**
 * fix(#1472 review): dataset attribution on the dataset-detail preview map.
 *
 * DatasetPage renders DatasetMap, which has no explicit <AttributionControl> to
 * hand `customAttribution` to — it gets MapLibre's auto-created default. So the
 * preview credits through the source-level `attribution` property, which that
 * default control reads off whichever sources are live. Without this the hero
 * preview rendered attributed data with no credit, which is the same omission
 * #1472 set out to fix on the viewer.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useMapLayers } from '../use-map-layers';
import type { Map as MaplibreMap } from 'maplibre-gl';

vi.mock('@/lib/env', () => ({
  getEnvConfig: () => ({ TILE_BASE_URL: 'http://tiles.test' }),
}));

vi.mock('maplibre-gl', () => ({ default: {} }));

const SWISSTOPO = '© swisstopo — swissALTI3D';

function fakeMap() {
  return {
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getSource: vi.fn(() => undefined),
  } as unknown as MaplibreMap;
}

function addedSource(map: MaplibreMap, id: string): Record<string, unknown> | undefined {
  const call = (map.addSource as ReturnType<typeof vi.fn>).mock.calls.find(
    (c) => c[0] === id,
  );
  return call?.[1] as Record<string, unknown> | undefined;
}

function runVector(attribution?: string | null) {
  const mapRef = { current: null };
  const { result } = renderHook(() =>
    useMapLayers({
      tableName: 'alti3d',
      geometryType: 'MultiPolygon',
      tileToken: null,
      mapRef,
      attribution,
    }),
  );
  const map = fakeMap();
  result.current.addVectorLayers(map);
  return map;
}

function runRaster(attribution?: string | null) {
  const mapRef = { current: null };
  const { result } = renderHook(() =>
    useMapLayers({
      tableName: null,
      geometryType: null,
      rasterTileUrl: '/raster-tiles/ds-1/tiles/{z}/{x}/{y}.png',
      tileToken: null,
      mapRef,
      attribution,
    }),
  );
  const map = fakeMap();
  result.current.addRasterLayers(map);
  return map;
}

describe('useMapLayers dataset attribution (#1472)', () => {
  it('puts the credit on the vector source', () => {
    const spec = addedSource(runVector(SWISSTOPO), 'vector-tile-source');
    expect(spec?.attribution).toBe(SWISSTOPO);
  });

  it('puts the credit on the raster source', () => {
    const spec = addedSource(runRaster(SWISSTOPO), 'raster-tile-source');
    expect(spec?.attribution).toBe(SWISSTOPO);
  });

  it('omits the property entirely when the dataset requires no credit', () => {
    expect(addedSource(runVector(null), 'vector-tile-source')).not.toHaveProperty(
      'attribution',
    );
    expect(addedSource(runRaster(null), 'raster-tile-source')).not.toHaveProperty(
      'attribution',
    );
  });

  it('omits the property when the caller passes nothing at all', () => {
    // Every other caller of this shared hook does exactly this, so the absent
    // case has to leave their source specs byte-identical to before.
    expect(addedSource(runVector(), 'vector-tile-source')).not.toHaveProperty(
      'attribution',
    );
  });
});
