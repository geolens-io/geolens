import { MapPin, Route, Pentagon, Hexagon, type LucideIcon } from 'lucide-react';
import type { OGCRecordResponse } from '@/types/api';

/**
 * Extract a bounding box from an OGC record's polygon geometry.
 */
export function extractBbox(feature: OGCRecordResponse): [number, number, number, number] | null {
  if (!feature.geometry || feature.geometry.type !== 'Polygon') return null;

  const coords = (feature.geometry as { type: 'Polygon'; coordinates: number[][][] }).coordinates[0];
  if (!coords || coords.length < 4) return null;

  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const [x, y] of coords) {
    if (x < minx) minx = x;
    if (y < miny) miny = y;
    if (x > maxx) maxx = x;
    if (y > maxy) maxy = y;
  }

  return [minx, miny, maxx, maxy];
}

/**
 * Compute ground-sampling distance from raster pixel resolutions.
 * Returns the minimum of the absolute x/y resolutions, or null if either is missing.
 */
export function computeRasterGsd(resX: number | null | undefined, resY: number | null | undefined): number | null {
  if (resX == null || resY == null) return null;
  return Math.min(Math.abs(resX), Math.abs(resY));
}

/** Column names that indicate elevation/height data */
const ELEVATION_COLUMN_NAMES = new Set([
  'height', 'elev', 'elevation', 'z', 'altitude', 'alt',
  'elev_ft', 'elev_m', 'height_m', 'height_ft', 'dem', 'dtm',
]);

/** Column types that are numeric (can drive fill-extrusion-height) */
const NUMERIC_COLUMN_TYPES = new Set([
  'integer', 'bigint', 'smallint', 'real', 'float', 'float4', 'float8',
  'double precision', 'numeric', 'decimal', 'number',
]);

/**
 * Find an elevation/height column in column_info.
 * Matches by exact column name (case-insensitive) AND numeric column type
 * to avoid false positives on text columns named "dem" or "dtm".
 * Returns the column name or null.
 */
export function findElevationColumn(columnInfo: { name: string; type?: string }[] | null | undefined): string | null {
  if (!columnInfo) return null;
  const col = columnInfo.find((c) => {
    if (!ELEVATION_COLUMN_NAMES.has(c.name.toLowerCase())) return false;
    // If type info is available, require it to be numeric
    if (c.type) return NUMERIC_COLUMN_TYPES.has(c.type.toLowerCase());
    // No type info — accept the name match (backward compat)
    return true;
  });
  return col?.name ?? null;
}

/**
 * Map a geometry type string to a Lucide icon component.
 */
export function geometryIcon(geomType: string | null): LucideIcon | null {
  if (!geomType) return null;
  const upper = geomType.toUpperCase();
  if (upper === 'POINT' || upper === 'MULTIPOINT') return MapPin;
  if (upper === 'LINESTRING' || upper === 'MULTILINESTRING') return Route;
  if (upper === 'POLYGON') return Pentagon;
  if (upper === 'MULTIPOLYGON') return Hexagon;
  return null;
}

/** Infer geometry type from paint keys when explicit type is null (e.g. table datasets with lat/lon). */
export function inferGeometryType(
  paint: Record<string, unknown> | undefined | null,
  geometryType: string | null | undefined,
): string | null {
  if (geometryType) return geometryType;
  if (!paint) return null;
  const keys = Object.keys(paint);
  if (keys.some((k) => k.startsWith('circle-'))) return 'POINT';
  if (keys.some((k) => k.startsWith('line-'))) return 'LINE';
  return null;
}
