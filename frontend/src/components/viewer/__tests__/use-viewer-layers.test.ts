import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useViewerLayers } from '@/components/viewer/hooks/use-viewer-layers';

interface TestLayer {
  id: string;
  dataset_id: string;
  table_name: string;
  sort_order: number;
  visible: boolean;
}

function layer(overrides: Partial<TestLayer> = {}): TestLayer {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    table_name: 'table_1',
    sort_order: 0,
    visible: true,
    ...overrides,
  };
}

describe('useViewerLayers', () => {
  it('tracks visibility by stable layer key instead of sort order', () => {
    const layers = [
      layer({ id: 'layer-a', dataset_id: 'dataset-a', sort_order: 0 }),
      layer({ id: 'layer-b', dataset_id: 'dataset-b', sort_order: 0 }),
    ];
    const { result } = renderHook(() => useViewerLayers(layers));

    expect(result.current.visibleLayers).toEqual(new Set(['layer-a', 'layer-b']));

    act(() => {
      result.current.handleToggleVisibility('layer-b');
    });

    expect(result.current.visibleLayers).toEqual(new Set(['layer-a']));
  });

  it('starts a different map from its saved visibility', () => {
    const mapA = [layer({ id: 'a1' }), layer({ id: 'a2' })];
    const mapB = [layer({ id: 'b1' }), layer({ id: 'b2' })];
    const { result, rerender } = renderHook(
      ({ layers, mapKey }) => useViewerLayers(layers, { mapKey }),
      { initialProps: { layers: mapA, mapKey: 'map-a' } },
    );

    act(() => result.current.handleToggleVisibility('a1'));
    rerender({ layers: mapB, mapKey: 'map-b' });

    expect(result.current.visibleLayers).toEqual(new Set(['b1', 'b2']));
  });

  it('keeps toggles for surviving layers and shows layers added by a refetch', () => {
    const before = [layer({ id: 'l1' }), layer({ id: 'l2' })];
    const after = [layer({ id: 'l2' }), layer({ id: 'l3' })];
    const { result, rerender } = renderHook(
      ({ layers }) => useViewerLayers(layers, { mapKey: 'map-a' }),
      { initialProps: { layers: before } },
    );

    act(() => result.current.handleToggleVisibility('l2'));
    rerender({ layers: after });

    expect(result.current.visibleLayers).toEqual(new Set(['l3']));
  });

  it('does not revive a toggle for a deleted layer that returns', () => {
    const { result, rerender } = renderHook(
      ({ layers }) => useViewerLayers(layers, { mapKey: 'map-a' }),
      { initialProps: { layers: [layer({ id: 'l1' }), layer({ id: 'l2' })] } },
    );

    act(() => result.current.handleToggleVisibility('l1'));
    expect(result.current.visibleLayers).toEqual(new Set(['l2']));
    rerender({ layers: [layer({ id: 'l2' })] });
    expect(result.current.visibleLayers).toEqual(new Set(['l2']));
    rerender({ layers: [layer({ id: 'l1' }), layer({ id: 'l2' })] });
    expect(result.current.visibleLayers).toEqual(new Set(['l1', 'l2']));
  });
});
