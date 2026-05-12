import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FeatureInfo } from './FeaturePopup';
import { clusterCircleLayerId, clusterCountLayerId } from '@/components/builder/layer-adapters/cluster-adapter';
import type { ClusterSourceStrategyKind } from '@/components/builder/cluster-source';

type ClusterFeatureLike = {
  layer?: { id?: string };
  properties?: Record<string, unknown> | null;
  geometry?: {
    type?: string;
    coordinates?: unknown;
  } | null;
};

type ClusterSourceWithExpansion = {
  getClusterExpansionZoom?: (
    clusterId: number,
    callback: (error: Error | null, zoom: number) => void,
  ) => void;
};

export function clusterInteractiveLayerIds(primaryLayerId: string) {
  return [clusterCircleLayerId(primaryLayerId), clusterCountLayerId(primaryLayerId), primaryLayerId];
}

function numericProperty(properties: Record<string, unknown>, key: string) {
  const value = properties[key];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function isClusterFeature(feature: ClusterFeatureLike) {
  const properties = feature.properties ?? {};
  return numericProperty(properties, 'point_count') != null || properties.cluster === true;
}

export function clusterFeatureCoordinates(feature: ClusterFeatureLike): [number, number] | null {
  const coordinates = feature.geometry?.coordinates;
  if (
    Array.isArray(coordinates)
    && coordinates.length >= 2
    && typeof coordinates[0] === 'number'
    && typeof coordinates[1] === 'number'
    && Number.isFinite(coordinates[0])
    && Number.isFinite(coordinates[1])
  ) {
    return [coordinates[0], coordinates[1]];
  }
  return null;
}

function sourceLabel(kind: ClusterSourceStrategyKind) {
  if (kind === 'server-tile') return 'Server-side cluster tile';
  if (kind === 'bounded-geojson') return 'Bounded GeoJSON cluster';
  return 'Cluster fallback';
}

export function clusterAggregateFeatureInfo(
  feature: ClusterFeatureLike,
  options: {
    layerName: string;
    sourceKind: ClusterSourceStrategyKind;
    locale?: string;
  },
): FeatureInfo {
  const properties = feature.properties ?? {};
  const count = numericProperty(properties, 'point_count') ?? 0;
  const expansionZoom = numericProperty(properties, 'expansion_zoom');
  const clusterId = properties.cluster_id;
  const aggregateProperties: Record<string, unknown> = {
    feature_count: count,
    source: sourceLabel(options.sourceKind),
  };
  if (expansionZoom != null) aggregateProperties.expansion_zoom = expansionZoom;
  if (clusterId !== undefined && clusterId !== null) aggregateProperties.cluster_id = clusterId;

  const countLabel = count.toLocaleString(options.locale);
  return {
    properties: aggregateProperties,
    layerName: options.layerName,
    title: `Cluster: ${countLabel} feature${count === 1 ? '' : 's'}`,
    visibleFields: ['feature_count', 'source', 'expansion_zoom', 'cluster_id'],
  };
}

async function clusterExpansionZoom(
  map: Pick<MaplibreMap, 'getSource' | 'getZoom'>,
  feature: ClusterFeatureLike,
  sourceId: string,
) {
  const properties = feature.properties ?? {};
  const explicitZoom = numericProperty(properties, 'expansion_zoom');
  if (explicitZoom != null) return Math.min(Math.max(explicitZoom, 0), 22);

  const clusterId = numericProperty(properties, 'cluster_id');
  const source = map.getSource(sourceId) as ClusterSourceWithExpansion | undefined;
  if (clusterId != null && source?.getClusterExpansionZoom) {
    return new Promise<number>((resolve) => {
      source.getClusterExpansionZoom!(clusterId, (error, zoom) => {
        if (error || !Number.isFinite(zoom)) {
          resolve(Math.min((map.getZoom?.() ?? 0) + 2, 22));
          return;
        }
        resolve(Math.min(Math.max(zoom, 0), 22));
      });
    });
  }

  return Math.min((map.getZoom?.() ?? 0) + 2, 22);
}

export async function activateClusterFeature(
  map: Pick<MaplibreMap, 'easeTo' | 'getSource' | 'getZoom'>,
  feature: ClusterFeatureLike,
  sourceId: string,
) {
  const center = clusterFeatureCoordinates(feature);
  if (!center) return false;
  const zoom = await clusterExpansionZoom(map, feature, sourceId);
  map.easeTo({
    center,
    zoom,
    duration: 500,
  });
  return true;
}
