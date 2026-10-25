/**
 * A shared map without a saved view hands ViewerMap the layers' bounds: MapLibre
 * fits them at construction, and the load handler keeps the fit at zoom 2 or
 * closer, as the Builder's fit does.
 */
import type { ReactNode } from 'react';
import { act, render } from '@/test/test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ViewerMap } from '../ViewerMap';
import type { SharedLayerResponse } from '@/types/api';

const mapGlMock = vi.hoisted(() => ({
  props: null as null | { initialViewState?: Record<string, unknown>; onLoad?: (e: unknown) => void },
}));

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: (props: { children?: ReactNode; initialViewState?: Record<string, unknown>; onLoad?: (e: unknown) => void }) => {
    mapGlMock.props = props;
    return <div data-testid="mapgl">{props.children}</div>;
  },
  NavigationControl: () => null,
  ScaleControl: () => null,
  FullscreenControl: () => null,
  AttributionControl: () => null,
  TerrainControl: () => null,
  Popup: () => null,
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null } }),
  useBranding: () => ({ data: undefined }),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({ edition: 'community', features: [], isEnterprise: false, isLoading: false, isResolved: true }),
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

const CAMERA = { center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 };
const BOUNDS: [[number, number], [number, number]] = [[-180, -60], [180, 80]];

function renderViewer(bounds: typeof BOUNDS | null) {
  render(
    <ViewerMap
      layers={[] as SharedLayerResponse[]}
      basemapStyle="positron"
      initialViewState={{ ...CAMERA, bounds }}
      visibleLayers={new Set<string>()}
    />,
  );
}

/** A map double whose every method is a no-op, except the zoom it reports. */
function loadWithZoom(zoom: number) {
  const setZoom = vi.fn();
  const methods = new Map<PropertyKey, unknown>([
    ['getZoom', () => zoom],
    ['setZoom', setZoom],
  ]);
  const map = new Proxy({}, {
    get: (_target, prop) => {
      if (!methods.has(prop)) methods.set(prop, vi.fn());
      return methods.get(prop);
    },
  });
  act(() => { mapGlMock.props?.onLoad?.({ target: map }); });
  return setZoom;
}

describe('ViewerMap initial view', () => {
  beforeEach(() => {
    mapGlMock.props = null;
  });

  it('fits the given bounds at construction', () => {
    renderViewer(BOUNDS);

    expect(mapGlMock.props?.initialViewState).toMatchObject({
      bounds: BOUNDS,
      fitBoundsOptions: { padding: 40, maxZoom: 18 },
    });
  });

  it('opens at the center and zoom without bounds', () => {
    renderViewer(null);

    expect(mapGlMock.props?.initialViewState).toEqual({
      longitude: 0, latitude: 0, zoom: 2, bearing: 0, pitch: 0,
    });
  });

  it('keeps a wide fit at zoom 2', () => {
    renderViewer(BOUNDS);

    expect(loadWithZoom(0.8)).toHaveBeenCalledWith(2);
  });

  it('leaves a saved view below zoom 2 alone', () => {
    renderViewer(null);

    expect(loadWithZoom(1.5)).not.toHaveBeenCalled();
  });
});
