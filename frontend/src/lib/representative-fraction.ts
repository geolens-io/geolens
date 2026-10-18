/**
 * Representative-fraction ("1:N") scale denomination helpers.
 *
 * Used by MapCoordReadout for the optional `showScale` segment.
 *
 * Formula: classic Web Mercator meters-per-pixel.
 *   M_PER_PX = 156543.03392 * cos(lat * π / 180) / 2^zoom
 * Reference: https://wiki.openstreetmap.org/wiki/Zoom_levels
 */

/** Meters per pixel at zoom 0 (earth circumference / tile size). */
const EARTH_CIRC_FACTOR = 156543.03392;

/**
 * Classic Web Mercator meters-per-pixel at geographic latitude `lat` (degrees)
 * and MapLibre zoom level `zoom`.
 *
 * At ±90° the cosine is 0 (or a tiny float); the returned value approaches 0.
 * Callers must handle sub-1 denominators — `formatRfValue` clamps them to "1".
 */
export function metersPerPixel(lat: number, zoom: number): number {
  return EARTH_CIRC_FACTOR * Math.cos((lat * Math.PI) / 180) / Math.pow(2, zoom);
}

/**
 * Compact-number formatter for representative-fraction denominators.
 *
 * Trailing ".0" is dropped:
 *   < 1        → "1"        (clamped; includes NaN, Infinity, negative)
 *   < 1 000    → "850"      (plain integer, no grouping)
 *   < 1 000 000→ "1.2k"     (one decimal, drop trailing ".0"; lowercase k)
 *   ≥ 1 000 000→ "1.2M"     (one decimal, drop trailing ".0"; uppercase M)
 *
 * Returns the value portion only — the caller prefixes "1:".
 */
export function formatRfValue(denominator: number): string {
  if (!isFinite(denominator) || isNaN(denominator) || denominator < 1) {
    return '1';
  }

  if (denominator < 1_000) {
    return String(Math.round(denominator));
  }

  if (denominator < 1_000_000) {
    const rounded = Math.round((denominator / 1_000) * 10) / 10;
    // Rounding to 1000k rolls up to the M tier.
    if (rounded >= 1_000) {
      return '1M';
    }
    return rounded % 1 === 0 ? `${Math.round(rounded)}k` : `${rounded}k`;
  }

  const rounded = Math.round((denominator / 1_000_000) * 10) / 10;
  return rounded % 1 === 0 ? `${Math.round(rounded)}M` : `${rounded}M`;
}

/**
 * A "1:288k"-style representative-fraction string.
 *
 * @param lat   Geographic latitude of the point of interest (degrees).
 * @param zoom  MapLibre zoom level.
 * @param ppi   Screen pixels per inch (default 96 — standard web DPI).
 */
export function formatRepresentativeFraction(
  lat: number,
  zoom: number,
  ppi = 96,
): string {
  const pxPerMeter = ppi / 0.0254; // 3779.527559... at 96 DPI
  const denominator = metersPerPixel(lat, zoom) * pxPerMeter;
  return `1:${formatRfValue(denominator)}`;
}
