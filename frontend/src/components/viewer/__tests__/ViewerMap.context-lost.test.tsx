import type { ReactNode } from 'react';
import { render, screen } from '@/test/test-utils';
import { describe, it, expect, vi } from 'vitest';

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children }: { children?: ReactNode }) => (
    <div data-testid="mapgl">{children}</div>
  ),
  NavigationControl: () => null,
  ScaleControl: () => null,
  FullscreenControl: () => null,
  AttributionControl: () => null,
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
  useWebGLRecovery: () => ({ contextLost: true, reload: vi.fn() }),
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

describe('ViewerMap — lost WebGL context', () => {
  it('announces the failure to assistive tech with a reload action', () => {
    render(
      <ViewerMap
        basemapStyle="positron"
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 1, bearing: 0, pitch: 0 }}
        layers={[]}
        visibleLayers={new Set()}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toContainElement(screen.getByRole('button', { name: /reload/i }));
  });
});
