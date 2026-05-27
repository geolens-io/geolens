/**
 * Regression pins for SHARE-07: ViewerMap inline branding overlay.
 *
 * Pins 4 cases:
 * (1) community edition + showInlineBranding=true → branding text in DOM
 * (2) enterprise + show_badge=false + showInlineBranding=true → NOT in DOM
 * (3) enterprise + show_badge=true + showInlineBranding=true → IS in DOM (opted in)
 * (4) showInlineBranding=false (default) → NOT in DOM regardless of edition
 */
import type { ReactNode } from 'react';
import { render, screen } from '@/test/test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ViewerMap } from '../ViewerMap';
import type { SharedLayerResponse } from '@/types/api';

/* ── Mock @vis.gl/react-maplibre to avoid WebGL instantiation ── */
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

/* ── Mock heavy map-sync dependencies ── */
vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null } }),
  useBranding: vi.fn(),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({ tokenMap: new Map() }),
}));

vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
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

/* ── Import hooks after mocks are registered ── */
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';

const mockedUseEdition = vi.mocked(useEdition);
const mockedUseBranding = vi.mocked(useBranding);

const MINIMAL_PROPS = {
  layers: [] as SharedLayerResponse[],
  basemapStyle: 'positron',
  initialViewState: {
    center_lng: 0,
    center_lat: 0,
    zoom: 1,
    bearing: 0,
    pitch: 0,
  },
  visibleLayers: new Set<string>(),
};

describe('ViewerMap — SHARE-07 branding overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('(1) community edition with showInlineBranding=true renders branding text', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isLoading: false,
    });
    mockedUseBranding.mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useBranding>);

    render(<ViewerMap {...MINIMAL_PROPS} showInlineBranding={true} />);

    expect(screen.getByTestId('viewer-branding-overlay')).toBeInTheDocument();
    expect(screen.getByTestId('viewer-branding-overlay')).toHaveTextContent(/Powered by GeoLens/i);
  });

  it('(2) enterprise + show_badge=false + showInlineBranding=true suppresses branding', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: [],
      isEnterprise: true,
      isLoading: false,
    });
    mockedUseBranding.mockReturnValue({
      data: { show_badge: false },
    } as ReturnType<typeof useBranding>);

    render(<ViewerMap {...MINIMAL_PROPS} showInlineBranding={true} />);

    expect(screen.queryByTestId('viewer-branding-overlay')).not.toBeInTheDocument();
  });

  it('(3) enterprise + show_badge=true + showInlineBranding=true renders branding (enterprise opted in)', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: [],
      isEnterprise: true,
      isLoading: false,
    });
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true },
    } as ReturnType<typeof useBranding>);

    render(<ViewerMap {...MINIMAL_PROPS} showInlineBranding={true} />);

    expect(screen.getByTestId('viewer-branding-overlay')).toBeInTheDocument();
  });

  it('(4) showInlineBranding=false (default) never renders branding regardless of edition', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isLoading: false,
    });
    mockedUseBranding.mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useBranding>);

    // No showInlineBranding prop — defaults to false
    render(<ViewerMap {...MINIMAL_PROPS} />);

    expect(screen.queryByTestId('viewer-branding-overlay')).not.toBeInTheDocument();
  });
});
