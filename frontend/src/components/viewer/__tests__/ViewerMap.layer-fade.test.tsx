// Layers that a visibility change turns on or off fade their paint opacity when the
// story reader asks for it, and switch at once everywhere else.
import { LAYER, viewerHarness } from '@/test/viewer-map-harness';
import { act, render, waitFor } from '@/test/test-utils';
import { syncMapComposition } from '@/components/builder/map-composition-sync';
import { toViewerSyncInput, ViewerMap } from '../ViewerMap';

const { mapState } = viewerHarness;

const LAYER_ID = 'viewer-layer-pt-layer';

function viewer(visibleLayers: Set<string>, fadeLayerChanges: boolean) {
  return (
    <ViewerMap
      layers={[LAYER]}
      basemapStyle="openfreemap-positron"
      basemapConfig={null}
      showBasemapLabels={true}
      terrainConfig={null}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={visibleLayers}
      fadeLayerChanges={fadeLayerChanges}
    />
  );
}

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion'),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

const opacityWrites = () =>
  mapState.fakeMap.setPaintProperty.mock.calls.filter(([id, property]) => id === LAYER_ID && property === 'circle-opacity');
const transitionWrites = () =>
  mapState.fakeMap.setPaintProperty.mock.calls.filter(([id, property]) => id === LAYER_ID && property === 'circle-opacity-transition');
const visibilityWrites = () =>
  mapState.fakeMap.setLayoutProperty.mock.calls.filter(([id, property]) => id === LAYER_ID && property === 'visibility');
const clearWrites = () => {
  mapState.fakeMap.setPaintProperty.mockClear();
  mapState.fakeMap.setLayoutProperty.mockClear();
};
const FAKE_TIMERS = { toFake: ['setTimeout', 'clearTimeout'] as const };

async function renderShown(fadeLayerChanges: boolean) {
  mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
  const view = render(viewer(new Set(['pt-layer']), fadeLayerChanges));
  await waitFor(() => expect(mapState.fakeMap.isStyleLoaded).toHaveBeenCalled());
  // The sync pass drew the layer visible.
  const seed = mapState.fakeMap.setLayoutProperty as unknown as (...args: unknown[]) => void;
  seed(LAYER_ID, 'visibility', 'visible');
  seed(`${LAYER_ID}-outline`, 'visibility', 'visible');
  clearWrites();
  return view;
}

