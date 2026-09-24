/**
 * The elevation ramp a hypsometric tint draws with. The hillshade adapter
 * describes the tint layer itself. Unknown ramp names are handled by
 * `getRampColors`.
 */
import { getRampColors } from '@/lib/color-ramps';
import { MAP_COLORS } from '@/lib/map-colors';

// The editor currently exposes a fixed, metre-based elevation range.
const DEFAULT_ELEV_MIN = 0;
const DEFAULT_ELEV_MAX = 4000;
const STOP_COUNT = 7;

/**
 * Build a MapLibre `interpolate` expression that maps elevation (metres) to
 * colors from the named ramp.
 */
// The shader reads masked pixels as the encoding floor. Keep that
// range transparent while retaining the first-color clamp for real low terrain.
const NODATA_ELEVATION_FLOOR = -10000;
const LOWEST_LAND_GUARD = -500;

export function buildElevationExpression(
  rampName: string,
  elevMin = DEFAULT_ELEV_MIN,
  elevMax = DEFAULT_ELEV_MAX,
  reversed = false,
): import('maplibre-gl').ExpressionSpecification {
  const colors = getRampColors(rampName, STOP_COUNT, reversed);
  const step = (elevMax - elevMin) / (colors.length - 1);
  const expr: unknown[] = ['interpolate', ['linear'], ['elevation']];
  // Guard stops only make sense below the real domain; a ramp whose elevMin
  // dips into the guard band (unusual, e.g. bathymetry) skips them rather than
  // emit non-ascending stops.
  if (elevMin > LOWEST_LAND_GUARD + 1) {
    expr.push(NODATA_ELEVATION_FLOOR, MAP_COLORS.transparent);
    expr.push(LOWEST_LAND_GUARD, MAP_COLORS.transparent);
    expr.push(LOWEST_LAND_GUARD + 1, colors[0]);
  }
  colors.forEach((color, i) => {
    expr.push(elevMin + i * step, color);
  });
  // Dynamic pushes prevent TypeScript from inferring the interpolate tuple.
  return expr as import('maplibre-gl').ExpressionSpecification;
}
