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
});
