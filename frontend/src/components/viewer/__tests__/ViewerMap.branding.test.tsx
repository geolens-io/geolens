/**
 * The GeoLens credit in the viewer's attribution control: shown for community
 * and for Enterprise with show_badge not false, absent while branding loads.
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
  AttributionControl: ({ customAttribution }: { customAttribution?: string | string[] }) => (
    <div data-testid="attribution-control" data-credits={JSON.stringify(customAttribution ?? null)} />
  ),
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

const COMMUNITY = {
  edition: 'community',
  features: [],
  isEnterprise: false,
  isMultiTenant: false,
  isLoading: false,
  isResolved: true,
} as ReturnType<typeof useEdition>;
const ENTERPRISE = { ...COMMUNITY, edition: 'enterprise', isEnterprise: true } as ReturnType<typeof useEdition>;

function credits(): string[] | null {
  return JSON.parse(screen.getByTestId('attribution-control').getAttribute('data-credits') ?? 'null');
}

function brandingData(data: unknown) {
  mockedUseBranding.mockReturnValue({ data } as ReturnType<typeof useBranding>);
}

describe('ViewerMap GeoLens attribution credit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('adds a safe link to the GeoLens site for community edition', () => {
    mockedUseEdition.mockReturnValue(COMMUNITY);
    brandingData({ show_badge: true, privacy_url: null });

    render(<ViewerMap {...MINIMAL_PROPS} />);

    const html = credits()?.at(-1) ?? '';
    expect(html).toContain('href="https://getgeolens.com"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('Powered by GeoLens');
  });

  it('adds the credit for enterprise with show_badge true', () => {
    mockedUseEdition.mockReturnValue(ENTERPRISE);
    brandingData({ show_badge: true, privacy_url: null });

    render(<ViewerMap {...MINIMAL_PROPS} />);

    expect(credits()).toHaveLength(1);
  });

  it('omits the credit for enterprise with show_badge false', () => {
    mockedUseEdition.mockReturnValue(ENTERPRISE);
    brandingData({ show_badge: false, privacy_url: null });

    render(<ViewerMap {...MINIMAL_PROPS} />);

    expect(credits()).toBeNull();
  });

  it('omits the credit while branding is still loading', () => {
    mockedUseEdition.mockReturnValue(COMMUNITY);
    brandingData(undefined);

    render(<ViewerMap {...MINIMAL_PROPS} />);

    expect(credits()).toBeNull();
  });

  it('puts the credit after the layer credits and drops the old overlay', () => {
    mockedUseEdition.mockReturnValue(COMMUNITY);
    brandingData({ show_badge: true, privacy_url: null });
    const layer = {
      id: 'a',
      dataset_id: 'd-a',
      dataset_name: 'A',
      display_name: null,
      table_name: 'a',
      geometry_type: 'POINT',
      column_info: null,
      sort_order: 0,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: null,
      tile_url: '',
      dataset_attribution: '(c) Source',
    } as SharedLayerResponse;

    render(<ViewerMap {...MINIMAL_PROPS} layers={[layer]} visibleLayers={new Set(['a'])} />);

    const all = credits() ?? [];
    expect(all).toHaveLength(2);
    expect(all[0]).toBe('(c) Source');
    expect(all[1]).toContain('getgeolens.com');
    expect(screen.queryByTestId('viewer-branding-overlay')).not.toBeInTheDocument();
  });
});
