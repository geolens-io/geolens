import { createRef, useEffect, type ReactNode } from 'react';
import { act, render, screen } from '@/test/test-utils';
import { StoryMapPane, type StoryMapPaneHandle } from '../StoryMapPane';
import type { ResolvedScene } from '../story-scenes';
import type { ViewerMap } from '@/components/viewer/ViewerMap';
import { isViewerTerrainExpected } from '@/components/viewer/hooks/use-viewer-terrain';
import type { MapResponse, StoryScene } from '@/types/api';

type ViewerMapProps = React.ComponentProps<typeof ViewerMap>;

const viewer = vi.hoisted(() => ({ props: null as ViewerMapProps | null, mounts: 0 }));
const fakeMap = vi.hoisted(() => {
  const initialView = { lng: 199.1234567, lat: 26.9876543, zoom: 6.7891234, bearing: 10, pitch: 20 };
  const handlers = new Map<string, Set<(event?: unknown) => void>>();
  const map = {
    view: { ...initialView },
    flyTo: vi.fn(),
    easeTo: vi.fn(),
    jumpTo: vi.fn(),
    focus: vi.fn(),
    getCanvas: () => ({ focus: map.focus }),
    getContainer: () => ({ clientWidth: 1000, clientHeight: 500 }),
    getCenter: () => ({ lng: map.view.lng, lat: map.view.lat }),
    getZoom: () => map.view.zoom,
    getBearing: () => map.view.bearing,
    getPitch: () => map.view.pitch,
    // One pixel per degree around the container's centre keeps the distances easy to read.
    project: ([lng, lat]: [number, number]) => ({ x: 500 + lng - map.view.lng, y: 250 - (lat - map.view.lat) }),
    on: (event: string, handler: (event?: unknown) => void) => {
      handlers.set(event, (handlers.get(event) ?? new Set()).add(handler));
    },
    off: (event: string, handler: (event?: unknown) => void) => void handlers.get(event)?.delete(handler),
    emit: (event: string, payload?: unknown) => [...(handlers.get(event) ?? [])].forEach((handler) => handler(payload)),
    reset: () => {
      map.view = { ...initialView };
      handlers.clear();
    },
  };
  return map;
});

vi.mock('@/components/viewer/ViewerMap', () => ({
  ViewerMap: (props: ViewerMapProps) => {
    viewer.props = props;
    useEffect(() => {
      viewer.mounts += 1;
    }, []);
    return <div data-testid="viewer-map" />;
  },
}));
const legend = vi.hoisted(() => ({ props: null as Record<string, unknown> | null }));
vi.mock('@/components/viewer/LayerLegend', () => ({
  LayerLegend: (props: Record<string, unknown>) => {
    legend.props = props;
    return null;
  },
}));
vi.mock('@/components/error', () => ({
  MapErrorBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock('@/hooks/use-maps', () => ({
  useMap: (id: string) => ({ data: MAPS[id], isLoading: false, isError: false }),
}));

function layer(id: string, visible: boolean) {
  return { id, dataset_id: `ds-${id}`, dataset_table_name: id, sort_order: 0, visible, paint: {}, layout: {} };
}

const MAPS: Record<string, MapResponse> = {
  'map-a': {
    id: 'map-a',
    basemap_style: 'positron',
    layers: [layer('roads', true), layer('rivers', false), layer('towns', true)],
  } as unknown as MapResponse,
  'map-b': { id: 'map-b', basemap_style: 'positron', layers: [] } as unknown as MapResponse,
  'map-dem': {
    id: 'map-dem',
    basemap_style: 'positron',
    terrain_config: { enabled: true, source_dataset_id: 'ds-dem', exaggeration: 1 },
    layers: [{ ...layer('dem', false), is_dem: true, dataset_record_type: 'raster_dataset' }],
  } as unknown as MapResponse,
};

function resolved(
  chapterId: string,
  mapId: string,
  zoom: number,
  layerVisibility: StoryScene['layer_visibility'] = {},
  transition?: StoryScene['transition'],
): ResolvedScene {
  return {
    chapterId,
    scene: {
      map_id: mapId,
      camera: { center: [-70, 25], zoom, bearing: 0, pitch: 0 },
      layer_visibility: layerVisibility,
      transition,
    },
  };
}

/** Puts the fake map on the scene's camera at zoom 3, as if the reader had arrived. */
function viewAt(lng: number, lat: number, zoom: number) {
  fakeMap.view = { lng, lat, zoom, bearing: 0, pitch: 0 };
}

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion'),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => {
  viewer.props = null;
  viewer.mounts = 0;
  fakeMap.reset();
  fakeMap.flyTo.mockReset();
  fakeMap.easeTo.mockReset();
  fakeMap.jumpTo.mockReset();
  fakeMap.focus.mockReset();
  mockReducedMotion(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderReady(scene: ResolvedScene) {
  const view = render(<StoryMapPane resolved={scene} />);
  await screen.findByTestId('viewer-map');
  act(() => viewer.props!.onMapReady!(fakeMap as never));
  return view;
}

it('flies within the same map when the scene has no transition, timed by the zoom change', async () => {
  viewAt(-70, 25, 3);
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
  // No pan; three zoom levels at 150 px each on top of the 600 ms floor.
  expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 6, duration: 1050 }));
  expect(fakeMap.easeTo).not.toHaveBeenCalled();
  expect(viewer.mounts).toBe(1);
});

it('caps the duration of a long move at 2.5 seconds', async () => {
  viewAt(-70, 25, 20);
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 3)} />);
  expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ duration: 2500 }));
});

