/** Geometry for the sign-in page's decorative globe: an orthographic view of a
 *  dot lattice that keeps only the points on land. */

export const GLOBE_VIEW = { size: 800, cx: 740, cy: 400, r: 330 } as const;

/** Latitude at the middle of the view, the same for every visitor. */
export const GLOBE_TILT_LAT = 20;

/** The panel cuts the globe off at its right edge, so the globe faces this far
 *  east of the visitor's longitude to bring that longitude into the visible part. */
export const GLOBE_EAST_BIAS = 30;

const RAD = Math.PI / 180;
const LAT_STEP = 3;
const DOTS_AT_EQUATOR = 120;

// One bit per lattice point, south to north and west to east, set where the
// point's centre is on land in Natural Earth's 1:110m land polygons, release
// v5.1.2 (public domain). scripts/login-globe-land-mask.py regenerates it.
const LAND_MASK =
  '/+/9x+P/4cf/H+jh/38AEKD/PwBAAGD+AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAAQAAA' +
  'AAAAAAAAAGAAAAAAAAAgAAAADAAAAAAAAAAAAAAcAAAAAAAAAAAAAMADAAAAAADAAQAAAIALAAAAAAAEDgAAAAD4AABw' +
  'AAAA/wMAAAAA/AAA+AAAAP8HAAAAAPAHAOAHAAD4fwAAAAAA/gMA+BEAAPwfAAAAAAD/AwD4MwAA4B8AAAAAAP4PAPCf' +
  'AAAAXwAAAAAA8P8AAP4TAACAAQAAAAAA/z8AwH8AAAAAAAAAAADA/x8A4B8AADDAAQAAAADg/wcA8B8AAATgAAAAAADg' +
  '/wEA+D8AAGQRAAAAAADAfwAA+H8AAHYAAAAAAADAfwAg/P8AAMEAAAAAAADADwD4//8ABAEAAAAAAADkAgD+/2+AQEEA' +
  'AAAAAMAAAMD//wUweAgAAAAAAAcAAPz/74CDQwAAAAAAJwgA8P/fD48HAAAAAAAGAQDw/9+P3x8AAAAA4AMAAPj/Pf7/' +
  'BwAAAAAeAgDA/////x8AAAAA/gMAwJ/5//8PAAAA8P8AAPCA//8/AQAAwP8HADDU7/9/CQAA8P8BAI77/v8PAADA/w8A' +
  'tMf+/58AAOD/DwD+3///BQCA/ycA/P///wAA+N8D4P///ycg+O8BSP//PwbkHweA/P8/gv8nBOz//xv/ZyP8///3fx24' +
  '+/+EzwH4P6ByAE6AOgAB6AQABQAA';

/** Latitude rings of the lattice, south to north. They thin out toward the
 *  poles so the dots stay evenly spaced on the sphere. */
const RINGS: { lat: number; count: number }[] = [];
for (let lat = -90 + LAT_STEP / 2; lat < 90; lat += LAT_STEP) {
  RINGS.push({ lat, count: Math.max(1, Math.round(DOTS_AT_EQUATOR * Math.cos(lat * RAD))) });
}

/** Number of lattice points: the mask holds one bit for each. */
export const LATTICE_SIZE = RINGS.reduce((sum, ring) => sum + ring.count, 0);

const MASK_BYTES = Uint8Array.from(atob(LAND_MASK), (c) => c.charCodeAt(0));

/** Size of the decoded mask in bytes. */
export const LAND_MASK_LENGTH = MASK_BYTES.length;

/** Lattice points on land, in radians. */
export const LAND_DOTS: readonly { lat: number; lon: number }[] = (() => {
  const dots: { lat: number; lon: number }[] = [];
  let bit = 0;
  for (const { lat, count } of RINGS) {
    for (let j = 0; j < count; j++, bit++) {
      if (MASK_BYTES[bit >> 3] & (1 << (bit & 7))) {
        dots.push({ lat: lat * RAD, lon: (-180 + (360 * (j + 0.5)) / count) * RAD });
      }
    }
  }
  return dots;
})();

const SIN_LAT0 = Math.sin(GLOBE_TILT_LAT * RAD);
const COS_LAT0 = Math.cos(GLOBE_TILT_LAT * RAD);

/** Orthographic projection centred on GLOBE_TILT_LAT and on
 *  `centerLon` (degrees). `near` is true on the hemisphere facing the viewer. */
export function projectGlobePoint(lat: number, lon: number, centerLon: number) {
  const dLon = lon - centerLon * RAD;
  const cosLat = Math.cos(lat);
  const sinLat = Math.sin(lat);
  const cosD = Math.cos(dLon);
  return {
    x: GLOBE_VIEW.cx + GLOBE_VIEW.r * cosLat * Math.sin(dLon),
    y: GLOBE_VIEW.cy - GLOBE_VIEW.r * (COS_LAT0 * sinLat - SIN_LAT0 * cosLat * cosD),
    near: SIN_LAT0 * sinLat + COS_LAT0 * cosLat * cosD >= 0,
  };
}

/** One SVG path holding a dot for every land point on the near hemisphere.
 *  Each dot is a near-zero-length segment, drawn round by the stroke's caps. */
export function landDotsPath(centerLon: number): string {
  let d = '';
  for (const dot of LAND_DOTS) {
    const p = projectGlobePoint(dot.lat, dot.lon, centerLon);
    if (p.near) d += `M${p.x.toFixed(1)} ${p.y.toFixed(1)}h.01`;
  }
  return d;
}

/** Path along sampled points, with the pen lifted while the line is behind the globe. */
function nearArcPath(samples: [lat: number, lon: number][], centerLon: number): string {
  let d = '';
  let penDown = false;
  for (const [lat, lon] of samples) {
    const p = projectGlobePoint(lat, lon, centerLon);
    if (p.near) d += `${penDown ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
    penDown = p.near;
  }
  return d;
}

export function meridianPath(lonDeg: number, centerLon: number): string {
  const samples: [number, number][] = [];
  for (let lat = -90; lat <= 90; lat += 5) samples.push([lat * RAD, lonDeg * RAD]);
  return nearArcPath(samples, centerLon);
}

/** A parallel looks the same at every `centerLon`, since the globe only turns about its axis. */
export function parallelPath(latDeg: number): string {
  const samples: [number, number][] = [];
  for (let lon = 0; lon <= 360; lon += 5) samples.push([latDeg * RAD, lon * RAD]);
  return nearArcPath(samples, 0);
}

/** Longitude of the visitor's time zone, from `Date.getTimezoneOffset()`'s
 *  minutes (positive west of UTC), at 15 degrees per hour. */
export function longitudeForUtcOffset(offsetMinutes: number): number {
  return 0 - offsetMinutes / 4;
}

/** The longitude the globe faces at rest for a visitor with this UTC offset. */
export function restLongitude(offsetMinutes: number): number {
  const lon = longitudeForUtcOffset(offsetMinutes) + GLOBE_EAST_BIAS;
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}
