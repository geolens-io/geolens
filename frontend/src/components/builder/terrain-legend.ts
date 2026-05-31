import type { MapTerrainConfig } from '@/types/api';
import { isDemTerrainVisualSuppressed } from './map-sync';

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
}

export interface DeriveTerrainLegendEntryOptions {
  /** i18n key for the synthetic entry label, resolved by the calling surface. */
  labelKey: string;
}

/**
 * Returns a single synthetic "3D terrain" legend entry descriptor when terrain
 * is active, else null. "Active" uses the SAME truth map-stack uses to emit its
 * synthetic `relief:terrain` row: terrain_config is enabled AND a source dataset
 * is selected. Keeping this in lockstep with the stack is the phase invariant.
 */
export function deriveTerrainLegendEntry(
  terrainConfig: MapTerrainConfig | null | undefined,
  opts: DeriveTerrainLegendEntryOptions,
): TerrainLegendEntry | null {
  const isActive = terrainConfig?.enabled === true && !!terrainConfig.source_dataset_id;
  if (!isActive) return null;
  return {
    id: 'relief:terrain',
    role: 'surface-terrain',
    labelKey: opts.labelKey,
  };
}