it('glides with easeTo when the chapter asks for it', async () => {
  viewAt(-70, 25, 3);
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 4, {}, 'glide')} />);
  expect(fakeMap.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 4, duration: 750 }));
  expect(fakeMap.flyTo).not.toHaveBeenCalled();
});

it('cuts with a zero-length move when the chapter asks for it', async () => {
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6, {}, 'cut')} />);
  expect(fakeMap.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 6, duration: 0 }));
  expect(fakeMap.flyTo).not.toHaveBeenCalled();
});

it.each([
  ['fly', 'flyTo'],
  ['glide', 'easeTo'],
] as const)('makes a %s a zero-length move under reduced motion', async (transition, method) => {
  mockReducedMotion(true);
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6, {}, transition)} />);
  expect(fakeMap[method]).toHaveBeenCalledWith(expect.objectContaining({ zoom: 6, duration: 0 }));
});

it('remounts on another map, opening at the new camera', async () => {
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} />);
  await screen.findByTestId('viewer-map');
  expect(viewer.mounts).toBe(2);
  expect(viewer.props?.initialViewState).toMatchObject({ zoom: 7, center_lng: -70 });
  expect(fakeMap.flyTo).not.toHaveBeenCalled();
});

it('moves to the latest scene once a map that loaded late is ready', async () => {
  const { rerender } = render(<StoryMapPane resolved={resolved('c1', 'map-a', 3)} />);
  await screen.findByTestId('viewer-map');
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 9)} />);
  act(() => viewer.props!.onMapReady!(fakeMap as never));
  expect(fakeMap.jumpTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 9 }));
});

it("applies the scene's layer visibility over the saved one and ignores stale ids", async () => {
  render(<StoryMapPane resolved={resolved('c1', 'map-a', 3, { roads: false, rivers: true, gone: true })} />);
  await screen.findByTestId('viewer-map');
  expect([...viewer.props!.visibleLayers].sort()).toEqual(['rivers', 'towns']);
});

it("reads the map's view as a scene stores it, and nothing before the map is ready", async () => {
  const ref = createRef<StoryMapPaneHandle>();
  render(<StoryMapPane ref={ref} resolved={resolved('c1', 'map-a', 3)} />);
  await screen.findByTestId('viewer-map');
  expect(ref.current?.getView()).toBeNull();

  act(() => viewer.props!.onMapReady!(fakeMap as never));
  expect(ref.current?.getView()).toEqual({ center: [-160.876543, 26.987654], zoom: 6.789123, bearing: 10, pitch: 20 });
});

it('shows the hint in place of a map while there is no scene', () => {
  const ref = createRef<StoryMapPaneHandle>();
  render(<StoryMapPane ref={ref} resolved={null} emptyHint="Choose a map" />);
  expect(screen.getByText('Choose a map')).toBeInTheDocument();
  expect(ref.current).toBeNull();
});

it("drops the reader's legend toggles when the scene's layer visibility changes", async () => {
  const { rerender } = render(<StoryMapPane resolved={resolved('c1', 'map-a', 3, { rivers: true })} />);
  await screen.findByTestId('viewer-map');
  act(() => (legend.props!.onToggleVisibility as (key: string) => void)('rivers'));
  expect(viewer.props!.visibleLayers.has('rivers')).toBe(false);

  rerender(<StoryMapPane resolved={resolved('c1', 'map-a', 3, { rivers: true, towns: false })} />);
  expect([...viewer.props!.visibleLayers].sort()).toEqual(['rivers', 'roads']);
});

it('passes what the map draws to the legend, as the map viewer does', async () => {
  render(<StoryMapPane resolved={resolved('c1', 'map-a', 3)} />);
  await screen.findByTestId('viewer-map');
  const drawn = new Map([['roads', { kind: 'line' }]]);
  act(() => viewer.props!.onDrawnChange!(drawn as never));
  expect(legend.props!.drawn).toBe(drawn);
});

