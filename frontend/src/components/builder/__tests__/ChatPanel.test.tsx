import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { sendChatMessage, streamChatMessage } from '@/api/maps';
import { ApiError } from '@/api/client';
import { ChatPanel, type LayerActions } from '../ChatPanel';
import type { MapLayerResponse } from '@/types/api';

// scrollIntoView is not available in jsdom
Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/api/maps', () => ({
  sendChatMessage: vi.fn(),
  streamChatMessage: vi.fn(),
}));

const mockStreamChat = vi.mocked(streamChatMessage);
const mockSendChat = vi.mocked(sendChatMessage);

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test Dataset',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    ...overrides,
  };
}

function renderPanel(
  propOverrides: Partial<React.ComponentProps<typeof ChatPanel>> & Partial<LayerActions> = {},
) {
  const {
    onFilterChange = vi.fn(),
    onPaintChange = vi.fn(),
    onStyleConfigChange = vi.fn(),
    onLabelChange = vi.fn(),
    onToggleVisibility = vi.fn(),
    onAddDataset = vi.fn(),
    onRemove = vi.fn(),
    onOpacityChange,
    ...rest
  } = propOverrides;
  const layerActions = {
    onFilterChange,
    onPaintChange,
    onStyleConfigChange,
    onLabelChange,
    onToggleVisibility,
    onAddDataset,
    onRemove,
    ...(onOpacityChange ? { onOpacityChange } : {}),
  };
  const props = {
    mapId: 'map-1',
    layers: [makeLayer()],
    layerActions,
    onQueryResult: vi.fn(),
    ...rest,
  };
  render(<ChatPanel {...props} />);
  return { ...layerActions, ...props };
}

