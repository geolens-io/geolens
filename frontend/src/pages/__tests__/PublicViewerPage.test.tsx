import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { PublicViewerPage } from '../PublicViewerPage';
import { useSharedMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import type { SharedMapResponse } from '@/types/api';

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
  ViewerMap: () => <div data-testid="viewer-map">viewer map</div>,
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
  has_non_public_layers: false,
  layers: [
    {
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
    mockedUseSharedMap.mockReturnValue({
      data: SHARED_MAP,
      isLoading: false,
      isError: false,
      error: null,
    } as ReturnType<typeof useSharedMap>);

    mockedUseViewerLayers.mockReturnValue({
      visibleLayers: new Set([1]),
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
});