it("keeps a reader's pan when a refetch brings the same chapter with another camera", async () => {
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c1', 'map-a', 8)} />);
  expect(fakeMap.flyTo).not.toHaveBeenCalled();
});

it("moves back to the scene's camera when the editor replaces the scenes", async () => {
  const { rerender } = render(<StoryMapPane resolved={resolved('c1', 'map-a', 3)} resetKey={0} />);
  await screen.findByTestId('viewer-map');
  act(() => viewer.props!.onMapReady!(fakeMap as never));
  rerender(<StoryMapPane resolved={resolved('c1', 'map-a', 5)} resetKey={1} />);
  expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 5 }));
  expect(viewer.mounts).toBe(1);
});

const READER_MOVE = { originalEvent: new Event('mousedown') };

describe('the return button', () => {
  const backButton = () => screen.queryByRole('button', { name: "Back to this chapter's view" });

  // The reader pans away once the chapter's own move has finished.
  function panAway() {
    fakeMap.view = { ...fakeMap.view, lng: -40 };
    act(() => fakeMap.emit('moveend', READER_MOVE));
  }

  beforeEach(() => viewAt(-70, 25, 3));

  it('appears once the reader moves the camera off the chapter view, without taking focus', async () => {
    await renderReady(resolved('c1', 'map-a', 3));
    expect(backButton()).toBeNull();
    const focused = document.activeElement;

    panAway();
    expect(backButton()).toBeInTheDocument();
    expect(document.activeElement).toBe(focused);
  });

  it('ignores a nudge inside the tolerance', async () => {
    await renderReady(resolved('c1', 'map-a', 3));
    fakeMap.view = { ...fakeMap.view, lng: -69.9, zoom: 3.05, bearing: 0.5, pitch: 0.5 };
    act(() => fakeMap.emit('moveend', READER_MOVE));
    expect(backButton()).toBeNull();
  });

  it.each([
    ['zoom', { zoom: 3.2 }],
    ['bearing', { bearing: 5 }],
    ['pitch', { pitch: 5 }],
    ['bearing across north', { bearing: 355 }],
  ])('appears when the %s moves beyond the tolerance', async (_name, change) => {
    await renderReady(resolved('c1', 'map-a', 3));
    fakeMap.view = { ...fakeMap.view, ...change };
    act(() => fakeMap.emit('moveend', READER_MOVE));
    expect(backButton()).toBeInTheDocument();
  });

  it("stays hidden through the chapter's own transition, including the end an interrupted flight fires", async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, zoom: 4.5 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, zoom: 6 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeNull();
  });

  it("counts a drag that ends the chapter's transition early as a move", async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);

    fakeMap.view = { ...fakeMap.view, zoom: 4.5 };
    act(() => fakeMap.emit('moveend', READER_MOVE));
    expect(backButton()).toBeInTheDocument();
  });

  it("moves back with the chapter's transition and resets the reader's legend toggles", async () => {
    await renderReady(resolved('c1', 'map-a', 3, {}, 'glide'));
    act(() => (legend.props!.onToggleVisibility as (key: string) => void)('roads'));
    expect(viewer.props!.visibleLayers.has('roads')).toBe(false);
    panAway();

    act(() => backButton()!.click());
    expect(fakeMap.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 3, center: [-70, 25] }));
    expect([...viewer.props!.visibleLayers].sort()).toEqual(['roads', 'towns']);
    expect(backButton()).toBeNull();
    expect(fakeMap.focus).toHaveBeenCalled();
  });

  it('moves back at once under reduced motion', async () => {
    mockReducedMotion(true);
    await renderReady(resolved('c1', 'map-a', 3));
    panAway();

    act(() => backButton()!.click());
    expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ center: [-70, 25], duration: 0 }));
  });

  it('returns to the scene a chapter without its own inherits', async () => {
    // The pane gets the inherited scene already resolved, under the chapter that owns it.
    await renderReady(resolved('c1', 'map-a', 3));
    panAway();
    act(() => backButton()!.click());
    expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 3, center: [-70, 25] }));
  });
});

it('turns the layer fades on for the story reader', async () => {
  render(<StoryMapPane resolved={resolved('c1', 'map-a', 3)} />);
  await screen.findByTestId('viewer-map');
  expect(viewer.props!.fadeLayerChanges).toBe(true);
});

it('turns on terrain from a DEM the map saved as hidden when the scene shows it', async () => {
  render(<StoryMapPane resolved={resolved('c1', 'map-dem', 3, { dem: true })} />);
  await screen.findByTestId('viewer-map');
  const props = viewer.props!;
  expect(isViewerTerrainExpected(props.layers, props.terrainConfig)).toBe(true);
  expect(props.visibleLayers.has('dem')).toBe(true);
  expect(legend.props!.layers).toBe(props.layers);
});
