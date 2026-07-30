import {
  CLUSTER_ZOOM_CEILING,
  activateClusterFeature,
  clusterAggregateFeatureInfo,
  clusterFeatureCoordinates,
  clusterInteractiveLayerIds,
  isClusterFeature,
} from '../cluster-interactions';

describe('cluster interactions', () => {
  it('recognizes cluster features and companion layer ids', () => {
    expect(clusterInteractiveLayerIds('layer-stops')).toEqual([
      'layer-stops-cluster',
      'layer-stops-cluster-count',
      'layer-stops',
    ]);
    expect(isClusterFeature({ properties: { point_count: 123 } })).toBe(true);
    expect(isClusterFeature({ properties: { cluster: true } })).toBe(true);
    expect(isClusterFeature({ properties: { name: 'Stop A' } })).toBe(false);
  });

  it('builds aggregate popup information from cluster properties only', () => {
    const feature = {
      properties: {
        point_count: 1200,
        point_count_abbreviated: '1.2k',
        cluster_id: '8:44:91:3',
        expansion_zoom: 11,
      },
    };

    expect(clusterAggregateFeatureInfo(feature, {
      layerName: 'Stops',
      sourceKind: 'server-tile',
      locale: 'en-US',
    })).toMatchObject({
      layerName: 'Stops',
      title: 'Cluster: 1,200 features',
      properties: {
        feature_count: 1200,
        source: 'Server-side cluster tile',
        expansion_zoom: 11,
        cluster_id: '8:44:91:3',
      },
      visibleFields: ['feature_count', 'source', 'expansion_zoom', 'cluster_id'],
    });
  });

  it('fix(#584): omits absent optional keys from visibleFields so the popup never renders them as "--"', () => {
    const feature = {
      properties: { point_count: 42 },
      geometry: { type: 'Point', coordinates: [0, 0] },
    };
    expect(clusterAggregateFeatureInfo(feature, {
      layerName: 'Stops',
      sourceKind: 'server-tile',
      locale: 'en-US',
    }).visibleFields).toEqual(['feature_count', 'source']);
  });

  it('zooms to server-provided expansion zoom for MVT clusters', async () => {
    const map = {
      getSource: vi.fn(),
      getZoom: vi.fn(() => 5),
      easeTo: vi.fn(),
    };
    const feature = {
      properties: { point_count: 500, expansion_zoom: 9 },
      geometry: { type: 'Point', coordinates: [-73.9, 40.7] },
    };

    await expect(activateClusterFeature(map as never, feature, 'source-stops')).resolves.toBe(true);

    expect(map.easeTo).toHaveBeenCalledWith({
      center: [-73.9, 40.7],
      zoom: 9,
      duration: 500,
    });
    expect(clusterFeatureCoordinates(feature)).toEqual([-73.9, 40.7]);
  });

  it('uses GeoJSON source expansion zoom when available', async () => {
    const getClusterExpansionZoom = vi.fn((_clusterId: number, callback: (error: Error | null, zoom: number) => void) => {
      callback(null, 12);
    });
    const map = {
      getSource: vi.fn(() => ({ getClusterExpansionZoom })),
      getZoom: vi.fn(() => 5),
      easeTo: vi.fn(),
    };
    const feature = {
      properties: { point_count: 32, cluster_id: 4 },
      geometry: { type: 'Point', coordinates: [-72, 41] },
    };

    await activateClusterFeature(map as never, feature, 'source-stops');

    expect(getClusterExpansionZoom).toHaveBeenCalledWith(4, expect.any(Function));
    expect(map.easeTo).toHaveBeenCalledWith(expect.objectContaining({
      center: [-72, 41],
      zoom: 12,
    }));
  });

  it('fix(#893): recentres without zooming when expansion zoom is already the current zoom', async () => {
    // z22 with cluster_max_zoom=22 clamps expansion_zoom to the zoom the
    // cluster is drawn at, and the map is at MapLibre's own ceiling, so no
    // zoom can split it. Centring is the whole available response.
    const map = {
      getSource: vi.fn(),
      getZoom: vi.fn(() => CLUSTER_ZOOM_CEILING),
      easeTo: vi.fn(),
    };
    const feature = {
      properties: { point_count: 7, expansion_zoom: CLUSTER_ZOOM_CEILING },
      geometry: { type: 'Point', coordinates: [178.4, -18.1] },
    };

    await expect(activateClusterFeature(map as never, feature, 'source-stops')).resolves.toBe(true);

    expect(map.easeTo).toHaveBeenCalledWith({
      center: [178.4, -18.1],
      zoom: CLUSTER_ZOOM_CEILING,
      duration: 500,
    });
  });

  it('fix(#893): never eases backwards when a stale parent tile reports a shallower expansion zoom', async () => {
    // An overzoomed parent cluster tile still drawn while its replacement loads
    // carries the expansion zoom of the level it was cut at. Honouring it would
    // throw the user out of the view they were zooming into.
    const map = {
      getSource: vi.fn(),
      getZoom: vi.fn(() => 20),
      easeTo: vi.fn(),
    };
    const feature = {
      properties: { point_count: 90, expansion_zoom: 15 },
      geometry: { type: 'Point', coordinates: [-73.9, 40.7] },
    };

    await activateClusterFeature(map as never, feature, 'source-stops');

    expect(map.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 20 }));
  });

  it('fix(#893): the no-expansion-hint fallback still steps forward and stops at the ceiling', async () => {
    const deep = {
      getSource: vi.fn(() => undefined),
      getZoom: vi.fn(() => CLUSTER_ZOOM_CEILING),
      easeTo: vi.fn(),
    };
    const shallow = {
      getSource: vi.fn(() => undefined),
      getZoom: vi.fn(() => 6),
      easeTo: vi.fn(),
    };
    const feature = {
      properties: { point_count: 12 },
      geometry: { type: 'Point', coordinates: [1, 2] },
    };

    await activateClusterFeature(shallow as never, feature, 'source-stops');
    expect(shallow.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 8 }));

    await activateClusterFeature(deep as never, feature, 'source-stops');
    expect(deep.easeTo).toHaveBeenCalledWith(
      expect.objectContaining({ zoom: CLUSTER_ZOOM_CEILING }),
    );
  });

  it('fix(#893): a failed GeoJSON expansion lookup falls back without losing ground', async () => {
    const getClusterExpansionZoom = vi.fn((
      _clusterId: number,
      callback: (error: Error | null, zoom: number) => void,
    ) => {
      callback(new Error('no such cluster'), Number.NaN);
    });
    const map = {
      getSource: vi.fn(() => ({ getClusterExpansionZoom })),
      getZoom: vi.fn(() => 9),
      easeTo: vi.fn(),
    };
    const feature = {
      properties: { point_count: 32, cluster_id: 4 },
      geometry: { type: 'Point', coordinates: [-72, 41] },
    };

    await activateClusterFeature(map as never, feature, 'source-stops');

    expect(map.easeTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 11 }));
  });
});
