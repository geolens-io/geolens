// The ViewerMap visibility-only effect dropped layer toggles issued
// while the basemap style was transitioning — a plain early-return on
// !isStyleLoaded() with no idle retry, and prevVisibleRef left unadvanced. The
// fix registers map.once('idle', applyVisibilityDiff) so the toggle re-applies
// once the map settles (mirrors the BuilderMap idle-retry pattern).
import { LAYER, viewerHarness } from '@/test/viewer-map-harness';
import { act, render, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import type { SharedLayerResponse } from '@/types/api';

const { mapState, terrainState, tileConfigState, tokenState } = viewerHarness;

function renderViewer(visibleLayers: Set<string>) {
  return render(
    <ViewerMap
      layers={[LAYER]}
      basemapStyle="openfreemap-positron"
      basemapConfig={null}
      showBasemapLabels={true}
      terrainConfig={null}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={visibleLayers}
    />,
  );
}

describe('ViewerMap visibility idle-retry (BUG-037)', () => {
  beforeEach(() => {
    mapState.reset();
    tileConfigState.data = {
      cdn_base_url: null,
      mvt_source_layer_prefix: 'data',
    };
    tokenState.data = new Map([['dataset-pt', { kind: 'vector', token: 't' }]]);
    terrainState.ready = false;
    terrainState.expected = false;
  });

  it('does not run visibility sync for an unresolved tenant source-layer prefix', async () => {
    tileConfigState.data = {
      cdn_base_url: null,
      mvt_source_layer_prefix: null,
    };
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);

    renderViewer(new Set(['pt-layer']));

    await waitFor(() => expect(mapState.fakeMap.setTransformRequest).toHaveBeenCalled());
    expect(mapState.fakeMap.setLayoutProperty).not.toHaveBeenCalled();
  });

  it("applies the other layers' toggles when an adapter cannot read one layer's style", async () => {
    const brokenHeatmap = {
      ...LAYER,
      id: 'heat-layer',
      style_config: { render_mode: 'heatmap', builder: { heatmapRamp: 42 } },
    } as unknown as SharedLayerResponse;
    const viewer = (visibleLayers: Set<string>) => (
      <ViewerMap
        layers={[brokenHeatmap, LAYER]}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={visibleLayers}
      />
    );
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    const { rerender } = render(viewer(new Set(['heat-layer', 'pt-layer'])));
    await waitFor(() => expect(mapState.fakeMap.isStyleLoaded).toHaveBeenCalled());
    mapState.fakeMap.setLayoutProperty.mockClear();

    rerender(viewer(new Set()));

    await waitFor(() => {
      expect(mapState.fakeMap.setLayoutProperty).toHaveBeenCalledWith('viewer-layer-pt-layer', 'visibility', 'none');
    });
  });

  it('registers an idle retry when a toggle arrives while the style is transitioning', async () => {
    // Initial render with the style LOADED so the visibility effect advances
    // prevVisibleRef to {pt-layer} (the layer is shown and the baseline is set).
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    const { rerender } = renderViewer(new Set(['pt-layer']));
    await waitFor(() => expect(mapState.fakeMap.isStyleLoaded).toHaveBeenCalled());

    // Now a basemap-style swap is in flight: the style is transitioning.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(false);
    mapState.fakeMap.once.mockClear();
    mapState.fakeMap.setLayoutProperty.mockClear();

    // Toggle the layer OFF while the style is mid-transition (isStyleLoaded=false).
    rerender(
      <ViewerMap
        layers={[LAYER]}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set()}
      />,
    );

    // The dedicated visibility effect must have scheduled an idle retry rather
    // than silently dropping the toggle.
    await waitFor(() => {
      expect(mapState.fakeMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });

    // Now the style settles → the queued diff applies and hides the layer.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    mapState.fakeMap.emit('idle');

    expect(mapState.fakeMap.setLayoutProperty).toHaveBeenCalledWith(
      'viewer-layer-pt-layer',
      'visibility',
      'none',
    );
  });

  it('does not reuse the initial basemap idle for an asynchronously added data layer', async () => {
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    tokenState.data = new Map();

    const { rerender, getByRole } = renderViewer(new Set(['pt-layer']));
    const mapRegion = getByRole('region', { name: 'Map viewer' });

    await waitFor(() => expect(mapState.fakeMap.setTransformRequest).toHaveBeenCalled());
    act(() => { mapState.fakeMap.emit('idle'); });

    // The basemap has settled, but the data-layer token has not arrived and no
    // ViewerMap-owned source/layer has been composed yet.
    expect(mapRegion).toHaveAttribute('data-tiles-loaded', 'false');
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    tokenState.data = new Map([['dataset-pt', { kind: 'vector', token: 'late' }]]);
    rerender(
      <ViewerMap
        layers={[LAYER]}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['pt-layer'])}
      />,
    );

    await waitFor(() => expect(mapState.fakeMap.addSource).toHaveBeenCalled());
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    // Only an idle observed after the current composition was attached can
    // certify it. Later source activity re-arms the same contract.
    act(() => { mapState.fakeMap.emit('idle'); });
    await waitFor(() => expect(mapRegion).toHaveAttribute('data-map-ready', 'true'));
    expect(mapRegion).toHaveAttribute('data-tiles-loaded', 'true');

    act(() => { mapState.fakeMap.emit('dataloading'); });
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');
    expect(mapRegion).toHaveAttribute('data-tiles-loaded', 'false');

    act(() => { mapState.fakeMap.emit('idle'); });
    await waitFor(() => expect(mapRegion).toHaveAttribute('data-map-ready', 'true'));
  });

  it('settles a terrain-only composition after the terrain source load cycle', async () => {
    const terrainLayer: SharedLayerResponse = {
      ...LAYER,
      id: 'terrain-layer',
      dataset_id: 'dataset-dem',
      table_name: 'terrain_dem',
      geometry_type: null,
      is_dem: true,
      layer_type: 'raster_geolens',
      style_config: { render_mode: 'terrain' },
    };
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    tokenState.data = new Map([['dataset-dem', { kind: 'raster' as const, tile_url: '/dem/{z}/{x}/{y}.png' }]]);
    terrainState.expected = true;

    const { rerender, getByRole } = render(
      <ViewerMap
        layers={[terrainLayer]}
        basemapStyle="openfreemap-positron"
        terrainConfig={{ enabled: true, source_dataset_id: 'dataset-dem', exaggeration: 1 }}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['terrain-layer'])}
      />,
    );
    const mapRegion = getByRole('region', { name: 'Map viewer' });

    await waitFor(() => expect(mapState.fakeMap.setTransformRequest).toHaveBeenCalled());
    act(() => { mapState.fakeMap.emit('idle'); });
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    // The terrain hook owns this source outside syncMapComposition. Its data
    // activity re-arms readiness, and terrainReady alone cannot bypass idle.
    act(() => { mapState.fakeMap.emit('dataloading'); });
    terrainState.ready = true;
    rerender(
      <ViewerMap
        layers={[terrainLayer]}
        basemapStyle="openfreemap-positron"
        terrainConfig={{ enabled: true, source_dataset_id: 'dataset-dem', exaggeration: 1 }}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['terrain-layer'])}
      />,
    );
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    act(() => { mapState.fakeMap.emit('idle'); });
    await waitFor(() => expect(mapRegion).toHaveAttribute('data-map-ready', 'true'));
  });
});
