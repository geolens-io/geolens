import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBookmark } from '@/types/api';
import { deepEqual } from '@/lib/deep-equal';
import { motionDuration } from '@/lib/reduced-motion';

export const MAX_BOOKMARKS = 100;
export const MAX_BOOKMARK_NAME = 120;

const TILE_SIZE = 512;
const MERCATOR_MAX_LAT = 85.051129;

const round6 = (n: number) => Math.round(n * 1e6) / 1e6;

function wrapLng(lng: number): number {
  if (lng >= -180 && lng <= 180) return lng;
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

function lngToX(lng: number, worldSize: number): number {
  return ((lng + 180) / 360) * worldSize;
}

function latToY(lat: number, worldSize: number): number {
  const clamped = Math.max(-MERCATOR_MAX_LAT, Math.min(MERCATOR_MAX_LAT, lat));
  const rad = (clamped * Math.PI) / 180;
  return (0.5 - Math.log(Math.tan(Math.PI / 4 + rad / 2)) / (2 * Math.PI)) * worldSize;
}

function yToLat(y: number, worldSize: number): number {
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / worldSize))) * 180) / Math.PI;
  return Math.max(-MERCATOR_MAX_LAT, Math.min(MERCATOR_MAX_LAT, lat));
}

interface ExtentView {
  center: { lng: number; lat: number };
  zoom: number;
  width: number;
  height: number;
  bearing?: number;
  /** Grows or shrinks the box about its center; see `bookmarkFromMap`. */
  scale?: number;
}

/**
 * The [west, south, east, north] box that `goToBookmark` fits back to the
 * same camera. It is computed from the viewport in Web Mercator pixels
 * rather than `map.getBounds()`, which returns the enlarged box of a rotated
 * or tilted view. `fitBounds` with a bearing rotates the box before fitting,
 * which needs more room than the box itself, so a rotated view's box is
 * shrunk about its center by the factor that makes the fit land on the same zoom.
 */
export function extentOfView({ center, zoom, width, height, bearing = 0, scale = 1 }: ExtentView): [number, number, number, number] {
  const worldSize = TILE_SIZE * 2 ** zoom;
  const angle = (bearing * Math.PI) / 180;
  const cos = Math.abs(Math.cos(angle));
  const sin = Math.abs(Math.sin(angle));
  const k = Math.min(width / (width * cos + height * sin), height / (width * sin + height * cos));
  const halfW = (width * k * scale) / 2;
  const halfH = (height * k * scale) / 2;

  const cx = lngToX(center.lng, worldSize);
  const cy = latToY(center.lat, worldSize);
  const south = round6(yToLat(cy + halfH, worldSize));
  const north = round6(yToLat(cy - halfH, worldSize));
  if (halfW * 2 >= worldSize) return [-180, south, 180, north];

  const west = round6(wrapLng(((cx - halfW) / worldSize) * 360 - 180));
  const east = round6(wrapLng(((cx + halfW) / worldSize) * 360 - 180));
  return [west, south, east, north];
}

/**
 * Whether two lists hold the same bookmarks. The server trims and NFC-normalizes
 * a name and answers an unset bearing or pitch as null, so a list as the
 * builder made it and the same list read back are compared in that form.
 */
export function sameBookmarks(a: readonly MapBookmark[], b: readonly MapBookmark[]): boolean {
  const stored = (list: readonly MapBookmark[]) =>
    list.map((item) => ({
      name: item.name.trim().normalize('NFC'),
      extent: item.extent,
      bearing: item.bearing ?? null,
      pitch: item.pitch ?? null,
    }));
  return deepEqual(stored(a), stored(b));
}

export function bookmarkFromMap(map: MaplibreMap, name: string): MapBookmark {
  const container = map.getContainer();
  const bearing = round6(map.getBearing());
  const pitch = round6(map.getPitch());
  const zoom = map.getZoom();
  const view = {
    center: map.getCenter(),
    zoom,
    width: container.clientWidth,
    height: container.clientHeight,
    bearing,
  };
  // The box is exact on a flat Mercator map. A globe fits a box its own way,
  // so the map is asked where the box would land and the box is resized until
  // that is this zoom.
  let scale = 1;
  let extent = extentOfView(view);
  for (let pass = 0; pass < 6; pass++) {
    const fit = map.cameraForBounds(fitCorners(extent), { bearing, padding: 0 });
    const off = (fit?.zoom ?? zoom) - zoom;
    if (!Number.isFinite(off) || Math.abs(off) < 0.002) break;
    scale *= 2 ** off;
    extent = extentOfView({ ...view, scale });
  }
  return {
    name,
    extent,
    ...(bearing !== 0 ? { bearing } : {}),
    ...(pitch !== 0 ? { pitch } : {}),
  };
}

/** The corners `fitBounds` takes; an area across the antimeridian runs east past 180. */
function fitCorners(extent: readonly number[]): [[number, number], [number, number]] {
  const [west, south, east, north] = extent;
  return [
    [west, south],
    [east < west ? east + 360 : east, north],
  ];
}

export function goToBookmark(map: MaplibreMap, bookmark: MapBookmark): void {
  const [west, south, east, north] = bookmark.extent;
  map.fitBounds(fitCorners(bookmark.extent), {
    bearing: bookmark.bearing ?? 0,
    pitch: bookmark.pitch ?? 0,
    padding: 0,
    // An area with no width or height would otherwise fit at the map's deepest zoom.
    ...(west === east || south === north ? { maxZoom: 16 } : {}),
    duration: motionDuration(800),
  });
}
