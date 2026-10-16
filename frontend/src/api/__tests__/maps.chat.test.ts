import { sendChatMessage } from '../maps';
import { apiFetch } from '../client';
import type { MapLayerResponse } from '@/types/api';

vi.mock('../client', async () => {
  const actual = await vi.importActual<typeof import('../client')>('../client');
  return { ...actual, apiFetch: vi.fn() };
});

const mockApiFetch = vi.mocked(apiFetch);

function layer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Parks',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'parks',
    dataset_extent_bbox: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    show_in_legend: true,
    ...overrides,
  };
}

describe('sendChatMessage', () => {
  beforeEach(() => {
    mockApiFetch.mockReset();
    mockApiFetch.mockResolvedValue({});
  });

  it('sends null column_info for a layer whose dataset reports no columns', async () => {
    await sendChatMessage('map-1', 'hello', [layer()]);

    const init = mockApiFetch.mock.calls[0][1] as { body: string };
    const [sent] = JSON.parse(init.body).layers;
    expect(sent.column_info).toBeNull();
  });
});
