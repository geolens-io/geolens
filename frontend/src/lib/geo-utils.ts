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
