import { describe, expect, it } from 'vitest';
import type { MapTerrainConfig } from '@/types/api';
import {
  deriveTerrainLegendEntry,
  isDemTerrainVisualSuppressed,
  terrainSourceIsShownAsLayer,
} from '../terrain-legend';

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

    // A terrain-capable DEM layer backing dataset 'dem-1'.
    const backingDemLayer = {
      dataset_id: 'dem-1',
      is_dem: true,
      dataset_record_type: 'raster_dataset',
    };

    it('returns one synthetic entry when terrain is active AND a backing DEM layer is present', () => {
      const terrainConfig: MapTerrainConfig = {
        enabled: true,
        source_dataset_id: 'dem-1',
        exaggeration: 1,
      };
      const entry = deriveTerrainLegendEntry(terrainConfig, [backingDemLayer], { labelKey });
      expect(entry).not.toBeNull();
      expect(entry?.id).toBe('relief:terrain');
      expect(entry?.role).toBe('surface-terrain');
      expect(entry?.labelKey).toBe(labelKey);
    });

    it('returns null when terrain_config is null', () => {
      expect(deriveTerrainLegendEntry(null, [backingDemLayer], { labelKey })).toBeNull();
    });

    it('returns null when terrain is configured but not enabled', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: false, source_dataset_id: 'dem-1', exaggeration: 1 },
          [backingDemLayer],
          { labelKey },
        ),
      ).toBeNull();
    });

    it('returns null when enabled but no source_dataset_id (dangling/unset)', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: true, source_dataset_id: null, exaggeration: 1 },
          [backingDemLayer],
          { labelKey },
        ),
      ).toBeNull();
    });

    // 999.17 MD-01: dangling terrain_config (legacy maps whose source layer was
    // deleted) → no backing DEM layer present → NO phantom synthetic entry.
    it('returns null when enabled with a source but NO backing DEM layer exists (dangling config)', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 },
          [], // no layers at all
          { labelKey },
        ),
      ).toBeNull();
    });

    it('returns null when a layer exists for the dataset but it is NOT terrain-capable (not a DEM)', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 },
          [{ dataset_id: 'dem-1', is_dem: false, dataset_record_type: 'vector_dataset' }],
          { labelKey },
        ),
      ).toBeNull();
    });

    it('returns null when the only DEM layer backs a DIFFERENT dataset', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 },
          [{ dataset_id: 'dem-other', is_dem: true, dataset_record_type: 'raster_dataset' }],
          { labelKey },
        ),
      ).toBeNull();
    });

    it('returns null when layers is null/undefined', () => {
      expect(
        deriveTerrainLegendEntry(
          { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 },
          null,
          { labelKey },
        ),
      ).toBeNull();
    });
  });

  describe('terrainSourceIsShownAsLayer (dedup guard)', () => {
    const active: MapTerrainConfig = { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 };

    it('is true when the terrain source dataset has a shown per-layer entry', () => {
      expect(terrainSourceIsShownAsLayer(active, [{ dataset_id: 'dem-1' }, { dataset_id: 'roads' }])).toBe(true);
    });

    it('is false when the source dataset is not among the shown entries (suppressed/hidden)', () => {
      expect(terrainSourceIsShownAsLayer(active, [{ dataset_id: 'roads' }])).toBe(false);
    });

    it('is false when terrain is disabled or has no source', () => {
      expect(terrainSourceIsShownAsLayer({ enabled: false, source_dataset_id: 'dem-1', exaggeration: 1 }, [{ dataset_id: 'dem-1' }])).toBe(false);
      expect(terrainSourceIsShownAsLayer(null, [{ dataset_id: 'dem-1' }])).toBe(false);
    });
  });
});
