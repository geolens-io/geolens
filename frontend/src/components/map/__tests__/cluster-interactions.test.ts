import {
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
});
