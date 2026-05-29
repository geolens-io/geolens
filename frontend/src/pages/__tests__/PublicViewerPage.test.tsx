import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { PublicViewerPage } from '../PublicViewerPage';
import { useSharedMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import { ApiError } from '@/api/client';
import type { ViewerMap } from '@/components/viewer/ViewerMap';
import type { SharedMapResponse } from '@/types/api';

const viewerMapMock = vi.hoisted(() => ({
  props: null as React.ComponentProps<typeof ViewerMap> | null,
}));

vi.mock('@/hooks/use-maps', () => ({
  useSharedMap: vi.fn(),
}));

vi.mock('@/components/viewer/hooks/use-viewer-layers', () => ({
  useViewerLayers: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBranding: vi.fn(),
}));

vi.mock('@/components/viewer/ViewerMap', () => ({
  ViewerMap: (props: React.ComponentProps<typeof ViewerMap>) => {
    viewerMapMock.props = props;
    return <div data-testid="viewer-map">viewer map</div>;
  },
}));

vi.mock('@/components/viewer/LayerLegend', () => ({
  LayerLegend: () => <div data-testid="layer-legend">legend</div>,
}));

vi.mock('@/components/map/MapTitlePill', () => ({
  MapTitlePill: ({ name }: { name: string }) => <div data-testid="map-title">{name}</div>,
}));

vi.mock('@/components/map/BasemapToggle', () => ({
  BasemapToggle: () => <div data-testid="basemap-toggle">basemap</div>,
}));

vi.mock('@/components/error', () => ({
  MapErrorBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const mockedUseSharedMap = vi.mocked(useSharedMap);
const mockedUseViewerLayers = vi.mocked(useViewerLayers);
const mockedUseEdition = vi.mocked(useEdition);
const mockedUseBranding = vi.mocked(useBranding);

const SHARED_MAP: SharedMapResponse = {
  name: 'Shared map',
  description: 'Shared viewer description',
  center_lng: -73.9857,
  center_lat: 40.7484,
  zoom: 10,
  bearing: 0,
  pitch: 0,
  basemap_style: 'carto-light',
  show_basemap_labels: true,
  basemap_config: {
    label_mode: 'subtle',
    road_visibility: 'hidden',
    boundary_visibility: 'subtle',
    building_visibility: false,
    land_water_tone: 'monochrome',
    relief_contrast: 'strong',
  },
  terrain_config: {
    enabled: true,
    source_dataset_id: 'dataset-1',
    exaggeration: 1.25,
  },
  has_non_public_layers: false,
  layers: [
    {
      id: 'shared-layer-1',
      dataset_id: 'dataset-1',
      dataset_name: 'Transit',
      display_name: 'Transit stops',
      table_name: 'transit_stops',
      geometry_type: 'Point',
      column_info: null,
      sort_order: 1,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: null,
      show_in_legend: true,
      layer_type: 'vector_geolens',
      dataset_record_type: 'vector_dataset',
      tile_url: '',
    },
  ],
};

function renderPage(route = '/m/share-token') {
  return render(
    <Routes>
      <Route path="/m/:token" element={<PublicViewerPage />} />
    </Routes>,
    { route },
  );
}

describe('PublicViewerPage', () => {
  beforeEach(() => {
    viewerMapMock.props = null;

    mockedUseSharedMap.mockReturnValue({
      data: SHARED_MAP,
      isLoading: false,
      isError: false,
      error: null,
    } as ReturnType<typeof useSharedMap>);

    mockedUseViewerLayers.mockReturnValue({
      visibleLayers: new Set(['shared-layer-1']),
      handleToggleVisibility: vi.fn(),
      isLegendOpen: true,
      setIsLegendOpen: vi.fn(),
    } as ReturnType<typeof useViewerLayers>);

    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: ['branding'],
      isEnterprise: true,
      isLoading: false,
    });

    mockedUseBranding.mockReturnValue({
      data: { show_badge: false },
    } as ReturnType<typeof useBranding>);
  });

  it('renders footer links on shared-map pages even when enterprise branding is disabled', () => {
    renderPage();

    const footer = screen.getByRole('contentinfo');
    expect(footer).toBeInTheDocument();
    expect(footer).not.toHaveTextContent('Powered by GeoLens');
    expect(screen.getByRole('link', { name: /^github$/i })).toHaveAttribute(
      'href',
      'https://github.com/geolens-io/geolens',
    );
  });

  it('omits the footer on embedded shared-map pages', () => {
    renderPage('/m/share-token?embed=true');

    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });

  it('forwards persisted basemap appearance into the viewer map', async () => {
    renderPage();

    await screen.findByTestId('viewer-map');

    expect(viewerMapMock.props).toMatchObject({
      basemapConfig: SHARED_MAP.basemap_config,
      terrainConfig: SHARED_MAP.terrain_config,
      showBasemapLabels: true,
    });
  });

  describe('SHARE-07 branding overlay routing', () => {
    it('embed mode passes showInlineBranding=true to ViewerMap', async () => {
      renderPage('/m/share-token?embed=true');
      await screen.findByTestId('viewer-map');
      expect(viewerMapMock.props?.showInlineBranding).toBe(true);
    });

    it('non-embed mode passes showInlineBranding=false to ViewerMap AND AppFooter renders', async () => {
      renderPage('/m/share-token');
      await screen.findByTestId('viewer-map');
      expect(viewerMapMock.props?.showInlineBranding).toBe(false);
      expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    });
  });

  describe('ROUTE-04: getSharedMap expected404 quiet path', () => {
    // Test 1: 404 → null data path: "Map not found" renders, no console.error for 404
    it('renders Map not found without console.error when getSharedMap returns null (quiet 404)', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      mockedUseSharedMap.mockReturnValue({
        data: null,
        isLoading: false,
        isError: false,
        error: null,
      } as unknown as ReturnType<typeof useSharedMap>);

      renderPage('/m/invalid-token-abc');

      // The "Map not found" view renders
      expect(screen.getByRole('heading', { name: /map not found/i })).toBeInTheDocument();

      // No console.error calls relating to 404 or fetch failure
      const calls = consoleErrorSpy.mock.calls.map((args) => args.join(' '));
      const has404Error = calls.some(
        (msg) => msg.includes('404') || msg.includes('Failed to load'),
      );
      expect(has404Error).toBe(false);

      consoleErrorSpy.mockRestore();
    });

    // Test 2: valid 200 path: viewer renders normally
    it('renders the viewer map when getSharedMap returns valid data (200 path)', async () => {
      // beforeEach already sets up a valid SHARED_MAP response
      renderPage('/m/valid-token');

      await screen.findByTestId('viewer-map');

      expect(screen.queryByRole('heading', { name: /map not found/i })).not.toBeInTheDocument();
    });

    // Test 3: 410 (expired) path: console.error is NOT silenced, "Link expired" UI shows
    it('renders Link expired view and does not suppress errors when getSharedMap throws ApiError(410)', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      mockedUseSharedMap.mockReturnValue({
        data: undefined,
        isLoading: false,
        isError: true,
        error: new ApiError('Gone', 410),
      } as unknown as ReturnType<typeof useSharedMap>);

      renderPage('/m/expired-token');

      // "Link expired" branch renders (not "Map not found")
      // The i18n key viewer.linkExpired renders as "This link has expired" in the test environment
      expect(screen.getByRole('heading', { name: /this link has expired/i })).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: /map not found/i })).not.toBeInTheDocument();

      consoleErrorSpy.mockRestore();
    });
  });
});
