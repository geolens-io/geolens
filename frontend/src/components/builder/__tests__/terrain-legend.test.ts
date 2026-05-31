import { describe, expect, it } from 'vitest';
import type { MapTerrainConfig } from '@/types/api';
import { deriveTerrainLegendEntry, isDemTerrainVisualSuppressed } from '../terrain-legend';

describe('terrain-legend helper', () => {
  describe('isDemTerrainVisualSuppressed (re-exported single source of truth)', () => {
    it('reports a render_mode:"terrain" DEM layer as suppressed', () => {
      expect(
        isDemTerrainVisualSuppressed({
          is_dem: true,
          style_config: { render_mode: 'terrain' },
        }),
      ).toBe(true);
    });

    it('reports a hillshade-mode relief DEM layer as NOT suppressed', () => {
      expect(
        isDemTerrainVisualSuppressed({
          is_dem: true,
          style_config: { render_mode: 'hillshade' },
        }),
      ).toBe(false);
    });

    it('reports a non-DEM layer as NOT suppressed', () => {
      expect(
        isDemTerrainVisualSuppressed({
          is_dem: false,
          style_config: { render_mode: 'terrain' },
        }),
      ).toBe(false);
    });
  });

  describe('deriveTerrainLegendEntry', () => {
    const labelKey = 'plugins.legend.terrain3d';

    it('returns one synthetic entry when terrain is active (enabled + source)', () => {
      const terrainConfig: MapTerrainConfig = {
        enabled: true,
        source_dataset_id: 'dem-1',
        exaggeration: 1,
      };
      const entry = deriveTerrainLegendEntry(terrainConfig, { labelKey });
      expect(entry).not.toBeNull();
      expect(entry?.id).toBe('relief:terrain');
      expect(entry?.role).toBe('surface-terrain');
      expect(entry?.labelKey).toBe(labelKey);
    });

    it('returns null when terrain_config is null', () => {
      expect(deriveTerrainLegendEntry(null, { labelKey })).toBeNull();
    });

    it('returns null when terrain is configured but not enabled', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: false, source_dataset_id: 'dem-1', exaggeration: 1 },
          { labelKey },
        ),
      ).toBeNull();
    });

    it('returns null when enabled but no source_dataset_id (dangling/unset)', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: true, source_dataset_id: null, exaggeration: 1 },
          { labelKey },
        ),
      ).toBeNull();
    });
  });
});
