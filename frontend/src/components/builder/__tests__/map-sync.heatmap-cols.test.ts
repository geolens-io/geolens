/**
 * Heatmap weight-column extraction tests for getDataDrivenColumnsForLayer.
 *
 * These tests cover the FULL HeatmapStyleControls write shape — both the
 * `_heatmap-weight-column` marker AND the `['get', col]` runtime expression
 * that HeatmapStyleControls.handleWeightColumnChange (line 43-44) writes
 * together whenever a weight column is selected.
 *
 * The existing tests in map-sync.data-driven-cols.test.ts:17-23 cover the
 * marker in isolation; this file adds:
 *   1. The full write shape (both keys present) — exercises Set deduplication
 *   2. Marker-absent fallback (only ['get', col] expression)
 *   3. Expression-absent fallback (only marker, expression = 1 default)
 *   4. Mismatch case (marker ≠ expression) — proves both inputs feed the same Set
 *
 * Reference: HeatmapStyleControls.tsx:36-47
 */

import { describe, it, expect } from 'vitest';
import { getDataDrivenColumnsForLayer } from '@/components/builder/map-sync';

describe('heatmap-weight-column extraction', () => {
  it('extracts a heatmap weight column from the FULL HeatmapStyleControls write shape', () => {
    // This is the exact shape HeatmapStyleControls.handleWeightColumnChange writes.
    // Both `_heatmap-weight-column` (marker) and `heatmap-weight: ['get', col]`
    // (runtime expression) reference the same column.  The Set deduplication
    // inside getDataDrivenColumnsForLayer must yield a single entry.
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {
        '_heatmap-weight-column': 'magnitude',
        'heatmap-weight': ['get', 'magnitude'],
        'heatmap-radius': 30,
        'heatmap-intensity': 1,
      },
    });
    expect(cols).toEqual(['magnitude']);
  });

  it("extracts heatmap weight column even when only the ['get'] expression is present (marker missing)", () => {
    // Defensive: a future write path might forget to set `_heatmap-weight-column`.
    // The walk() expression tree traversal should still find the column via the
    // `['get', col]` expression in heatmap-weight.
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {
        'heatmap-weight': ['get', 'magnitude'],
      },
    });
    expect(cols).toEqual(['magnitude']);
  });

  it('extracts heatmap weight column even when only the marker is present (expression = 1 default)', () => {
    // HeatmapStyleControls resets `heatmap-weight` to 1 when no column is chosen,
    // but leaves `_heatmap-weight-column` set to the string if someone manually
    // edits the paint object.  The direct marker read path covers this case.
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {
        '_heatmap-weight-column': 'magnitude',
        'heatmap-weight': 1,
      },
    });
    expect(cols).toEqual(['magnitude']);
  });

  it('extracts BOTH column-extractor inputs simultaneously when marker and expression differ (mismatch case)', () => {
    // Should not occur in practice (HeatmapStyleControls keeps them in sync),
    // but proves the Set union semantics: both the marker AND the expression tree
    // feed into the same cols Set so neither is silently dropped.
    const cols = getDataDrivenColumnsForLayer({
      style_config: null,
      paint: {
        '_heatmap-weight-column': 'col_a',
        'heatmap-weight': ['get', 'col_b'],
      },
    });
    expect(cols.sort()).toEqual(['col_a', 'col_b']);
  });
});