async function typeAndSend(
  user: ReturnType<typeof userEvent.setup>,
  text: string,
) {
  const input = screen.getByPlaceholderText(/describe a map change/i);
  await user.type(input, text);
  await user.click(screen.getByRole('button', { name: /send/i }));
}

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('passes explicit visible value to onToggleVisibility', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'toggle_visibility', layer_id: 'layer-1', visible: true },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Toggled' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'show the layer');

    await waitFor(() => {
      expect(props.onToggleVisibility).toHaveBeenCalledWith('layer-1', true);
    });
  });

  it('calls onQueryResult for show_query_result actions', async () => {
    const geojson = { type: 'FeatureCollection', features: [] };
    const bbox = [-74, 40, -73, 41];

    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [{ type: 'show_query_result', geojson, bbox }],
        },
      };
      yield { event: 'done', data: { explanation: 'Results' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'find features');

    await waitFor(() => {
      expect(props.onQueryResult).toHaveBeenCalledWith(geojson, bbox);
    });
  });

  it('shows cancel button while loading and hides send button', async () => {
    let resolve!: () => void;
    const hang = new Promise<void>((r) => {
      resolve = r;
    });

    // eslint-disable-next-line require-yield
    mockStreamChat.mockImplementation(async function* () {
      await hang;
    });

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'slow request');

    expect(
      screen.getByRole('button', { name: /cancel/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /send/i }),
    ).not.toBeInTheDocument();

    resolve();
  });

  it('streaming happy path applies actions and shows explanation', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'set_filter', layer_id: 'layer-1', expression: ['==', 'type', 'park'] },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Filtered to parks' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'filter to parks');

    await waitFor(() => {
      expect(props.onFilterChange).toHaveBeenCalledWith('layer-1', ['==', 'type', 'park']);
    });
    expect(await screen.findByText('Filtered to parks')).toBeInTheDocument();
  });

  it('passes raw user message to streamChatMessage without enrichment', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield { event: 'done', data: { explanation: 'ok' } };
    });

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'color @Parks red');

    await waitFor(() => {
      expect(mockStreamChat).toHaveBeenCalledTimes(1);
    });
    // First arg is mapId, second is message — should be raw text, no [Context:] or [Intent:]
    const message = mockStreamChat.mock.calls[0][1];
    expect(message).toBe('color @Parks red');
    expect(message).not.toContain('[Context:');
    expect(message).not.toContain('[Intent:');
  });

  it('dispatches set_opacity to onOpacityChange', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [{ type: 'set_opacity', layer_id: 'layer-1', opacity: 0.5 }],
        },
      };
      yield { event: 'done', data: { explanation: 'Set opacity' } };
    });

    const user = userEvent.setup();
    const props = renderPanel({ onOpacityChange: vi.fn() });
    await typeAndSend(user, 'make it transparent');

    await waitFor(() => {
      expect(props.onOpacityChange).toHaveBeenCalledWith('layer-1', 0.5);
    });
  });

  it('patches set_style paint into the current layer paint', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'set_style', layer_id: 'layer-1', paint: { 'fill-color': '#ff0000' } },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Styled' } };
    });

    const user = userEvent.setup();
    const props = renderPanel({
      layers: [makeLayer({ paint: { 'fill-opacity': 0.45, 'fill-outline-color': '#111827' } })],
    });
    await typeAndSend(user, 'make it red');

    await waitFor(() => {
      expect(props.onPaintChange).toHaveBeenCalledWith('layer-1', {
        'fill-opacity': 0.45,
        'fill-outline-color': '#111827',
        'fill-color': '#ff0000',
      });
    });
  });

  it('clears explicit set_style paint properties after patching', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'set_style',
              layer_id: 'layer-1',
              paint: { 'line-color': '#f97316' },
              clear_paint: ['line-gradient'],
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Solid' } };
    });

    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const user = userEvent.setup();
    const props = renderPanel({
      layers: [makeLayer({
        dataset_geometry_type: 'LineString',
        paint: { 'line-color': '#111827', 'line-width': 4, 'line-gradient': gradient },
      })],
    });
    await typeAndSend(user, 'make the trail solid orange');

    await waitFor(() => {
      expect(props.onPaintChange).toHaveBeenCalledWith('layer-1', {
        'line-color': '#f97316',
        'line-width': 4,
      });
    });
  });

  it('honors replace_paint for set_style full replacement', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'set_style',
              layer_id: 'layer-1',
              paint: { 'fill-color': '#22c55e' },
              replace_paint: true,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Replaced' } };
    });

    const user = userEvent.setup();
    const props = renderPanel({
      layers: [makeLayer({ paint: { 'fill-opacity': 0.45, 'fill-outline-color': '#111827' } })],
    });
    await typeAndSend(user, 'replace style');

    await waitFor(() => {
      expect(props.onPaintChange).toHaveBeenCalledWith('layer-1', {
        'fill-color': '#22c55e',
      });
    });
  });

  it('does not re-apply actions when streaming partially succeeds then fails', async () => {
    // Stream applies one action then throws
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'set_style', layer_id: 'layer-1', paint: { 'fill-color': 'red' } },
          ],
        },
      };
      throw new Error('stream interrupted mid-response');
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'style it red');

    await waitFor(() => {
      expect(props.onPaintChange).toHaveBeenCalledTimes(1);
    });

    // Non-streaming fallback should NOT have been called
    expect(mockSendChat).not.toHaveBeenCalled();

    // Stream interrupted message should appear
    expect(await screen.findByText(/interrupted/i)).toBeInTheDocument();
  });

  it('shows specific error when stream returns ApiError without fallback', async () => {
    // Stream fails with a 403 ApiError — should show permission error directly
    // eslint-disable-next-line require-yield
    mockStreamChat.mockImplementation(async function* () {
      throw new ApiError('Forbidden', 403);
    });

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'do something');

    expect(await screen.findByText(/permission/i)).toBeInTheDocument();
    // Should NOT have fallen back to non-streaming
    expect(mockSendChat).not.toHaveBeenCalled();
  });

  it('dispatches set_data_driven_style to onStyleConfigChange with paint and config', async () => {
    const stepExpr = ['step', ['get', 'acres'], '#ffffcc', 100, '#41b6c4', 500, '#253494'];
    const styleConfig = { mode: 'graduated', column: 'acres', ramp: 'YlGnBu', method: 'quantile', breaks: [] };

    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'set_data_driven_style',
              layer_id: 'layer-1',
              paint: { 'fill-color': stepExpr },
              style_config: styleConfig,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Styled by acres' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'color by acres');

    await waitFor(() => {
      expect(props.onStyleConfigChange).toHaveBeenCalledWith(
        'layer-1',
        styleConfig,
        { 'fill-color': stepExpr },
      );
    });
    expect(props.onPaintChange).not.toHaveBeenCalled();
  });

  it('merges set_data_driven_style paint into current layer paint', async () => {
    const stepExpr = ['step', ['get', 'acres'], '#ffffcc', 100, '#41b6c4', 500, '#253494'];
    const styleConfig = { mode: 'graduated', column: 'acres', ramp: 'YlGnBu', method: 'quantile', breaks: [] };

    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'set_data_driven_style',
              layer_id: 'layer-1',
              paint: { 'fill-color': stepExpr },
              style_config: styleConfig,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Styled by acres' } };
    });

    const user = userEvent.setup();
    const props = renderPanel({
      layers: [makeLayer({ paint: { 'fill-opacity': 0.45, 'fill-outline-color': '#111827' } })],
    });
    await typeAndSend(user, 'color by acres');

    await waitFor(() => {
      expect(props.onStyleConfigChange).toHaveBeenCalledWith(
        'layer-1',
        styleConfig,
        {
          'fill-opacity': 0.45,
          'fill-outline-color': '#111827',
          'fill-color': stepExpr,
        },
      );
    });
  });

  it.each([
    { status: 401, expected: /session expired/i },
    { status: 403, expected: /permission/i },
    { status: 502, expected: /unavailable/i },
    { status: 503, expected: /unavailable/i },
  ])(
    'shows specific error for ApiError status $status via fallback',
    async ({ status, expected }) => {
      // Stream fails with generic error, then fallback also fails with ApiError
      // eslint-disable-next-line require-yield
      mockStreamChat.mockImplementation(async function* () {
        throw new Error('stream failed');
      });
      mockSendChat.mockRejectedValue(new ApiError('error', status));

      const user = userEvent.setup();
      renderPanel();
      await typeAndSend(user, 'trigger error');

      expect(await screen.findByText(expected)).toBeInTheDocument();
    },
  );
});
