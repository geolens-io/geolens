import { createRef, useEffect, type ReactNode } from 'react';
import { act, render, screen } from '@/test/test-utils';
import { StoryMapPane, type StoryMapPaneHandle } from '../StoryMapPane';
import type { ResolvedScene } from '../story-scenes';
import type { ViewerMap } from '@/components/viewer/ViewerMap';
import type { MapResponse, StoryScene } from '@/types/api';

type ViewerMapProps = React.ComponentProps<typeof ViewerMap>;

const viewer = vi.hoisted(() => ({ props: null as ViewerMapProps | null, mounts: 0 }));
const fakeMap = vi.hoisted(() => ({
  flyTo: vi.fn(),
  jumpTo: vi.fn(),
  getCenter: () => ({ lng: 199.1234567, lat: 26.9876543 }),
  getZoom: () => 6.7891234,
  getBearing: () => 10,
  getPitch: () => 20,
}));

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
};

function resolved(chapterId: string, mapId: string, zoom: number, layerVisibility: StoryScene['layer_visibility'] = {}): ResolvedScene {
  return {
    chapterId,
    scene: { map_id: mapId, camera: { center: [-70, 25], zoom, bearing: 0, pitch: 0 }, layer_visibility: layerVisibility },
  };
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
  fakeMap.flyTo.mockReset();
  fakeMap.jumpTo.mockReset();
  mockReducedMotion(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderReady(scene: ResolvedScene) {
  const view = render(<StoryMapPane resolved={scene} />);
  await screen.findByTestId('viewer-map');
  viewer.props!.onMapReady!(fakeMap as never);
  return view;
}

it('flies within the same map when the scene changes', async () => {
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
  expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 6, duration: 2000 }));
  expect(viewer.mounts).toBe(1);
});

it('jumps instead of flying under reduced motion', async () => {
  mockReducedMotion(true);
  const { rerender } = await renderReady(resolved('c1', 'map-a', 3));
  rerender(<StoryMapPane resolved={resolved('c2', 'map-a', 6)} />);
  expect(fakeMap.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 6, duration: 0 }));
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
  viewer.props!.onMapReady!(fakeMap as never);
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

  viewer.props!.onMapReady!(fakeMap as never);
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