describe('ViewerMap layer fades', () => {
  beforeEach(() => {
    mapState.reset();
    mockReducedMotion(false);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('fades a layer out through its own sync pass, hides it when the fade ends, then restores its opacity', async () => {
    const { rerender } = await renderShown(true);
    vi.useFakeTimers({ toFake: [...FAKE_TIMERS.toFake] });

    rerender(viewer(new Set(), true));
    expect(transitionWrites().at(-1)![2]).toEqual({ duration: 400, delay: 0 });
    expect(opacityWrites().at(-1)![2]).toBe(0);
    expect(visibilityWrites()).toHaveLength(0);

    vi.advanceTimersByTime(399);
    expect(visibilityWrites()).toHaveLength(0);

    vi.advanceTimersByTime(1);
    expect(visibilityWrites().at(-1)![2]).toBe('none');
    expect(opacityWrites().at(-1)![2]).toBe(1);
    expect(transitionWrites().at(-1)![2]).toBeUndefined();
  });

  it('fades a layer in from zero once the zero has been drawn', async () => {
    const { rerender } = await renderShown(true);
    vi.useFakeTimers({ toFake: [...FAKE_TIMERS.toFake] });
    rerender(viewer(new Set(), true));
    vi.advanceTimersByTime(400);
    clearWrites();

    rerender(viewer(new Set(['pt-layer']), true));
    expect(visibilityWrites().map(([, , value]) => value)).toEqual(['visible']);
    expect(opacityWrites().map(([, , value]) => value)).toEqual([0]);
    expect(transitionWrites().at(-1)![2]).toEqual({ duration: 0, delay: 0 });

    act(() => mapState.fakeMap.emit('render'));
    expect(transitionWrites().at(-1)![2]).toEqual({ duration: 400, delay: 0 });
    expect(opacityWrites().at(-1)![2]).toBe(1);

    vi.advanceTimersByTime(400);
    expect(transitionWrites().at(-1)![2]).toBeUndefined();
  });

  it('carries on from where a fade has reached when the layer is toggled again', async () => {
    const { rerender } = await renderShown(true);
    vi.useFakeTimers({ toFake: [...FAKE_TIMERS.toFake] });
    rerender(viewer(new Set(), true));
    vi.advanceTimersByTime(200);
    clearWrites();

    rerender(viewer(new Set(['pt-layer']), true));
    expect(opacityWrites().map(([, , value]) => value)).toEqual([1]);
    expect(transitionWrites().at(-1)![2]).toEqual({ duration: 400, delay: 0 });

    // The abandoned fade-out never hides the layer.
    vi.advanceTimersByTime(1000);
    expect(visibilityWrites().map(([, , value]) => value)).toEqual([]);
  });

  it('fades a polygon layer, writing no visibility until the fade ends, when a chapter brings new layer objects and a full sync pass', async () => {
    // The full sync pass writes every layer's visibility, and leaves the style dirty until the map is idle.
    const original = vi.mocked(syncMapComposition).getMockImplementation();
    const actual = await vi.importActual<typeof import('@/components/builder/map-composition-sync')>('@/components/builder/map-composition-sync');
    vi.mocked(syncMapComposition).mockImplementation((args) => {
      actual.syncMapComposition(args);
      mapState.fakeMap.isStyleLoaded.mockReturnValue(false);
    });
    try {
      const { rerender } = await renderShown(true);
      vi.useFakeTimers({ toFake: [...FAKE_TIMERS.toFake] });

      rerender(
        <ViewerMap
          layers={[{ ...LAYER, geometry_type: 'POLYGON', paint: { 'fill-color': '#336699' } }]}
          basemapStyle="openfreemap-positron"
          initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
          visibleLayers={new Set()}
          fadeLayerChanges
        />,
      );
      // The fading layer is never hidden by the pass, so it writes no visibility at all.
      const writes = () => mapState.fakeMap.setLayoutProperty.mock.calls.filter(([, property]) => property === 'visibility');
      expect(writes()).toHaveLength(0);
      expect(mapState.fakeMap.setPaintProperty).toHaveBeenCalledWith(LAYER_ID, 'fill-layer-opacity-transition', { duration: 400, delay: 0 });

      vi.advanceTimersByTime(400);
      // Every map layer of the polygon is hidden when the fade ends, and none is shown again.
      expect(writes().map(([, , value]) => value)).toEqual(expect.arrayContaining(['none']));
      expect(writes().every(([, , value]) => value === 'none')).toBe(true);
    } finally {
      vi.mocked(syncMapComposition).mockImplementation(original!);
    }
  });

  it('switches at once when the fade is not asked for', async () => {
    const { rerender } = await renderShown(false);

    rerender(viewer(new Set(), false));
    expect(visibilityWrites().at(-1)![2]).toBe('none');
    expect(opacityWrites()).toHaveLength(0);
  });

  it('switches at once under reduced motion', async () => {
    mockReducedMotion(true);
    const { rerender } = await renderShown(true);

    rerender(viewer(new Set(), true));
    expect(visibilityWrites().at(-1)![2]).toBe('none');
    expect(opacityWrites()).toHaveLength(0);
  });

  it('does not fade the layers the map opens with', async () => {
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    render(viewer(new Set(['pt-layer']), true));
    await waitFor(() => expect(mapState.fakeMap.isStyleLoaded).toHaveBeenCalled());
    expect(opacityWrites()).toHaveLength(0);
  });
});

describe('ViewerMap fading a point layer with a ring', () => {
  beforeEach(() => mapState.reset());
  afterEach(() => vi.useRealTimers());

  it('scales the configured ring opacity by the fade factor, with a transition on the ring key', async () => {
    const ringed = { ...LAYER, paint: { 'circle-color': '#2255aa', 'circle-stroke-width': 2, 'circle-stroke-opacity': 0.5 } };
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    const view = (visible: Set<string>) => (
      <ViewerMap
        layers={[ringed]}
        basemapStyle="openfreemap-positron"
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={visible}
        fadeLayerChanges
      />
    );
    const { rerender } = render(view(new Set(['pt-layer'])));
    await waitFor(() => expect(mapState.fakeMap.isStyleLoaded).toHaveBeenCalled());
    clearWrites();
    vi.useFakeTimers({ toFake: [...FAKE_TIMERS.toFake] });

    rerender(view(new Set()));
    expect(mapState.fakeMap.setPaintProperty).toHaveBeenCalledWith(LAYER_ID, 'circle-stroke-opacity-transition', { duration: 400, delay: 0 });
    const ringWrites = () => mapState.fakeMap.setPaintProperty.mock.calls.filter(([, property]) => property === 'circle-stroke-opacity');
    expect(ringWrites().at(-1)![2]).toBe(0);

    vi.advanceTimersByTime(400);
    expect(mapState.fakeMap.setPaintProperty).toHaveBeenCalledWith(LAYER_ID, 'circle-stroke-opacity-transition', undefined);
    expect(ringWrites().at(-1)![2]).toBe(0.5);
  });
});

describe('toViewerSyncInput during a fade', () => {
  const labelled = { ...LAYER, opacity: 0.5, label_config: { column: 'name', textOpacity: 0.8 } };

  it('draws a fading layer visible, its opacity and label opacity scaled by the fade factor', () => {
    const input = toViewerSyncInput(labelled, 'k', new Set(), new Map([['k', { factor: 0 }]]));
    expect(input).toMatchObject({ visible: true, opacity: 0, label_config: { textOpacity: 0 } });
  });

  it('leaves a layer that is not fading as it was', () => {
    expect(toViewerSyncInput(labelled, 'k', new Set(), new Map())).toMatchObject({
      visible: false,
      opacity: 0.5,
      label_config: { textOpacity: 0.8 },
    });
  });

  it('leaves a label opacity that is a zoom expression alone', () => {
    const expression = { ...labelled, label_config: { column: 'name', textOpacity: { stops: [[5, 0], [8, 1]] } } };
    const input = toViewerSyncInput(expression as never, 'k', new Set(), new Map([['k', { factor: 0 }]]));
    expect(input.label_config).toBe(expression.label_config);
  });
});
