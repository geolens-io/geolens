// The companion-layer id scheme (`-outline`, `-extrusion`, `-arrow`, `-label`,
// `-colorrelief`, `-cluster`, `-cluster-count`) in one place. The toggle,
// filter and teardown paths derive companion ids through
// `getCompanionLayerIds`, so a new companion type can't be silently missed by
// one of them.
import { clusterCircleLayerId, clusterCountLayerId } from './layer-adapters/cluster-adapter';
import { mixedLinesLayerId, mixedPointsLayerId } from './layer-adapters/mixed-adapter';

/**
 * Suffix for the DEM hypsometric color-relief companion layer. Unlike the other
 * companions, the color-relief layer reuses the raster-dem source rather than
 * owning its own source, so it is keyed off the LAYER id (`layer-${id}`), not the
 * raw layer id. Exported so the standalone derivations in map-sync and the
 * hillshade adapter share one literal.
 */
export const COLOR_RELIEF_SUFFIX = '-colorrelief';

/** The full set of MapLibre source/layer ids derived from one logical layer. */
interface CompanionLayerIds {
  /** Per-layer source id (`source-${id}`). Note: deduped vector layers resolve a
   *  DIFFERENT shared source via `getSourceIdForLayer`; this is only the
   *  per-layer key used by the teardown helpers. */
  source: string;
  /** Primary geometry layer (`layer-${id}`). */
  layer: string;
  outline: string;
  extrusion: string;
  arrow: string;
  label: string;
  /** DEM hypsometric tint companion (`layer-${id}-colorrelief`). */
  colorRelief: string;
  /** Cluster circle companion (`layer-${id}-cluster`). */
  cluster: string;
  /** Cluster count label companion (`layer-${id}-cluster-count`). */
  clusterCount: string;
  /** Mixed-geometry line-family companion (`layer-${id}-lines`). */
  mixedLines: string;
  /** Mixed-geometry point-family companion (`layer-${id}-points`). */
  mixedPoints: string;
}

/**
 * Derive every companion source/layer id for a logical layer id.
 *
 * `prefix` is the optional Viewer/Embed id prefix (e.g. `embed-`) used by
 * `syncLayersToMap`'s `idPrefix` option — it is applied to source/layer ids the
 * same way `prefixed()` applies it. Cluster and color-relief ids hang off the
 * (prefixed) layer id, matching `clusterCircleLayerId`/`clusterCountLayerId` and
 * the `${layerId}-colorrelief` convention.
 */
export function getCompanionLayerIds(rawLayerId: string, prefix?: string): CompanionLayerIds {
  const p = prefix ?? '';
  const layer = `${p}layer-${rawLayerId}`;
  return {
    source: `${p}source-${rawLayerId}`,
    layer,
    outline: `${layer}-outline`,
    extrusion: `${layer}-extrusion`,
    arrow: `${layer}-arrow`,
    label: `${layer}-label`,
    colorRelief: `${layer}${COLOR_RELIEF_SUFFIX}`,
    cluster: clusterCircleLayerId(layer),
    clusterCount: clusterCountLayerId(layer),
    mixedLines: mixedLinesLayerId(layer),
    mixedPoints: mixedPointsLayerId(layer),
  };
}

/** All prospective map layers of a saved layer, including disabled companions; sources are excluded. */
export function getDrawingLayerIds(rawLayerId: string, prefix?: string): string[] {
  const ids = getCompanionLayerIds(rawLayerId, prefix);
  return [
    ids.colorRelief,
    ids.label,
    ids.arrow,
    ids.extrusion,
    ids.outline,
    ids.clusterCount,
    ids.cluster,
    ids.mixedLines,
    ids.mixedPoints,
    ids.layer,
  ];
}
