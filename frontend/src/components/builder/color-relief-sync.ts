/**
 * Synchronize a hypsometric companion below its hillshade on the shared DEM
 * source. Recreate the layer when its ramp changes because `setPaintProperty`
 * does not reliably rebuild color-ramp textures. The hillshade-only gate avoids
 * sharing this source with active 3D terrain. Unknown ramp names are handled by
 * `getRampColors`.
 */
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getRampColors } from '@/lib/color-ramps';
import type { AdapterLayerInput } from './layer-adapters/types';
import { COLOR_RELIEF_SUFFIX } from './companion-ids';
import { MAP_COLORS } from '@/lib/map-colors';

// The editor currently exposes a fixed, metre-based elevation range.
const DEFAULT_ELEV_MIN = 0;
const DEFAULT_ELEV_MAX = 4000;
const STOP_COUNT = 7;

/**
 * Build a MapLibre `interpolate` expression that maps elevation (metres) to
 * colors from the named ramp.
 */
// fix(#455): the shader reads masked pixels as the encoding floor. Keep that
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

/**
 * Sync a companion `color-relief` layer for the given DEM layer.
 *
 * Recreates an enabled hillshade companion so ramp changes reach the GPU, and
 * removes it for every other mode. A missing pre-idle source is a safe no-op.
 */
export function syncColorReliefLayer(
  map: MaplibreMap,
  input: AdapterLayerInput,
): void {
  const reliefLayerId = `${input.layerId}${COLOR_RELIEF_SUFFIX}`;

  const renderMode = (input.style_config as Record<string, unknown> | null | undefined)?.render_mode;
  const isHillshade = renderMode === 'hillshade';
  const enabled = input.paint['_hypso-enabled'] === true && isHillshade;

  if (!enabled) {
    if (map.getLayer(reliefLayerId)) {
      map.removeLayer(reliefLayerId);
    }
    return;
  }

  if (!map.getSource(input.sourceId)) return;

  const rampName =
    typeof input.paint['_hypso-ramp'] === 'string'
      ? (input.paint['_hypso-ramp'] as string)
      : 'Viridis';
  const rampReversed = input.paint['_hypso-reversed'] === true;

  // Recreate so MapLibre rebuilds the color-ramp texture.
  if (map.getLayer(reliefLayerId)) {
    map.removeLayer(reliefLayerId);
  }

  const reliefLayer: import('maplibre-gl').AddLayerObject = {
    id: reliefLayerId,
    type: 'color-relief',
    source: input.sourceId,
    layout: { visibility: input.visible ? 'visible' : 'none' },
    paint: {
      'color-relief-color': buildElevationExpression(rampName, undefined, undefined, rampReversed),
      'color-relief-opacity': 0.7,
    },
  };

  map.addLayer(
    reliefLayer,
    // Keep hillshade shading above the tint.
    input.layerId,
  );
}
