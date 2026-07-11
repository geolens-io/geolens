import type { MapTerrainConfig } from '@/types/api';
import { isDemTerrainVisualSuppressed } from './map-sync';
import { isTerrainCapableDemLayer } from './map-stack';

/**
 * Single source of truth for "this DEM layer is suppressed because it powers
 * active 3D terrain." Re-exported here so BOTH legend surfaces (builder
 * LegendPlugin + viewer LayerLegend) consume ONE predicate (D-02) and never
 * re-derive the render_mode/is_dem check independently.
 */
export { isDemTerrainVisualSuppressed };

/**
 * Synthetic "3D terrain" legend descriptor. Mirrors the shape/id of the stack's
 * synthetic `relief:terrain` row (`map-stack.ts` makeTerrainReliefEntry) so the
 * legend and the layer stack visually agree (D-01). Surface-agnostic: carries an
 * i18n label KEY, never literal text, so each surface resolves it in its own
 * namespace (builder: `plugins.legend.terrain3d`; viewer: `viewer.legend.terrain3d`).
 */
export interface TerrainLegendEntry {
  /** Mirrors the stack synthetic row id for visual agreement. */
  id: 'relief:terrain';
  /** Mirrors the stack synthetic row role. */
  role: 'surface-terrain';
  /** i18n key the caller resolves in its own namespace. */
  labelKey: string;
  /**
   * fix(HT-08): the bound DEM layer's display name, so the legend keeps the
   * dataset identity ("swissALTI3D relief") instead of degrading to a generic
   * "3D terrain" row the moment the overlay is off. Null when the backing
   * layer carries no name; callers then fall back to t(labelKey).
   */
  sourceName: string | null;
}

export interface DeriveTerrainLegendEntryOptions {
  /** i18n key for the synthetic entry label, resolved by the calling surface. */
  labelKey: string;
}

/** Minimal layer shape needed to decide whether a backing terrain DEM exists. */
type TerrainBackingLayer = {
  dataset_id?: string | null;
  is_dem?: boolean | null;
  dataset_record_type?: string | null;
  display_name?: string | null;
  dataset_name?: string | null;
};

/**
 * Returns a single synthetic "3D terrain" legend entry descriptor when terrain
 * is active, else null. "Active" uses the SAME truth map-stack uses to emit its
 * synthetic `relief:terrain` row: terrain_config is enabled, a source dataset is
 * selected, AND a terrain-capable DEM layer for that dataset is actually present
 * in the layer set (999.17 MD-01). Without the backing-layer check, a dangling
 * terrain_config (legacy maps whose source layer was deleted) would render a
 * phantom "3D terrain" legend entry while the stack reports it missing and no
 * mesh paints — the exact legend<->map disagreement this phase eliminates.
 * Mirrors the stack's `sourceStatus: 'active'` condition (map-stack.ts).
 */
export function deriveTerrainLegendEntry(
  terrainConfig: MapTerrainConfig | null | undefined,
  layers: readonly TerrainBackingLayer[] | null | undefined,
  opts: DeriveTerrainLegendEntryOptions,
): TerrainLegendEntry | null {
  const sourceDatasetId = terrainConfig?.enabled === true ? terrainConfig.source_dataset_id : null;
  if (!sourceDatasetId) return null;

  const backingLayer = (layers ?? []).find(
    (layer) => layer.dataset_id === sourceDatasetId && isTerrainCapableDemLayer(layer),
  );
  if (!backingLayer) return null;

  return {
    id: 'relief:terrain',
    role: 'surface-terrain',
    labelKey: opts.labelKey,
    sourceName: backingLayer.display_name ?? backingLayer.dataset_name ?? null,
  };
}

/**
 * True when the terrain source dataset is already represented by one of the
 * surface's per-layer legend entries — so the synthetic "3D terrain" entry would
 * duplicate it. Callers pass THEIR OWN shown-entry list (each surface filters
 * differently: LegendPlugin drops hidden layers, LayerLegend keeps them as
 * toggles), so the dedup is correct per surface. When the source DEM has no
 * shown entry (pure terrain render_mode → suppressed, or hidden), this returns
 * false and the synthetic entry remains the only terrain indicator.
 */
export function terrainSourceIsShownAsLayer(
  terrainConfig: MapTerrainConfig | null | undefined,
  shownLayers: readonly { dataset_id?: string | null }[],
): boolean {
  const src = terrainConfig?.enabled === true ? terrainConfig.source_dataset_id : null;
  return !!src && shownLayers.some((l) => l.dataset_id === src);
}
