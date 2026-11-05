import { createRef, useEffect, type ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { StoryMapPane, type StoryMapPaneHandle } from '../StoryMapPane';
import type { ResolvedScene } from '../story-scenes';
import type { ViewerMap } from '@/components/viewer/ViewerMap';
import { isViewerTerrainExpected } from '@/components/viewer/hooks/use-viewer-terrain';
import type { MapResponse, StoryScene } from '@/types/api';

type ViewerMapProps = React.ComponentProps<typeof ViewerMap>;

const viewer = vi.hoisted(() => ({ props: null as ViewerMapProps | null, mounts: 0, byBasemap: {} as Record<string, ViewerMapProps> }));
const makeFakeMap = vi.hoisted(() => () => {
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
const fakeMap = vi.hoisted(() => makeFakeMap());
const nextMaps = vi.hoisted(() => ({ 'map-b': makeFakeMap(), 'map-c': makeFakeMap() }));

vi.mock('@/components/viewer/ViewerMap', () => ({
  ViewerMap: (props: ViewerMapProps) => {
    viewer.props = props;
    useEffect(() => {
      viewer.mounts += 1;
    }, []);
    viewer.byBasemap[props.basemapStyle as string] = props;
    return <div data-testid="viewer-map" data-basemap={props.basemapStyle} />;
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
  'map-b': { id: 'map-b', basemap_style: 'voyager', layers: [] } as unknown as MapResponse,
  'map-c': { id: 'map-c', basemap_style: 'dark-matter', layers: [] } as unknown as MapResponse,
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
  viewer.byBasemap = {};
  fakeMap.reset();
  for (const map of Object.values(nextMaps)) {
    map.reset();
    map.flyTo.mockReset();
    map.easeTo.mockReset();
    map.jumpTo.mockReset();
  }
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

  it("stays hidden through the chapter's own transition, and settles when it ends", async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, zoom: 6 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeNull();
  });

  it("appears when a press stops the chapter's flight between two views", async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, zoom: 4.96 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeInTheDocument();
  });

  it('appears when a press stops the return flight between two views', async () => {
    await renderReady(resolved('c1', 'map-a', 3));
    panAway();
    act(() => backButton()!.click());
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, lng: -55 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeInTheDocument();
  });

  it('stays hidden through an editor reset in the middle of a flight, and settles at its end', async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} resetKey={0} />);
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} resetKey={1} />);

    // The stopped flight ends while its replacement runs.
    fakeMap.view = { ...fakeMap.view, zoom: 4.5 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, zoom: 6 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeNull();
  });

  it('leaves a camera saved during a flight to be compared when the flight ends', async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
    fakeMap.view = { ...fakeMap.view, zoom: 4.5 };
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 7)} />);
    expect(backButton()).toBeNull();

    fakeMap.view = { ...fakeMap.view, zoom: 6 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeInTheDocument();
  });

  it('appears for a compass drag, whose moveend carries no originalEvent', async () => {
    await renderReady(resolved('c1', 'map-a', 3));
    fakeMap.view = { ...fakeMap.view, bearing: 40 };
    act(() => fakeMap.emit('moveend', {}));
    expect(backButton()).toBeInTheDocument();
  });

  it('settles when the saved camera for the chapter becomes the map view, and ignores the previous chapter', async () => {
    const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
    panAway();
    expect(backButton()).toBeInTheDocument();

    // "Use current view": the same chapter, with the camera the map is at.
    const here = resolved('c1', 'map-a', 3);
    here.scene.camera = { center: [-40, 25], zoom: 3, bearing: 0, pitch: 0 };
    rerender(<StoryMapPane resolved={here} />);
    expect(backButton()).toBeNull();

    // Another chapter plays its own move, so the old comparison is dropped.
    panAway();
    fakeMap.view = { ...fakeMap.view, lng: -10 };
    act(() => fakeMap.emit('moveend', READER_MOVE));
    expect(backButton()).toBeInTheDocument();
    rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
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

describe('crossfade to a map loaded ahead', () => {
  const paneSlots = () => [...document.querySelectorAll<HTMLElement>('#map-viewport > [data-slot]')];
  const slot = (role: string) => paneSlots().find((el) => el.dataset.slot === role);
  const mapCount = () => screen.queryAllByTestId('viewer-map').length;
  const loading = () => screen.queryByText('Loading map…');

  /** Renders the chapter on map-a with map-b next, and brings both maps up. */
  async function renderAhead(nextScene: ResolvedScene = resolved('c2', 'map-b', 7), current = resolved('c1', 'map-a', 3)) {
    viewAt(-70, 25, 3);
    const view = render(<StoryMapPane resolved={current} next={nextScene} />);
    await screen.findAllByTestId('viewer-map');
    act(() => viewer.byBasemap.positron.onMapReady!(fakeMap as never));
    return view;
  }

  const readyNext = (id: 'map-b' | 'map-c', basemap: string) =>
    act(() => viewer.byBasemap[basemap].onMapReady!(nextMaps[id] as never));

  it('mounts the next map hidden, inert and at its own camera, only when it is on another map', async () => {
    await renderAhead();
    expect(mapCount()).toBe(2);
    const standby = slot('standby')!;
    expect(standby).toHaveAttribute('inert');
    expect(standby).toHaveAttribute('aria-hidden', 'true');
    expect(standby.style.opacity).toBe('0');
    expect(viewer.byBasemap.voyager.initialViewState).toMatchObject({ zoom: 7, center_lng: -70 });
    expect(slot('active')).not.toHaveAttribute('inert');
  });

  it('mounts no second map when there is no next map to load', async () => {
    render(<StoryMapPane resolved={resolved('c1', 'map-a', 3)} next={null} />);
    await screen.findByTestId('viewer-map');
    expect(mapCount()).toBe(1);
  });

  it('mounts no second map when the next scene is on the same map', async () => {
    render(<StoryMapPane resolved={resolved('c1', 'map-a', 3)} next={resolved('c2', 'map-a', 6)} />);
    await screen.findByTestId('viewer-map');
    expect(mapCount()).toBe(1);
  });

  it('fades the next map in over the current one, which moves to the new view, and drops the old after the fade', async () => {
    const { rerender } = await renderAhead();
    readyNext('map-b', 'voyager');
    const incoming = slot('standby')!;
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} next={null} />);

    expect(viewer.mounts).toBe(2);
    expect(mapCount()).toBe(2);
    expect(slot('active')).toBe(incoming);
    expect(incoming.style.opacity).toBe('1');
    expect(incoming.style.transitionDuration).toBe('400ms');
    expect(slot('outgoing')).toBeInTheDocument();
    expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 7, center: [-70, 25] }));
    expect(nextMaps['map-b'].flyTo).not.toHaveBeenCalled();
    expect(loading()).toBeNull();

    fireEvent.transitionEnd(incoming);
    expect(slot('outgoing')).toBeUndefined();
    expect(mapCount()).toBe(1);
  });

  it('keeps both slot nodes where they are when the map changes, so the fade has a start value', async () => {
    const { rerender, container } = await renderAhead();
    readyNext('map-b', 'voyager');
    const before = paneSlots();
    const watcher = new MutationObserver(() => {});
    watcher.observe(container.querySelector('#map-viewport')!, { childList: true });
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} next={null} />);
    const moves = watcher.takeRecords();
    watcher.disconnect();
    expect(moves).toHaveLength(0);
    expect(paneSlots()).toEqual([before[0], before[1]]);
    expect(paneSlots().map((el) => el.dataset.slot)).toEqual(['outgoing', 'active']);
  });

  it('drops the old map when the fade timer runs out without a transition event', async () => {
    const { rerender } = await renderAhead();
    readyNext('map-b', 'voyager');
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} next={null} />);
    expect(slot('outgoing')).toBeInTheDocument();
    await waitFor(() => expect(slot('outgoing')).toBeUndefined(), { timeout: 2000 });
  });

  it('cuts without moving the old map, only fading', async () => {
    const { rerender } = await renderAhead(resolved('c2', 'map-b', 7, {}, 'cut'));
    readyNext('map-b', 'voyager');
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7, {}, 'cut')} next={null} />);
    expect(fakeMap.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 7, duration: 0 }));
    expect(fakeMap.flyTo).not.toHaveBeenCalled();
    expect(slot('active')!.style.transitionDuration).toBe('400ms');
  });

  it('swaps without a fade or a move under reduced motion', async () => {
    mockReducedMotion(true);
    const { rerender } = await renderAhead();
    readyNext('map-b', 'voyager');
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} next={null} />);
    expect(slot('outgoing')).toBeUndefined();
    expect(mapCount()).toBe(1);
    expect(slot('active')!.style.transitionDuration).toBe('0ms');
    expect(fakeMap.flyTo).not.toHaveBeenCalled();
    expect(fakeMap.easeTo).not.toHaveBeenCalled();
  });

  it('shows the loading state when the next map is not ready yet', async () => {
    const { rerender } = await renderAhead();
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} next={null} />);
    expect(slot('outgoing')).toBeUndefined();
    expect(mapCount()).toBe(1);
    expect(loading()).toBeInTheDocument();

    readyNext('map-b', 'voyager');
    expect(loading()).toBeNull();
  });

  it('never has more than two maps across a walk through three maps', async () => {
    const seen: number[] = [];
    const count = () => seen.push(mapCount());
    const { rerender } = await renderAhead(resolved('c2', 'map-b', 7));
    count();
    readyNext('map-b', 'voyager');
    rerender(<StoryMapPane resolved={resolved('c2', 'map-b', 7)} next={resolved('c3', 'map-c', 9)} />);
    count();
    // The third map waits for the fade to end.
    expect(viewer.byBasemap['dark-matter']).toBeUndefined();
    fireEvent.transitionEnd(slot('active')!);
    await screen.findAllByTestId('viewer-map');
    count();
    expect(slot('standby')).toBeInTheDocument();
    act(() => viewer.byBasemap['dark-matter'].onMapReady!(nextMaps['map-c'] as never));
    rerender(<StoryMapPane resolved={resolved('c3', 'map-c', 9)} next={null} />);
    count();
    fireEvent.transitionEnd(slot('active')!);
    count();
    expect(seen).toEqual([2, 2, 2, 2, 1]);
  });

  it('points the handle at the visible map', async () => {
    const ref = createRef<StoryMapPaneHandle>();
    viewAt(-70, 25, 3);
    const { rerender } = render(<StoryMapPane ref={ref} resolved={resolved('c1', 'map-a', 3)} next={resolved('c2', 'map-b', 7)} />);
    await screen.findAllByTestId('viewer-map');
    act(() => viewer.byBasemap.positron.onMapReady!(fakeMap as never));
    readyNext('map-b', 'voyager');
    nextMaps['map-b'].view = { lng: 10, lat: 20, zoom: 7, bearing: 0, pitch: 0 };
    rerender(<StoryMapPane ref={ref} resolved={resolved('c2', 'map-b', 7)} next={null} />);
    expect(ref.current?.getView()).toMatchObject({ center: [10, 20] });
  });
});
