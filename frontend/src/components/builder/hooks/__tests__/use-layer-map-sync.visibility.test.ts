import { describe, it, expect, vi } from 'vitest';
import { applyLayerVisibilityToMap } from '../use-layer-map-sync';
import { getCompanionLayerIds } from '@/components/builder/companion-ids';
import type { MapLayerResponse } from '@/types/api';

// codex(#841): the canonical visibility helper must honor the ux(#839)
// clusterShowCounts opt-out — re-showing a layer through the single, bulk, or
// group path used to resurrect counts the user turned off until the next full
// composition sync.
describe('applyLayerVisibilityToMap — clusterShowCounts gate (codex #841)', () => {
  function makeMap() {
    return {
      getLayer: vi.fn().mockReturnValue({ id: 'x' }),
      setLayoutProperty: vi.fn(),
    };
  }

  const layer = (builder: Record<string, unknown>): MapLayerResponse => ({
    id: 'layer-1',
    paint: {},
    style_config: { render_mode: 'cluster', builder },
  } as unknown as MapLayerResponse);

  const ids = getCompanionLayerIds('layer-1');
  const visibilityOf = (map: ReturnType<typeof makeMap>, id: string) =>
    (map.setLayoutProperty.mock.calls as Array<[string, string, string]>)
      .find(([callId, prop]) => callId === id && prop === 'visibility')?.[2];

  it('re-showing a layer keeps the count layer hidden when counts are off', () => {
    const map = makeMap();
    applyLayerVisibilityToMap(map as never, layer({ clusterShowCounts: false }), true);
    expect(visibilityOf(map, ids.clusterCount)).toBe('none');
    expect(visibilityOf(map, ids.cluster)).toBe('visible');
    expect(visibilityOf(map, ids.layer)).toBe('visible');
  });

  it('an absent flag shows the count layer (default on)', () => {
    const map = makeMap();
    applyLayerVisibilityToMap(map as never, layer({}), true);
    expect(visibilityOf(map, ids.clusterCount)).toBe('visible');
  });

  it('hiding the layer hides the count layer regardless of the flag', () => {
    const map = makeMap();
    applyLayerVisibilityToMap(map as never, layer({}), false);
    expect(visibilityOf(map, ids.clusterCount)).toBe('none');
  });
});
