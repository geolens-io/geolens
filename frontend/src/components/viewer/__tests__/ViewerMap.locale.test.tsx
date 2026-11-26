import type { ReactNode } from 'react';
import { act } from '@testing-library/react';
import { changeTestLanguage } from '@/test/i18n';
import { render, screen } from '@/test/test-utils';
import { afterEach, describe, it, expect, vi } from 'vitest';

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children, locale, cooperativeGestures }: { children?: ReactNode; locale?: Record<string, string>; cooperativeGestures?: boolean }) => (
    <div
      data-testid="mapgl"
      data-locale={JSON.stringify(locale ?? null)}
      data-cooperative={String(cooperativeGestures)}
    >
      {children}
    </div>
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

  it('turns cooperative gestures on only when asked, with the prompt in the interface language', async () => {
    await act(() => changeTestLanguage('fr'));
    const props = {
      basemapStyle: 'positron',
      initialViewState: { center_lng: 0, center_lat: 0, zoom: 1, bearing: 0, pitch: 0 },
      layers: [],
      visibleLayers: new Set<string>(),
    };

    const { rerender } = render(<ViewerMap {...props} />);
    expect(screen.getByTestId('mapgl').dataset.cooperative).toBe('false');

    rerender(<ViewerMap {...props} cooperativeGestures />);
    const map = screen.getByTestId('mapgl');
    expect(map.dataset.cooperative).toBe('true');
    const locale = JSON.parse(map.dataset.locale ?? 'null');
    expect(locale['CooperativeGesturesHandler.WindowsHelpText']).toBe('Utilisez Ctrl + molette pour zoomer sur la carte');
    expect(locale['CooperativeGesturesHandler.MacHelpText']).toContain('⌘');
    expect(locale['CooperativeGesturesHandler.MobileHelpText']).toBe('Utilisez deux doigts pour déplacer la carte');
  });
});
