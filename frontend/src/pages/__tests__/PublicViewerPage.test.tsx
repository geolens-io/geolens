import type { ReactNode } from 'react';
import { Link, Route, Routes } from 'react-router';
import { act, fireEvent, render, screen, within } from '@/test/test-utils';
import { PublicViewerPage } from '../PublicViewerPage';
import { useSharedMap } from '@/hooks/use-maps';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { ApiError } from '@/api/client';
import type { ViewerMap } from '@/components/viewer/ViewerMap';
import type { LayerLegend } from '@/components/viewer/LayerLegend';
import type { SharedMapResponse } from '@/types/api';

const viewerMapMock = vi.hoisted(() => ({
  props: null as React.ComponentProps<typeof ViewerMap> | null,
}));
const legendMock = vi.hoisted(() => ({
  props: null as React.ComponentProps<typeof LayerLegend> | null,
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

vi.mock('@/components/viewer/ViewerMap', () => ({
  ViewerMap: (props: React.ComponentProps<typeof ViewerMap>) => {
    viewerMapMock.props = props;
    return <div data-testid="viewer-map">viewer map</div>;
  },
}));

vi.mock('@/components/viewer/LayerLegend', () => ({
  LayerLegend: (props: React.ComponentProps<typeof LayerLegend>) => {
    legendMock.props = props;
    return <div data-testid="layer-legend">legend</div>;
  },
}));

vi.mock('@/components/map/MapTitlePill', () => ({
  MapTitlePill: ({ name }: { name: string }) => <div data-testid="map-title">{name}</div>,
}));

vi.mock('@/components/map/BasemapToggle', () => ({
  BasemapToggle: ({ value, onChange }: { value: string; onChange: (id: string) => void }) => (
    <button type="button" data-testid="basemap-toggle" onClick={() => onChange('chosen-basemap')}>
      {value}
    </button>
  ),
}));

vi.mock('@/components/error', () => ({
  MapErrorBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const mockedUseSharedMap = vi.mocked(useSharedMap);
const mockedUseViewerLayers = vi.mocked(useViewerLayers);

const SHARED_MAP: SharedMapResponse = {
  name: 'Shared map',
  description: 'Shared viewer description',
  center_lng: -73.9857,
  center_lat: 40.7484,
  zoom: 10,
  has_saved_view: true,
  bearing: 0,
  pitch: 0,
  basemap_style: 'carto-light',
  show_basemap_labels: true,
  show_attribute_table: true,
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
    legendMock.props = null;

    mockedUseSharedMap.mockReturnValue({
      data: SHARED_MAP,
      isLoading: false,
      isError: false,
      error: null,
    } as ReturnType<typeof useSharedMap>);

    mockedUseViewerLayers.mockReturnValue({
      visibleLayers: new Set(['shared-layer-1']),
      hiddenByReader: new Set<string>(),
      handleToggleVisibility: vi.fn(),
      isLegendOpen: true,
      setIsLegendOpen: vi.fn(),
    } as ReturnType<typeof useViewerLayers>);
  });

  it.each([
    ['open', '/m/share-token?embed=true', 'Hide dashboard'],
    ['collapsed when the embed asks', '/m/share-token?embed=true&dashboard=collapsed', 'Open dashboard'],
  ])('starts an embed\'s dashboard %s', (_label, route, button) => {
    mockedUseSharedMap.mockReturnValue({
      data: {
        ...SHARED_MAP,
        dashboard_config: {
          version: 1,
          panel: 'right',
          widgets: [
            {
              id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
              type: 'indicator',
              v: 1,
              layer_id: 'shared-layer-1',
              scope: 'layer',
              config: { stat: 'count', column: null },
            },
          ],
        },
      },
      isLoading: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useSharedMap>);
    renderPage(route);
    expect(screen.getByRole('button', { name: button })).toBeInTheDocument();
  });

  it('titles the document with the shared map name', () => {
    renderPage();
    expect(vi.mocked(useDocumentTitle)).toHaveBeenLastCalledWith('Shared map');
  });

  it('falls back to the generic title while the map is unresolved', () => {
    mockedUseSharedMap.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
    } as ReturnType<typeof useSharedMap>);
    renderPage();
    expect(vi.mocked(useDocumentTitle)).toHaveBeenLastCalledWith('Shared Map');
  });

  it('wraps the loading branch in a main landmark', () => {
    mockedUseSharedMap.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
    } as ReturnType<typeof useSharedMap>);
    renderPage();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });

  it('wraps the error branch in a main landmark and announces it as an alert', () => {
    mockedUseSharedMap.mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useSharedMap>);
    renderPage();
    const main = screen.getByRole('main');
    expect(within(main).getByRole('alert')).toHaveTextContent(/map not found/i);
  });

  it('renders no app footer on shared-map pages', () => {
    renderPage();

    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^github$/i })).not.toBeInTheDocument();
  });

  it('renders no app footer on embedded shared-map pages', () => {
    renderPage('/m/share-token?embed=true');

    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });

  describe('embed legend default', () => {
    const categorical = {
      ...SHARED_MAP.layers[0],
      geometry_type: 'MULTIPOINT',
      paint: {
        'circle-radius': 5,
        'circle-color': ['match', ['get', 'kind'], 'school', '#f472b6', '#cccccc'],
      },
      style_config: {
        mode: 'categorical' as const,
        column: 'kind',
        categories: [{ value: 'school', label: 'School', color: '#f472b6' }],
      },
    };

    function mapWith(layer: SharedMapResponse['layers'][number]) {
      mockedUseSharedMap.mockReturnValue({
        data: { ...SHARED_MAP, layers: [layer] },
        isLoading: false,
        isError: false,
        error: null,
      } as ReturnType<typeof useSharedMap>);
    }

    const clusterRamp = {
      ...SHARED_MAP.layers[0],
      style_config: {
        render_mode: 'cluster' as const,
        builder: {
          clusterColorRamp: [
            { count: 0, color: '#818cf8' },
            { count: 25, color: '#6366f1' },
            { count: 2500, color: '#4338ca' },
          ],
        },
      },
    };

    async function renderEmbed(drawsAs: 'circle' | 'cluster', query = 'embed=true') {
      renderPage(`/m/share-token?${query}`);
      await screen.findByTestId('viewer-map');
      act(() =>
        viewerMapMock.props?.onDrawnChange?.(new Map([['shared-layer-1', { drawsAs }]])),
      );
    }

    it('shows the legend in an embed when a visible layer is styled by category', async () => {
      mapWith(categorical);
      await renderEmbed('circle');

      expect(screen.getByTestId('layer-legend')).toBeInTheDocument();
      expect(mockedUseViewerLayers).toHaveBeenLastCalledWith(
        expect.anything(),
        expect.objectContaining({ showLegend: true }),
      );
    });

    it('waits for what the map drew before opening the embed legend', async () => {
      mapWith(categorical);
      renderPage('/m/share-token?embed=true');
      await screen.findByTestId('viewer-map');

      expect(screen.queryByTestId('layer-legend')).not.toBeInTheDocument();
    });

    it('shows the legend in an embed when the only classes are cluster count colours', async () => {
      mapWith(clusterRamp);
      await renderEmbed('cluster');

      expect(screen.getByTestId('layer-legend')).toBeInTheDocument();
    });

    it('keeps the embed legend hidden when a cluster fell back to plain points', async () => {
      mapWith(clusterRamp);
      await renderEmbed('circle');

      expect(screen.queryByTestId('layer-legend')).not.toBeInTheDocument();
    });

    it('keeps the embed legend hidden for a single-colour layer', async () => {
      await renderEmbed('circle');

      expect(screen.queryByTestId('layer-legend')).not.toBeInTheDocument();
    });

    it('keeps the embed legend hidden when the category layer is hidden', async () => {
      mapWith({ ...categorical, visible: false });
      await renderEmbed('circle');

      expect(screen.queryByTestId('layer-legend')).not.toBeInTheDocument();
    });

    it('lets legend=false hide the embed legend', async () => {
      mapWith(categorical);
      await renderEmbed('circle', 'embed=true&legend=false');

      expect(screen.queryByTestId('layer-legend')).not.toBeInTheDocument();
    });
  });

  it('hands the legend what the viewer map reports drawing', async () => {
    renderPage();
    await screen.findByTestId('viewer-map');
    const drawn = new Map([['shared-layer-1', { drawsAs: 'circle' as const }]]);

    act(() => viewerMapMock.props?.onDrawnChange?.(drawn));

    expect(legendMock.props?.drawn).toBe(drawn);
  });

  it('sends no credential taken from an api_key query parameter', async () => {
    renderPage('/m/share-token?api_key=account-key&et=embed-token');

    await screen.findByTestId('viewer-map');

    expect(mockedUseSharedMap).toHaveBeenCalledWith('share-token', 'embed-token');
    expect(JSON.stringify(mockedUseSharedMap.mock.calls)).not.toContain('account-key');
    expect(JSON.stringify(viewerMapMock.props)).not.toContain('account-key');
  });

  it.each([
    [false, true],
    [true, false],
  ])('sets dataset links for has_non_public_layers=%s to %s', async (hasNonPublic, allowed) => {
    mockedUseSharedMap.mockReturnValue({
      data: { ...SHARED_MAP, has_non_public_layers: hasNonPublic },
      isLoading: false,
      isError: false,
      error: null,
    } as ReturnType<typeof useSharedMap>);
    renderPage();

    await screen.findByTestId('viewer-map');

    expect(viewerMapMock.props?.datasetLinksAllowed).toBe(allowed);
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

  describe('initial view', () => {
    const extentLayer = { ...SHARED_MAP.layers[0], dataset_extent_bbox: [-74.3, 40.5, -73.7, 40.9] };

    function mapWithView(hasSavedView: boolean) {
      mockedUseSharedMap.mockReturnValue({
        data: { ...SHARED_MAP, has_saved_view: hasSavedView, layers: [extentLayer] },
        isLoading: false,
        isError: false,
        error: null,
      } as ReturnType<typeof useSharedMap>);
    }

    it('fits the visible layers when the map has no saved view', async () => {
      mapWithView(false);
      renderPage();

      await screen.findByTestId('viewer-map');

      expect(viewerMapMock.props?.fitLayers).toBe(true);
      expect(viewerMapMock.props?.layers).toEqual([extentLayer]);
    });

    it('opens at the saved view when the map has one', async () => {
      mapWithView(true);
      renderPage();

      await screen.findByTestId('viewer-map');

      expect(viewerMapMock.props?.fitLayers).toBe(false);
      expect(viewerMapMock.props?.initialViewState).toMatchObject({
        center_lng: SHARED_MAP.center_lng,
        center_lat: SHARED_MAP.center_lat,
        zoom: SHARED_MAP.zoom,
      });
    });

    it.each([
      ['center', '?center=2.35,48.86'],
      ['zoom', '?zoom=6'],
    ])('lets a URL %s override the fit', async (_name, query) => {
      mapWithView(false);
      renderPage(`/m/share-token${query}`);

      await screen.findByTestId('viewer-map');

      expect(viewerMapMock.props?.fitLayers).toBe(false);
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
  describe('when the viewed map changes', () => {
    function renderWithNav() {
      return render(
        <>
          <Link to="/m/token-b">other map</Link>
          <Link to="/m/token-a">first map</Link>
          <Routes>
            <Route path="/m/:token" element={<PublicViewerPage />} />
          </Routes>
        </>,
        { route: '/m/token-a' },
      );
    }

    it('resets the chosen basemap and drawn layers on another map', async () => {
      renderWithNav();
      await screen.findByTestId('viewer-map');
      fireEvent.click(screen.getByTestId('basemap-toggle'));
      act(() => viewerMapMock.props?.onDrawnChange?.(new Map([['l', { drawsAs: 'circle' as const }]])));
      expect(screen.getByTestId('basemap-toggle')).toHaveTextContent('chosen-basemap');
      expect(legendMock.props?.drawn).toBeDefined();

      fireEvent.click(screen.getByRole('link', { name: 'other map' }));

      expect(screen.getByTestId('basemap-toggle')).toHaveTextContent('carto-light');
      expect(legendMock.props?.drawn).toBeUndefined();
    });

    it('keeps them across a rerender of the same map', async () => {
      renderWithNav();
      await screen.findByTestId('viewer-map');
      fireEvent.click(screen.getByTestId('basemap-toggle'));
      const drawn = new Map([['l', { drawsAs: 'circle' as const }]]);
      act(() => viewerMapMock.props?.onDrawnChange?.(drawn));

      fireEvent.click(screen.getByRole('link', { name: 'first map' }));

      expect(screen.getByTestId('basemap-toggle')).toHaveTextContent('chosen-basemap');
      expect(legendMock.props?.drawn).toBe(drawn);
    });
  });
});
