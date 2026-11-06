import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SAVED_LAYERS, toSharedLayer } from '@/test/fixtures/saved-layers';
import type { LinkedPick } from '../linked-filters';
import { usePicks } from '../hooks/use-picks';

vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: () => ({ data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' } }),
}));

const values = Array.from({ length: 60 }, (_, index) => `value-${String(index).padStart(3, '0')}-${'x'.repeat(30)}`);

function choose(layout: Record<string, unknown>) {
  const layer = { ...toSharedLayer(SAVED_LAYERS.serverCluster), layout };
  const onPicksChange = vi.fn();
  const { result } = renderHook(() => usePicks([] as readonly LinkedPick[], onPicksChange, [layer]));
  act(() => result.current.choose('w1', layer, { column: 'kind', label: 'Kind', values }));
  return onPicksChange;
}

describe('a pick on a server-clustered layer', () => {
  it('is taken when the tile URL fits', () => {
    expect(choose({})).toHaveBeenCalled();
  });

  it('is refused when the columns the map layers read push the URL past the limit', () => {
    const longColumns = Array.from({ length: 40 }, (_, index) => `${'c'.repeat(150)}_${index}`);
    expect(choose({ 'text-field': ['concat', ...longColumns.map((name) => ['get', name])] })).not.toHaveBeenCalled();
  });
});
