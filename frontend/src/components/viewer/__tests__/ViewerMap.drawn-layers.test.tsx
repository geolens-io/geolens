// The viewer reports what it draws each layer as once any bounded cluster GeoJSON has settled.
import { useState, type ReactNode } from 'react';
import { render, screen, waitFor, within } from '@/test/test-utils';
import { BLANK_BASEMAP_ID } from '@/lib/basemap-utils';
import { fetchBoundedGeoJson, type BoundedGeoJsonResponse } from '@/api/geojson-z';
import type { DrawnLayer } from '@/components/map/legend-facts';
import { SAVED_LAYERS, toSharedLayer } from '@/test/fixtures/saved-layers';
import { LayerLegend } from '../LayerLegend';
import { ViewerMap } from '../ViewerMap';

const mapState = vi.hoisted(() => {
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  return {
    fakeMap: {
      isStyleLoaded: vi.fn(() => true),
      on: vi.fn(),
      off: vi.fn(),
      once: vi.fn(),
      setTransformRequest: vi.fn(),
      getLayer: vi.fn(() => ({ id: 'x' })),
      getSource: vi.fn(() => null),
      getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
      queryRenderedFeatures: vi.fn(() => []),
      getCanvas: vi.fn(() => canvas),
      getZoom: vi.fn(() => 5),
      setMissingStyleImageResolver: vi.fn(),
      setLayoutProperty: vi.fn(),
      setTerrain: vi.fn(),
      triggerRepaint: vi.fn(),
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: unknown }) => void }) => {
      React.useEffect(() => { onLoad?.({ target: mapState.fakeMap }); }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
    FullscreenControl: () => null,
    AttributionControl: () => null,
    TerrainControl: () => null,
    Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  };
});
vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' } }),
  useBranding: () => ({ data: undefined }),
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
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/api/geojson-z', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/geojson-z')>(),
  fetchBoundedGeoJson: vi.fn(),
}));
vi.mock('@/components/builder/map-composition-sync', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/components/builder/map-composition-sync')>(),
  applyMapBasemapAppearance: vi.fn(),
  syncMapComposition: vi.fn(),
}));

const EMPTY_GEOJSON: BoundedGeoJsonResponse = { type: 'FeatureCollection', features: [], truncated: false, total_count: 0 };
const { polygon, boundedCluster: cluster } = SAVED_LAYERS;

function renderViewer(onDrawnChange: (drawn: ReadonlyMap<string, unknown>) => void) {
  const layers = [polygon, cluster];
  render(
    <ViewerMap
      layers={layers.map(toSharedLayer)}
      basemapStyle={BLANK_BASEMAP_ID}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={new Set(layers.map((layer) => layer.id))}
      onDrawnChange={onDrawnChange}
    />,
  );
}

const SHARED_LAYERS = [polygon, cluster].map(toSharedLayer);
const VISIBLE = new Set([polygon.id, cluster.id]);

/** The map and its legend, joined through state the way the viewer pages join them. */
function ViewerWithLegend({ apiKey }: { apiKey: string }) {
  const [drawn, setDrawn] = useState<ReadonlyMap<string, DrawnLayer>>();
  return (
    <>
      <ViewerMap
        layers={SHARED_LAYERS}
        basemapStyle={BLANK_BASEMAP_ID}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={VISIBLE}
        apiKey={apiKey}
        onDrawnChange={setDrawn}
      />
      <LayerLegend layers={SHARED_LAYERS} visibleLayers={VISIBLE} onToggleVisibility={vi.fn()} isOpen onToggle={vi.fn()} drawn={drawn} />
    </>
  );
}

describe('ViewerMap drawn layers', () => {
  afterEach(() => {
    vi.mocked(fetchBoundedGeoJson).mockReset();
  });

  it('reports a bounded cluster whose GeoJSON arrived as a cluster', async () => {
    vi.mocked(fetchBoundedGeoJson).mockResolvedValue(EMPTY_GEOJSON);
    const onDrawnChange = vi.fn();
    renderViewer(onDrawnChange);

    await waitFor(() => expect(onDrawnChange).toHaveBeenCalled());
    expect(onDrawnChange.mock.lastCall![0]).toEqual(new Map([
      [polygon.id, { drawsAs: 'fill' }],
      [cluster.id, { drawsAs: 'cluster' }],
    ]));
  });

  it('reports a bounded cluster whose GeoJSON fetch failed as single points', async () => {
    vi.mocked(fetchBoundedGeoJson).mockRejectedValue(new Error('offline'));
    const onDrawnChange = vi.fn();
    renderViewer(onDrawnChange);

    await waitFor(() => expect(onDrawnChange).toHaveBeenCalled());
    expect(onDrawnChange.mock.lastCall![0].get(cluster.id)).toEqual({ drawsAs: 'circle' });
  });

  it('lets the legend name the saved strategy again while a new bounded GeoJSON request loads', async () => {
    vi.mocked(fetchBoundedGeoJson).mockRejectedValue(new Error('offline'));
    const { rerender } = render(<ViewerWithLegend apiKey="first" />);
    const bikeRacks = () => within(within(screen.getByRole('region', { name: 'Layers' })).getByText('Bike racks').closest('li')!);
    await waitFor(() => expect(bikeRacks().getByText('Point fallback')).toBeInTheDocument());

    vi.mocked(fetchBoundedGeoJson).mockReturnValue(new Promise(() => {}));
    rerender(<ViewerWithLegend apiKey="second" />);

    await waitFor(() => expect(bikeRacks().getByText('Bounded cluster')).toBeInTheDocument());
  });

  it('reports nothing while the bounded GeoJSON is loading', async () => {
    vi.mocked(fetchBoundedGeoJson).mockReturnValue(new Promise(() => {}));
    const onDrawnChange = vi.fn();
    renderViewer(onDrawnChange);

    await waitFor(() => expect(fetchBoundedGeoJson).toHaveBeenCalled());
    expect(onDrawnChange).not.toHaveBeenCalled();
  });
});
