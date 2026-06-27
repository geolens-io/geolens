/**
 * EDITOR-DEM-05: Hypsometric tint via MapLibre native `color-relief` layer.
 *
 * A companion `color-relief` layer is added on the SAME raster-dem source that the hillshade
 * adapter already owns.  It is inserted BELOW the hillshade layer so the shading renders on top.
 *
 * Elevation range default: 0–4000 m (Assumption A1, documented in 1140-RESEARCH.md).
 * Users who need different ranges should use a future min/max-elevation control (follow-up).
 *
 * Pitfall 1 (color-relief-color): `color-relief-color` uses `ColorRampProperty` — the same class
 * as `heatmap-color` and `line-gradient`. `setPaintProperty` does not reliably trigger the ramp
 * texture re-bake.  The layer is always removed+added on every call to guarantee a correct repaint
 * when the ramp changes.
 *
 * Pitfall 2 (source sharing): MapLibre warns when a raster-dem source is shared with 3D terrain
 * (`map.setTerrain`), but that warning is irrelevant here because `syncColorReliefLayer` is only
 * active in hillshade mode (color-relief is gated on render_mode === 'hillshade').  No terrain
 * source contention occurs.
 *
 * Threat T-1140-05: `getRampColors` falls back to 'YlOrRd' for unknown ramp names, so an
 * arbitrary `_hypso-ramp` string cannot break the expression.
 */
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getRampColors } from '@/lib/color-ramps';
import type { AdapterLayerInput } from './layer-adapters/types';
import { COLOR_RELIEF_SUFFIX } from './companion-ids';

// Default elevation range (metres) for the interpolation stops.
// Assumption A1: 0–4000 m covers the majority of terrain use-cases for a builder tool.
// A follow-up control can expose min/max to users (v1032 candidate).
const DEFAULT_ELEV_MIN = 0;
const DEFAULT_ELEV_MAX = 4000;
const STOP_COUNT = 7;

/**
 * Build a MapLibre `interpolate` expression that maps elevation (metres) to
 * colours from the given chroma-js ramp name.
 *
 * Expression shape (MapLibre 5.24 `color-relief-color` accepted format):
 * ```
 * ['interpolate', ['linear'], ['elevation'], elev0, '#color0', elev1, '#color1', ...]
 * ```
 */
export function buildElevationExpression(
  rampName: string,
  elevMin = DEFAULT_ELEV_MIN,
  elevMax = DEFAULT_ELEV_MAX,
): unknown[] {
  const colors = getRampColors(rampName, STOP_COUNT);
  const step = (elevMax - elevMin) / (colors.length - 1);
  const expr: unknown[] = ['interpolate', ['linear'], ['elevation']];
  colors.forEach((color, i) => {
    expr.push(elevMin + i * step, color);
  });
  return expr;
}

/**
 * Sync a companion `color-relief` layer for the given DEM layer.
 *
 * - Enabled + hillshade mode → remove+add the color-relief layer (recreation on every call
 *   guarantees the ramp is applied, per Pitfall 1).
 * - Disabled OR any mode other than hillshade → remove the companion layer if it exists.
 *
 * Defensive guards ensure a pre-idle / source-less map never throws inside the sync loop.
 */
export function syncColorReliefLayer(
  map: MaplibreMap,
  input: AdapterLayerInput,
): void {
  // builder-audit SYNC-04: the -colorrelief suffix lives in companion-ids.ts.
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

  // Guard: source must exist (added by hillshade-adapter before this helper is called).
  if (!map.getSource(input.sourceId)) return;

  const rampName =
    typeof input.paint['_hypso-ramp'] === 'string'
      ? (input.paint['_hypso-ramp'] as string)
      : 'Viridis';

  // Always recreate (remove then add) — color-relief-color is a ColorRampProperty;
  // setPaintProperty does not trigger the ramp texture re-bake (Pitfall 1).
  if (map.getLayer(reliefLayerId)) {
    map.removeLayer(reliefLayerId);
  }

  map.addLayer(
    {
      id: reliefLayerId,
      // 'color-relief' is a native MapLibre 5.24 layer type.
      // The @maplibre/maplibre-gl-style-spec LayerSpecification union predates this type, so we
      // cast to silence the type checker while keeping full runtime safety.
      type: 'color-relief' as unknown as 'hillshade',
      source: input.sourceId, // existing raster-dem source from hillshade-adapter
      layout: { visibility: input.visible ? 'visible' : 'none' },
      paint: {
        'color-relief-color': buildElevationExpression(rampName),
        'color-relief-opacity': 0.7,
      },
    } as unknown as import('maplibre-gl').AddLayerObject,
    // Insert BELOW the hillshade layer so shading renders on top of the tint.
    input.layerId,
  );
}
