import type { MapGeoJSONFeature } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';
import { substitutePopupTemplate } from '@/lib/popup-template';

const EXCLUDED_PROPERTY_KEYS = new Set(['geom', 'geometry']);

export const ACCESSIBLE_FEATURE_LIMIT = 100;

export interface AccessibleMapFeature {
  key: string;
  layerName: string;
  title: string | null;
  clusterCount: number | null;
  geometryType: string;
  bounds: [west: number, south: number, east: number, north: number] | null;
  properties: [key: string, value: unknown][];
}

export interface AccessibleMapFeatureResult {
  features: AccessibleMapFeature[];
  total: number;
  truncated: boolean;
}

export type ResolveAccessibleLayer = (
  mapLayerId: string,
) => SharedLayerResponse | null;

function geometryBounds(
  geometry: GeoJSON.Geometry | null | undefined,
): AccessibleMapFeature['bounds'] {
  if (!geometry) return null;

  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;

  const visitCoordinates = (value: unknown) => {
    if (!Array.isArray(value)) return;
    if (
      value.length >= 2
      && typeof value[0] === 'number'
      && typeof value[1] === 'number'
      && Number.isFinite(value[0])
      && Number.isFinite(value[1])
    ) {
      west = Math.min(west, value[0]);
      east = Math.max(east, value[0]);
      south = Math.min(south, value[1]);
      north = Math.max(north, value[1]);
      return;
    }
    for (const item of value) visitCoordinates(item);
  };

  if (geometry.type === 'GeometryCollection') {
    for (const item of geometry.geometries) {
      const bounds = geometryBounds(item);
      if (!bounds) continue;
      west = Math.min(west, bounds[0]);
      south = Math.min(south, bounds[1]);
      east = Math.max(east, bounds[2]);
      north = Math.max(north, bounds[3]);
    }
  } else {
    visitCoordinates(geometry.coordinates);
  }

  return Number.isFinite(west) ? [west, south, east, north] : null;
}

function visibleProperties(
  properties: Record<string, unknown>,
  layer: SharedLayerResponse,
): [string, unknown][] {
  if (layer.popup_config?.enabled === false) return [];

  const entries = Object.entries(properties).filter(([key]) => (
    !key.startsWith('_') && !EXCLUDED_PROPERTY_KEYS.has(key)
  ));
  const propertyMap = new Map(entries);
  const visibleFields = layer.popup_config?.visible_fields;

  if (visibleFields !== null && visibleFields !== undefined) {
    return visibleFields
      .filter((key) => propertyMap.has(key))
      .map((key) => [key, propertyMap.get(key)] as [string, unknown]);
  }

  if (layer.column_info) {
    const allowed = new Set(layer.column_info.map((column) => column.name));
    return entries.filter(([key]) => allowed.has(key));
  }

  return entries;
}

function identityForFeature(
  feature: MapGeoJSONFeature,
  layerName: string,
): string {
  if (feature.id !== undefined) {
    return `${feature.source}:${feature.sourceLayer ?? ''}:${feature.id}`;
  }

  // Rendered vector features can be split at tile boundaries. MapLibre returns
  // one fragment per tile, so geometry/bounds cannot participate in a stable
  // fallback identity. GeoLens tiles normally expose a feature id; this
  // property fingerprint is the best available fallback for id-less sources
  // and lets us merge those fragments instead of presenting duplicate rows.
  return `${feature.source}:${feature.sourceLayer ?? ''}:${layerName}:${feature.geometry?.type ?? 'Unknown'}:${JSON.stringify(feature.properties ?? {})}`;
}

function mergeBounds(
  current: AccessibleMapFeature['bounds'],
  next: AccessibleMapFeature['bounds'],
): AccessibleMapFeature['bounds'] {
  if (!current) return next;
  if (!next) return current;
  return [
    Math.min(current[0], next[0]),
    Math.min(current[1], next[1]),
    Math.max(current[2], next[2]),
    Math.max(current[3], next[3]),
  ];
}

function clusterCount(properties: Record<string, unknown>): number | null {
  const value = properties.point_count;
  const parsed = typeof value === 'number'
    ? value
    : typeof value === 'string'
      ? Number(value)
      : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/**
 * Convert rendered GeoLens features into a bounded, de-duplicated data model
 * for the keyboard-accessible map-data panel. Basemap features never reach
 * this helper because ViewerMap queries only its managed interactive layers.
 */
export function toAccessibleMapFeatures(
  renderedFeatures: MapGeoJSONFeature[],
  resolveLayer: ResolveAccessibleLayer,
  limit = ACCESSIBLE_FEATURE_LIMIT,
): AccessibleMapFeatureResult {
  const unique = new Map<string, AccessibleMapFeature>();

  for (const feature of renderedFeatures) {
    const layer = resolveLayer(feature.layer.id);
    if (!layer) continue;

    const properties = (feature.properties ?? {}) as Record<string, unknown>;
    const layerName = layer.display_name || layer.dataset_name;
    const bounds = geometryBounds(feature.geometry);
    const identity = identityForFeature(feature, layerName);
    const existing = unique.get(identity);
    if (existing) {
      existing.bounds = mergeBounds(existing.bounds, bounds);
      existing.clusterCount = Math.max(
        existing.clusterCount ?? 0,
        clusterCount(properties) ?? 0,
      ) || null;
      continue;
    }

    unique.set(identity, {
      key: identity,
      layerName,
      title: layer.popup_config?.enabled !== false && layer.popup_config?.expression
        ? substitutePopupTemplate(layer.popup_config.expression, properties)
        : null,
      clusterCount: clusterCount(properties),
      geometryType: feature.geometry?.type ?? layer.geometry_type ?? 'Unknown',
      bounds,
      properties: visibleProperties(properties, layer),
    });
  }

  const all = [...unique.values()];
  return {
    features: all.slice(0, Math.max(0, limit)),
    total: all.length,
    truncated: all.length > limit,
  };
}
