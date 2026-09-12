import { describe, it, expect, vi } from 'vitest';
import {
  removePerLayerCompanions,
  buildDuplicateRenderingInput,
} from '@/components/builder/hooks/builder-layer-mutations';
import { makeBuilderLayer } from '@/components/builder/__tests__/fixtures/map-builder-fixtures';

function makeMap(overrides: {
  isStyleLoaded?: () => boolean;
  getLayer?: (id: string) => object | null | undefined;
  removeLayer?: ReturnType<typeof vi.fn>;
} = {}) {
  return {
    isStyleLoaded: overrides.isStyleLoaded ?? vi.fn(() => true),
    getLayer: overrides.getLayer ?? vi.fn((id: string) => ({ id })),
    removeLayer: overrides.removeLayer ?? vi.fn(),
    // The helper defers to `idle` when the style is mid-swap.
    once: vi.fn(),
  };
}

describe('removePerLayerCompanions by render mode', () => {

  it('removes fill companions', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(3);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
  });

  it('removes cluster companions', () => {
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
  ])('%s render mode removes only the base layer', (renderMode) => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', renderMode]]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(1);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
  });

  it('removes the line base and arrow companion', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'line']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(2);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-arrow');
  });

  it('uses the suffix sweep when arrow is not registered', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'arrow']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    // 'arrow' is not a registry key → getAdapter('arrow') returns circleAdapter fallback
    // whose type === 'circle', not 'arrow', so the type guard fails and the code falls
    // through to the full suffix sweep, including mixed-geometry companions.
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

  it('uses the full suffix sweep without a render mode', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });

    removePerLayerCompanions(map as never, ['l1']);

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

  it('removes the optional hillshade color-relief companion', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([['l1', 'hillshade']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(2);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-colorrelief');
  });

  it('skips companions that are absent from the map', () => {
    const removeLayer = vi.fn();
    const getLayer = vi.fn((id: string) => id.endsWith('-extrusion') ? null : { id });
    const map = makeMap({ getLayer, removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).not.toHaveBeenCalledWith('layer-l1-extrusion');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
  });

  it('does nothing for a null map', () => {
    expect(() => {
      removePerLayerCompanions(null, ['l1']);
    }).not.toThrow();
  });

  it('does not remove layers before the style loads', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ isStyleLoaded: vi.fn(() => false), removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

    expect(removeLayer).not.toHaveBeenCalled();
  });

  // A delete during a style swap must retry or its companion layers remain orphaned.
  it('retries the sweep on idle when the style is not loaded', () => {
    const removeLayer = vi.fn();
    const isStyleLoaded = vi.fn(() => false);
    const map = makeMap({ isStyleLoaded, removeLayer });
    const renderModeByLayerId = new Map([['l1', 'fill']]);

    removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);
    expect(removeLayer).not.toHaveBeenCalled();

    const idleCall = map.once.mock.calls.find((c) => c[0] === 'idle');
    expect(idleCall).toBeDefined();
    isStyleLoaded.mockReturnValue(true);
    (idleCall![1] as () => void)();

    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
  });

  it('replays a single-pass iterable on the idle retry', () => {
    const removeLayer = vi.fn();
    const isStyleLoaded = vi.fn(() => false);
    const map = makeMap({ isStyleLoaded, removeLayer });
    // A Set's iterator is re-iterable, but a generator's is not, so the retry
    // must not depend on the caller's iterable surviving a second walk.
    function* once(): Generator<string> { yield 'l1'; }

    removePerLayerCompanions(map as never, once());
    const idleCall = map.once.mock.calls.find((c) => c[0] === 'idle');
    isStyleLoaded.mockReturnValue(true);
    (idleCall![1] as () => void)();

    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
  });

  it('sweeps multiple layer ids independently', () => {
    const removeLayer = vi.fn();
    const map = makeMap({ removeLayer });
    const renderModeByLayerId = new Map([
      ['l1', 'fill'],
      ['l2', 'cluster'],
    ]);

    removePerLayerCompanions(map as never, ['l1', 'l2'], renderModeByLayerId);

    expect(removeLayer).toHaveBeenCalledTimes(6);
    expect(removeLayer).toHaveBeenCalledWith('layer-l1');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-outline');
    expect(removeLayer).toHaveBeenCalledWith('layer-l1-extrusion');
    expect(removeLayer).toHaveBeenCalledWith('layer-l2-cluster');
    expect(removeLayer).toHaveBeenCalledWith('layer-l2-cluster-count');
    expect(removeLayer).toHaveBeenCalledWith('layer-l2');
  });

});

describe('buildDuplicateRenderingInput', () => {
  it('places the duplicate adjacent to the source', () => {
    const source = makeBuilderLayer({ id: 'src', sort_order: 1 });

    const input = buildDuplicateRenderingInput(source);

    expect(input.sort_order).toBe(source.sort_order + 1);
  });

  it('does not add parent_group_id to the MapLayerInput', () => {
    const source = { ...makeBuilderLayer({ id: 'src', sort_order: 0 }), parent_group_id: 'group-1' };
    const input = buildDuplicateRenderingInput(source);

    expect(input).not.toHaveProperty('parent_group_id');
  });
});
