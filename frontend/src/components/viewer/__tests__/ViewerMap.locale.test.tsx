import type { ReactNode } from 'react';
import { act } from '@testing-library/react';
import { changeTestLanguage } from '@/test/i18n';
import { render, screen } from '@/test/test-utils';
import { afterEach, describe, it, expect, vi } from 'vitest';

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children, locale }: { children?: ReactNode; locale?: Record<string, string> }) => (
    <div data-testid="mapgl" data-locale={JSON.stringify(locale ?? null)}>{children}</div>
  ),
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

import { ViewerMap } from '../ViewerMap';

describe('ViewerMap locale', () => {
  afterEach(async () => {
    await act(() => changeTestLanguage('en'));
  });

  it('gives the map control strings in the interface language', async () => {
    await act(() => changeTestLanguage('fr'));

    render(
      <ViewerMap
        basemapStyle="positron"
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 1, bearing: 0, pitch: 0 }}
        layers={[]}
        visibleLayers={new Set()}
      />,
    );

    const locale = JSON.parse(screen.getByTestId('mapgl').dataset.locale ?? 'null');
    expect(locale['NavigationControl.ZoomIn']).toBe('Zoom avant');
    expect(locale['FullscreenControl.Enter']).toBe('Plein écran');
  });
});
