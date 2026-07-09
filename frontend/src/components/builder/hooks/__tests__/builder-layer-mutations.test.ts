/**
 * Phase 1134 Plan 02 — removePerLayerCompanions per-render-mode regression tests (MAP-17).
 *
 * Verifies that removePerLayerCompanions uses the LayerAdapter registry (getLayerIds)
 * when a renderModeByLayerId map is provided, and falls back to the suffix sweep
 * when it is not.
 */

import { describe, it, expect, vi } from 'vitest';
import {
  removePerLayerCompanions,
  buildDuplicateRenderingInput,
} from '@/components/builder/hooks/builder-layer-mutations';
import { makeBuilderLayer } from '@/components/builder/__tests__/fixtures/map-builder-fixtures';

// ---------------------------------------------------------------------------
// Minimal MapLibre mock
// ---------------------------------------------------------------------------

function makeMap(overrides: {
  isStyleLoaded?: () => boolean;
  getLayer?: (id: string) => object | null | undefined;
  removeLayer?: ReturnType<typeof vi.fn>;
} = {}) {
  return {
    isStyleLoaded: overrides.isStyleLoaded ?? vi.fn(() => true),
    getLayer: overrides.getLayer ?? vi.fn((id: string) => ({ id })),
    removeLayer: overrides.removeLayer ?? vi.fn(),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('removePerLayerCompanions — per-render-mode regression (MAP-17)', () => {

  it('Test 1: fill → removes [layerId, layerId-outline, layerId-extrusion]', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(3);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
  });

  it('Test 2: cluster → removes [layerId-cluster, layerId-cluster-count, layerId]', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'cluster']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(3);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-cluster');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-cluster-count');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
  });

  it.each([
    ['circle'],
    ['symbol'],
    ['heatmap'],
    ['raster'],
  ])('Test 3: %s render mode → removes only base layerId', (renderMode) => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', renderMode]]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(1);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
  });

  it('Test 3b: line render mode → removes base id + arrow companion', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'line']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    // line-adapter getLayerIds returns [layerId, arrowLayerId(layerId)]
    expect(removeLayer).toHaveBeenCalledTimes(2);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-arrow');
  });

  it('Test 3c: arrow render mode → falls back to suffix sweep (arrow not in registry)', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'arrow']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    // 'arrow' is not a registry key → getAdapter('arrow') returns circleAdapter fallback
    // whose type === 'circle', not 'arrow', so the type guard fails and the code falls
    // through to the FALLBACK_SUFFIXES sweep (10 calls including optional companions;
    // fix #430 codex r23 added the mixed-geometry -lines/-points companions).
    expect(removeLayer).toHaveBeenCalledTimes(10);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-arrow');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-colorrelief');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-label');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-cluster');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-cluster-count');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-lines');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-points');
  });

  it('Test 4: legacy / no renderMode falls back to 7-suffix sweep', () => {
    const removeLayer = vi.fn();
    // getLayer returns truthy for all ids so all 7 suffixes produce a call
    const map = makeMap({ removeLayer });

    // Called WITHOUT renderModeByLayerId — falls back to suffix list
    removePerLayerCompanions(map as never, ['l1']);

    // Fallback suffixes: base + optional companions (incl. the mixed-geometry
    // -lines/-points pair, fix #430 codex r23).
    expect(removeLayer).toHaveBeenCalledTimes(10);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-label');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-arrow');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-colorrelief');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-cluster');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-cluster-count');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-lines');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-points');
  });

  it('Test 4b: hillshade render mode removes optional color-relief companion', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'hillshade']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(2);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-colorrelief');
  });

  it('Test 5: getLayer returns null for some companions → skipped without error', () => {
    const removeLayer = vi.fn();
    // Extrusion companion does not exist on the map
    const getLayer = vi.fn((id: string) => id.endsWith('-extrusion') ? null : { id });
    const map = makeMap({ getLayer, removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).not.toHaveBeenCalledWith('layer-l1-extrusion');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
  });

  it('Test 6: map === null → no-op, no throw', () => {
    expect(() => {
      removePerLayerCompanions(null, ['l1']);
    }).not.toThrow();
  });

  it('Test 7: map.isStyleLoaded() === false → no removeLayer calls', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ isStyleLoaded: vi.fn(() => false), removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).not.toHaveBeenCalled();
  });

  it('Test 8: multiple layer ids in one call → sweeps each independently', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([
      ['l1', 'fill'],
      ['l2', 'cluster'],
    ]);

    removePerLayerCompanions(map as never, ['l1', 'l2'], renderModeByLayerId);

    // fill: 3 ids, cluster: 3 ids = 6 total
    expect(removeLayer).toHaveBeenCalledTimes(6);
    // fill companions
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
    // cluster companions
    expect(removeLayer).toHaveBeenCalledWith('layer-l2-cluster');
    expect(removeLayer).toHaveBeenCalledWith('layer-l2-cluster-count');
    expect(removeLayer).toHaveBeenCalledWith('layer-l2');
  });

});

// ---------------------------------------------------------------------------
// fix(#392): buildDuplicateRenderingInput — adjacent positioning (audit B-004b/LM-02)
// ---------------------------------------------------------------------------

describe('buildDuplicateRenderingInput — adjacent sort_order (B-004b / LM-02)', () => {
  it('Test 1: places the duplicate adjacent to the source, not at the stack bottom', () => {
    const source = makeBuilderLayer({ id: 'src', sort_order: 1 });
    // A much-higher sort_order layer elsewhere in the stack — the OLD
    // max(sort_order)+1 behavior would place the duplicate at sort_order 11.
    const other = makeBuilderLayer({ id: 'other', sort_order: 10 });

    const input = buildDuplicateRenderingInput(source, [source, other]);

    // Adjacent to the source (N+1 region), NOT max(sort_order)+1 (11).
    expect(input.sort_order).toBe(source.sort_order + 1);
    expect(input.sort_order).not.toBe(11);
  });

  it('Test 1b: does not add parent_group_id to the MapLayerInput (the type cannot carry it)', () => {
    const source = { ...makeBuilderLayer({ id: 'src', sort_order: 0 }), parent_group_id: 'group-1' };
    const input = buildDuplicateRenderingInput(source, [source]);

    expect(input).not.toHaveProperty('parent_group_id');
  });
});
