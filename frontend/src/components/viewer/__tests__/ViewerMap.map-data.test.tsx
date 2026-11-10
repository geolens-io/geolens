/**
 * ViewerMap's Map data entry: the launcher opens the docked panel under the
 * map area and its close returns focus to it; page overlays sit in the map
 * area; rendered features are queried only for the List view; and a feature
 * click on the map selects that feature for the panel's table.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import { viewerManagedLayerIds } from '../viewer-query-layer-ids';
import { useMapSelectionStore } from '@/stores/map-selection-store';
import type { SharedLayerResponse } from '@/types/api';

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

type FakeMap = {
  isStyleLoaded: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  moveLayer: ReturnType<typeof vi.fn>;
  removeSource: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  setMissingStyleImageResolver: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  setFilter: ReturnType<typeof vi.fn>;
  addLayer: ReturnType<typeof vi.fn>;
  addSource: ReturnType<typeof vi.fn>;
  removeLayer: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  setLayerZoomRange: ReturnType<typeof vi.fn>;
  hasImage: ReturnType<typeof vi.fn>;
  addImage: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  const fakeMap: FakeMap = {
    // Style loaded so the initial sync effects run synchronously (no idle-retry needed here).
    isStyleLoaded: vi.fn(() => true),
    on: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      handlers.get(event)?.delete(handler);
    }),
    once: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    setTransformRequest: vi.fn(),
    getLayer: vi.fn(() => ({ id: 'x' })),
    getSource: vi.fn(() => null),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    moveLayer: vi.fn(),
    removeSource: vi.fn(),
    setTerrain: vi.fn(),
    setMissingStyleImageResolver: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn(),
    removeLayer: vi.fn(),
    triggerRepaint: vi.fn(),
    setLayerZoomRange: vi.fn(),
    hasImage: vi.fn(() => true),
    addImage: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };
  return {
    fakeMap,
    handlers,
    reset: () => {
      handlers.clear();
      Object.values(fakeMap).forEach((v) => {
        if (typeof v === 'function' && 'mockClear' in v) (v as ReturnType<typeof vi.fn>).mockClear();
      });
      fakeMap.isStyleLoaded.mockReturnValue(true);
      fakeMap.getLayer.mockReturnValue({ id: 'x' });
      fakeMap.hasImage.mockReturnValue(true);
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: FakeMap }) => void }) => {
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

const tileConfigState = vi.hoisted(() => ({ cdn_base_url: null as string | null }));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: tileConfigState }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({ tokenMap: new Map([['dataset-pt', { kind: 'vector', token: 't' }]]) }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => false,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return { ...actual, applyBasemapConfigToMap: vi.fn(), syncLayersToMap: vi.fn() };
});
vi.mock('@/lib/builder/basemap-style-mutation', () => ({ applySublayerOverrides: vi.fn() }));

vi.mock('@/api/datasets', () => ({ getDatasetRows: vi.fn(() => new Promise(() => {})) }));

const LAYER: SharedLayerResponse = {
  id: 'pt-layer',
  dataset_id: 'dataset-pt',
  dataset_name: 'Points',
  display_name: 'Points',
  table_name: 'points',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  show_in_legend: true,
  opacity: 1,
  paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
};

function renderViewer(showAttributeTable = false, overlays?: ReactNode) {
  return render(
    <ViewerMap
      layers={[LAYER]}
      basemapStyle="openfreemap-positron"
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={new Set(['pt-layer'])}
      showAttributeTable={showAttributeTable}
      overlays={overlays}
    />,
  );
}

async function openPanel() {
  const launcher = screen.getByRole('button', { name: 'Map data' });
  await waitFor(() => expect(launcher).toBeEnabled());
  fireEvent.click(launcher);
  return screen.getByRole('region', { name: 'Map data' });
}

beforeAll(() => {
  window.matchMedia = vi.fn(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});

describe('ViewerMap Map data panel', () => {
  beforeEach(() => {
    mapState.reset();
    tileConfigState.cdn_base_url = null;
    useMapSelectionStore.getState().clear();
  });

  it('opens the docked panel from its launcher and returns focus to it on close', async () => {
    renderViewer();
    const launcher = screen.getByRole('button', { name: 'Map data' });
    await waitFor(() => expect(launcher).toBeEnabled());
    expect(launcher).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(launcher);

    const panel = screen.getByRole('region', { name: 'Map data' });
    expect(launcher).toHaveAttribute('aria-expanded', 'true');
    expect(launcher).toHaveAttribute('aria-controls', panel.id);
    // Docked in the viewer's root below the map area, not a modal dialog.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(panel.parentElement).toHaveAttribute('data-map-ready');

    fireEvent.click(screen.getByRole('button', { name: 'Close map data' }));

    expect(screen.queryByRole('region', { name: 'Map data' })).not.toBeInTheDocument();
    expect(launcher).toHaveFocus();
  });

  it('keeps page overlays in the map area, which the panel shortens rather than covers', async () => {
    renderViewer(false, <button type="button">Basemap</button>);
    const panel = await openPanel();

    const mapArea = screen.getByRole('button', { name: 'Basemap' }).parentElement!;
    expect(mapArea).toContainElement(screen.getByTestId('mapgl'));
    expect(mapArea).not.toContainElement(panel);
    expect(mapArea.nextElementSibling).toBe(panel);
  });

  it('queries the rendered features only while the List view shows', async () => {
    renderViewer(true);
    await openPanel();
    act(() => mapState.fakeMap.emit('idle'));
    expect(mapState.fakeMap.queryRenderedFeatures).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('radio', { name: 'List' }));

    expect(mapState.fakeMap.queryRenderedFeatures).toHaveBeenCalled();
  });

  it('offers the Table view only when the map turns the reader table on', async () => {
    const { unmount } = renderViewer(false);
    await openPanel();
    expect(screen.queryByRole('radio', { name: 'Table' })).not.toBeInTheDocument();
    unmount();

    renderViewer(true);
    await openPanel();
    expect(screen.getByRole('radio', { name: 'Table' })).toBeChecked();
  });

  it('selects a clicked feature for the table', async () => {
    renderViewer(true);
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('click', expect.any(Function));
    });
    const [layerId] = viewerManagedLayerIds(LAYER, 'pt-layer');
    mapState.fakeMap.queryRenderedFeatures.mockReturnValue([
      { id: 7, layer: { id: layerId }, properties: { name: 'A' }, geometry: { type: 'Point', coordinates: [0, 0] } },
    ]);

    act(() => {
      mapState.fakeMap.emit('click', { point: { x: 1, y: 1 }, lngLat: { lng: 0, lat: 0 } });
    });

    expect(useMapSelectionStore.getState().selection).toMatchObject({ layerId: 'pt-layer', featureId: 7 });
  });
});
