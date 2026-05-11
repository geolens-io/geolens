import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { PublicMapViewerPage } from '../PublicMapViewerPage';
import { useMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import type { ViewerMap } from '@/components/viewer/ViewerMap';
import type { MapResponse } from '@/types/api';

const viewerMapMock = vi.hoisted(() => ({
  props: null as React.ComponentProps<typeof ViewerMap> | null,
}));

vi.mock('@/hooks/use-maps', () => ({
  useMap: vi.fn(),
}));

vi.mock('@/components/viewer/hooks/use-viewer-layers', () => ({
  useViewerLayers: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
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

const mockedUseMap = vi.mocked(useMap);
const mockedUseViewerLayers = vi.mocked(useViewerLayers);

const PUBLIC_MAP: MapResponse = {
  id: 'map-1',
  name: 'Public map',
  description: 'Authenticated public map description',
  notes: null,
  center_lng: -112.14,
  center_lat: 36.06,
  zoom: 9,
  bearing: 0,
  pitch: 55,
  basemap_style: 'openfreemap-positron',
  show_basemap_labels: false,
  basemap_config: {
    label_mode: 'hidden',
    road_visibility: 'subtle',
    boundary_visibility: 'hidden',
    building_visibility: false,
    land_water_tone: 'contrast',
    relief_contrast: 'strong',
  },
  terrain_config: null,
  visibility: 'public',
  thumbnail_url: null,
  created_by: 'user-1',
  created_by_username: 'owner',
  created_at: '2026-05-11T00:00:00Z',
  updated_at: '2026-05-11T00:00:00Z',
  layer_count: 1,
  widgets: null,
  forked_from_id: null,
  forked_from_name: null,
  layers: [
    {
      id: 'layer-1',
      map_id: 'map-1',
      dataset_id: 'dataset-1',
      dataset_name: 'Canyon relief',
      display_name: 'Canyon relief',
      dataset_table_name: 'canyon_relief',
      dataset_geometry_type: 'Polygon',
      dataset_column_info: null,
      dataset_record_type: 'vector_dataset',
      dataset_feature_count: 100,
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
      is_3d: false,
      is_dem: false,
    },
  ],
};

function renderPage(route = '/maps/map-1/view') {
  return render(
    <Routes>
      <Route path="/maps/:id/view" element={<PublicMapViewerPage />} />
    </Routes>,
    { route },
  );
}

describe('PublicMapViewerPage', () => {
  beforeEach(() => {
    viewerMapMock.props = null;

    mockedUseMap.mockReturnValue({
      data: PUBLIC_MAP,
      isLoading: false,
      isError: false,
      error: null,
    } as ReturnType<typeof useMap>);

    mockedUseViewerLayers.mockReturnValue({
      visibleLayers: new Set([1]),
      handleToggleVisibility: vi.fn(),
      isLegendOpen: true,
      setIsLegendOpen: vi.fn(),
    } as ReturnType<typeof useViewerLayers>);
  });

  it('forwards persisted basemap appearance into the viewer map', async () => {
    renderPage();

    await screen.findByTestId('viewer-map');

    expect(viewerMapMock.props).toMatchObject({
      basemapConfig: PUBLIC_MAP.basemap_config,
      showBasemapLabels: false,
    });
  });
});
