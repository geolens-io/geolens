/**
 * feat(#1472): the viewer's per-dataset attribution control.
 *
 * Two levels, because the bug this feature fixes can reappear at either:
 * the pure collection helper (what credits, in what order, deduped), and the
 * wiring that gets them into MapLibre's AttributionControl — including the
 * `key` that forces a remount, without which react-maplibre's `useControl`
 * builds the control once and a changed `customAttribution` never lands.
 */
import type { ReactNode } from 'react';
import { render, screen } from '@/test/test-utils';
import { describe, it, expect, vi } from 'vitest';
import type { SharedLayerResponse } from '@/types/api';
import { attributionControlKey, collectLayerAttributions } from '../layer-identity';

/* ── Mock @vis.gl/react-maplibre. AttributionControl is deliberately NOT
      null-mocked (as it is in the sibling viewer suites) — this suite exists to
      assert what reaches it, so it renders its props into the DOM. ── */
vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children }: { children?: ReactNode }) => (
    <div data-testid="mapgl">{children}</div>
  ),
  NavigationControl: () => null,
  ScaleControl: () => null,
  FullscreenControl: () => null,
  AttributionControl: ({ customAttribution }: { customAttribution?: string | string[] }) => (
    <div
      data-testid="attribution-control"
      data-custom-attribution={
        customAttribution === undefined
          ? 'undefined'
          : JSON.stringify(customAttribution)
      }
    />
  ),
  TerrainControl: () => null,
  Popup: ({ children }: { children?: ReactNode }) => (
    <div data-testid="feature-popup">{children}</div>
  ),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null } }),
  useBranding: () => ({ data: null }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({ data: { edition: 'community' } }),
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({ tokenMap: new Map() }),
}));

vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => false,
}));

vi.mock('@/components/map/MapCoordReadout', () => ({
  MapCoordReadout: () => null,
}));

vi.mock('@/api/geojson-z', () => ({
  fetchBoundedGeoJson: vi.fn(async () => ({
    type: 'FeatureCollection',
    features: [],
    total_count: 0,
    truncated: false,
  })),
  asFeatureCollection: (data: unknown) => data,
}));

import { ViewerMap } from '../ViewerMap';

const SWISSTOPO = '© swisstopo — swissALTI3D';
const NOAA = 'NOAA NCEI ETOPO 2022';

function layer(
  id: string,
  attribution: string | null,
  sortOrder: number,
): SharedLayerResponse {
  return {
    id,
    dataset_id: `dataset-${id}`,
    dataset_name: `Layer ${id}`,
    display_name: null,
    table_name: `data_${id}`,
    geometry_type: 'MultiPolygon',
    column_info: null,
    sort_order: sortOrder,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    tile_url: '',
    dataset_attribution: attribution,
  };
}

describe('collectLayerAttributions', () => {
  it('returns the visible layers’ credits in stacking order', () => {
    const layers = [layer('a', SWISSTOPO, 0), layer('b', NOAA, 1)];
    expect(collectLayerAttributions(layers, new Set(['a', 'b']))).toEqual([
      SWISSTOPO,
      NOAA,
    ]);
  });

  it('dedupes layers that share one source’s credit', () => {
    const layers = [
      layer('a', SWISSTOPO, 0),
      layer('b', SWISSTOPO, 1),
      layer('c', NOAA, 2),
    ];
    expect(collectLayerAttributions(layers, new Set(['a', 'b', 'c']))).toEqual([
      SWISSTOPO,
      NOAA,
    ]);
  });

  it('drops a layer’s credit when it is toggled off', () => {
    const layers = [layer('a', SWISSTOPO, 0), layer('b', NOAA, 1)];
    expect(collectLayerAttributions(layers, new Set(['b']))).toEqual([NOAA]);
    expect(collectLayerAttributions(layers, new Set())).toEqual([]);
  });

  it('ignores null, empty, and whitespace-only credits', () => {
    const layers = [
      layer('a', null, 0),
      layer('b', '', 1),
      layer('c', '   ', 2),
      layer('d', SWISSTOPO, 3),
    ];
    expect(collectLayerAttributions(layers, new Set(['a', 'b', 'c', 'd']))).toEqual([
      SWISSTOPO,
    ]);
  });

  it('trims surrounding whitespace before deduping', () => {
    const layers = [layer('a', `  ${SWISSTOPO}  `, 0), layer('b', SWISSTOPO, 1)];
    expect(collectLayerAttributions(layers, new Set(['a', 'b']))).toEqual([SWISSTOPO]);
  });

  it('handles an undefined layer list', () => {
    expect(collectLayerAttributions(undefined, new Set())).toEqual([]);
  });
});

describe('attributionControlKey', () => {
  // The key is what makes `customAttribution` live: react-maplibre builds the
  // control once, so two distinct credit sets that share a key are two sets a
  // toggle can move between with the control never updating.
  it('separates credit sets that a delimiter join would collide', () => {
    expect(attributionControlKey(['A|B'])).not.toBe(
      attributionControlKey(['A', 'B']),
    );
  });

  it('separates the same credits in a different order', () => {
    expect(attributionControlKey([SWISSTOPO, NOAA])).not.toBe(
      attributionControlKey([NOAA, SWISSTOPO]),
    );
  });

  it('is stable for an unchanged credit set', () => {
    expect(attributionControlKey([SWISSTOPO])).toBe(attributionControlKey([SWISSTOPO]));
  });

  it('separates the empty set from a single empty-string credit', () => {
    expect(attributionControlKey([])).not.toBe(attributionControlKey(['']));
  });
});

describe('ViewerMap — attribution control', () => {
  const baseProps = {
    basemapStyle: 'positron',
    initialViewState: {
      center_lng: 0,
      center_lat: 0,
      zoom: 1,
      bearing: 0,
      pitch: 0,
    },
  };

  it('passes the visible layers’ credits as customAttribution', () => {
    render(
      <ViewerMap
        {...baseProps}
        layers={[layer('a', SWISSTOPO, 0), layer('b', NOAA, 1)]}
        visibleLayers={new Set(['a', 'b'])}
      />,
    );

    expect(
      screen.getByTestId('attribution-control').dataset.customAttribution,
    ).toBe(JSON.stringify([SWISSTOPO, NOAA]));
  });

  it('omits customAttribution entirely when no layer requires credit', () => {
    render(
      <ViewerMap
        {...baseProps}
        layers={[layer('a', null, 0)]}
        visibleLayers={new Set(['a'])}
      />,
    );

    // Not `[]` — an empty array would still replace MapLibre's default option,
    // so the no-credit case must leave the control exactly as it was before.
    expect(
      screen.getByTestId('attribution-control').dataset.customAttribution,
    ).toBe('undefined');
  });

  it('updates the credits when a layer is toggled off', () => {
    const layers = [layer('a', SWISSTOPO, 0), layer('b', NOAA, 1)];
    const { rerender } = render(
      <ViewerMap {...baseProps} layers={layers} visibleLayers={new Set(['a', 'b'])} />,
    );
    expect(
      screen.getByTestId('attribution-control').dataset.customAttribution,
    ).toBe(JSON.stringify([SWISSTOPO, NOAA]));

    rerender(
      <ViewerMap {...baseProps} layers={layers} visibleLayers={new Set(['a'])} />,
    );
    expect(
      screen.getByTestId('attribution-control').dataset.customAttribution,
    ).toBe(JSON.stringify([SWISSTOPO]));
  });
});
