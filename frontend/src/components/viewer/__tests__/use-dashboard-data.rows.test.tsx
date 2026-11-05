import { act, waitFor } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { fetchAggregate } from '@/api/aggregate';
import { getWidgetDefinition } from '@/components/widgets/registry';
import type { WidgetInstance } from '@/components/widgets/contract';
import type { SharedLayerResponse } from '@/types/api';
import { useWidgetAggregate } from '../hooks/use-dashboard-data';

vi.mock('@/api/aggregate', () => ({ fetchAggregate: vi.fn() }));

const fetchMock = vi.mocked(fetchAggregate);
const definition = getWidgetDefinition('feature_list', 'dashboard')!;
const layer = {
  id: 'layer-1',
  dataset_id: 'dataset-1',
  geometry_type: 'POINT',
  column_info: [{ name: 'name', type: 'text' }],
} as unknown as SharedLayerResponse;
const instance = {
  id: 'w1',
  type: 'feature_list',
  v: 1,
  layer_id: 'layer-1',
  scope: 'layer',
  config: { title_column: 'name', subtitle_column: null, sort_column: null, sort: 'asc', page_size: 10 },
} as WidgetInstance;

const firstPage = {
  op: 'rows',
  approximate: false,
  cached: false,
  result: { rows: [{ gid: 1, values: { name: 'A' } }], next_cursor: 'c1', has_more: true },
};

describe('useWidgetAggregate with a rows widget', () => {
  it('offers no next page while a refresh of the pages is on its way', async () => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(firstPage as never);
    const { result } = renderHook(() => useWidgetAggregate({ instance, definition, layer, viewBbox: null }));
    await waitFor(() => expect(result.current.loadMore).toBeDefined());

    let finish!: (value: never) => void;
    fetchMock.mockReturnValue(new Promise<never>((resolve) => (finish = resolve)));
    act(() => void result.current.query.refetch());
    await waitFor(() => expect(result.current.query.isFetching).toBe(true));
    expect(result.current.loadMore).toBeUndefined();

    finish(firstPage as never);
    await waitFor(() => expect(result.current.loadMore).toBeDefined());
  });
});
