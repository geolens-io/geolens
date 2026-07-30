import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FeatureInfo } from './FeaturePopup';
import { clusterCircleLayerId, clusterCountLayerId } from '@/components/builder/layer-adapters/cluster-adapter';
import type { ClusterSourceStrategyKind } from '@/components/builder/cluster-source';
import { motionDuration } from '@/lib/reduced-motion';
import i18n from '@/i18n/i18n';

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
  // fix(#438): I18N-02 — these strings render in the cluster popup ('source'
  // field); they were hardcoded English.
  if (kind === 'server-tile') return i18n.t('builder:cluster.sourceServerTile');
  if (kind === 'bounded-geojson') return i18n.t('builder:cluster.sourceBoundedGeojson');
  return i18n.t('builder:cluster.sourceFallback');
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
    // fix(#438): I18N-02 — was `Cluster: N feature(s)` with manual English
    // pluralization; now an i18next plural key.
    title: i18n.t('builder:cluster.popupTitle', { count, countLabel }),
    // fix(#586): only list keys actually present — the popup's
    // no-schema fallback renders configured-but-absent fields as '--', which
    // would surface a meaningless "Expansion Zoom: --" on clusters without one.
    visibleFields: ['feature_count', 'source', 'expansion_zoom', 'cluster_id']
      .filter((k) => k in aggregateProperties),
  };
}

// MapLibre's own zoom ceiling, and the value the tile server clamps
// `expansion_zoom` to (see `backend/app/processing/tiles/service.py`). Named so
// the ceiling case below is greppable instead of a repeated literal.
export const CLUSTER_ZOOM_CEILING = 22;

function clampClusterZoom(zoom: number) {
  return Math.min(Math.max(zoom, 0), CLUSTER_ZOOM_CEILING);
}

async function clusterExpansionZoom(
  map: Pick<MaplibreMap, 'getSource' | 'getZoom'>,
  feature: ClusterFeatureLike,
  sourceId: string,
) {
  const properties = feature.properties ?? {};
  const explicitZoom = numericProperty(properties, 'expansion_zoom');
  if (explicitZoom != null) return clampClusterZoom(explicitZoom);

  const clusterId = numericProperty(properties, 'cluster_id');
  const source = map.getSource(sourceId) as ClusterSourceWithExpansion | undefined;
  if (clusterId != null && source?.getClusterExpansionZoom) {
    return new Promise<number>((resolve) => {
      source.getClusterExpansionZoom!(clusterId, (error, zoom) => {
        if (error || !Number.isFinite(zoom)) {
          resolve(clampClusterZoom((map.getZoom?.() ?? 0) + 2));
          return;
        }
        resolve(clampClusterZoom(zoom));
      });
    });
  }

  return clampClusterZoom((map.getZoom?.() ?? 0) + 2);
}

export async function activateClusterFeature(
  map: Pick<MaplibreMap, 'easeTo' | 'getSource' | 'getZoom'>,
  feature: ClusterFeatureLike,
  sourceId: string,
) {
  const center = clusterFeatureCoordinates(feature);
  if (!center) return false;
  const target = await clusterExpansionZoom(map, feature, sourceId);
  // fix(#893): ease to the expansion zoom only when it is deeper than where we
  // already are. Two ways it is not. At CLUSTER_ZOOM_CEILING with
  // cluster_max_zoom=22 the server's now-honest value (#882) IS the current
  // zoom. And a parent cluster tile still drawn overzoomed while its
  // replacement loads reports the shallow expansion zoom of the level it was
  // cut at, which used to ease the user BACKWARDS out of the view they were
  // zooming into. Falling back to the current zoom recentres without moving the
  // zoom — at the ceiling no zoom can split the cluster, so recentring is the
  // whole honest response, and a click can never lose ground.
  const currentZoom = map.getZoom?.() ?? 0;
  const zoom = target > currentZoom ? target : currentZoom;
  map.easeTo({
    center,
    zoom,
    // fix(#438): A11Y-08 — instant under prefers-reduced-motion.
    duration: motionDuration(500),
  });
  return true;
}
