import { render, screen, waitFor, within } from '@/test/test-utils';
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
    onRestoreLayers = vi.fn(),
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
    onRestoreLayers,
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
      // builder-audit #338 P1-13: AI filters are validated + normalized through the shared
      // filter contract before apply, so the legacy bare-field form is canonicalized.
      expect(props.onFilterChange).toHaveBeenCalledWith('layer-1', ['==', ['get', 'type'], 'park']);
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

  it('clamps AI opacity actions before dispatching them to layer controls', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [{ type: 'set_opacity', layer_id: 'layer-1', opacity: 1.8 }],
        },
      };
      yield { event: 'done', data: { explanation: 'Set opacity' } };
    });

    const user = userEvent.setup();
    const props = renderPanel({ onOpacityChange: vi.fn() });
    await typeAndSend(user, 'make it too opaque');

    await waitFor(() => {
      expect(props.onOpacityChange).toHaveBeenCalledWith('layer-1', 1);
    });
  });

  it('ignores malformed streamed actions payloads without falling back or mutating layers', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: { actions: null },
      };
      yield { event: 'done', data: { explanation: 'No valid actions' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'send malformed actions');

    expect(await screen.findByText('No valid actions')).toBeInTheDocument();
    expect(props.onPaintChange).not.toHaveBeenCalled();
    expect(props.onFilterChange).not.toHaveBeenCalled();
    expect(mockSendChat).not.toHaveBeenCalled();
  });

  it('CH-08: drops a streamed action with an unknown type while a sibling valid action still applies', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'toggle_visibility', layer_id: 'layer-1', visible: true },
            { type: 'not_a_real_action_type', layer_id: 'layer-1' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Mixed actions' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'send a mixed actions payload');

    await waitFor(() => {
      expect(props.onToggleVisibility).toHaveBeenCalledWith('layer-1', true);
    });
    expect(props.onPaintChange).not.toHaveBeenCalled();
    expect(props.onFilterChange).not.toHaveBeenCalled();
  });

  it('B-014: a streamed error event shows an inline error and does NOT retry via non-streaming', async () => {
    // Model emitted an SSE error event mid-stream (e.g. tool-loop exhausted).
    // The non-streaming sendChatMessage fallback must NOT fire — that would
    // double the (already-failed) LLM call.
    mockStreamChat.mockImplementation(async function* () {
      yield { event: 'error', data: { message: 'tool loop exhausted' } };
    });

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'trigger a model error');

    expect(await screen.findByText('Something went wrong. Please try again.')).toBeInTheDocument();
    expect(mockSendChat).not.toHaveBeenCalled();
  });

  it('a streamed error event WITH an HTTP status classifies by status (403 → forbidden banner), not a generic retry', async () => {
    // A pre-flight HTTPException from the SSE endpoint carries a numeric `status`
    // (the SSE body is always a 200 stream). It must classify like the
    // non-streaming path — 403 → sticky forbidden banner — instead of collapsing
    // to the generic retryable "Something went wrong" inline bubble. It must also
    // NOT fall through to the non-streaming retry (no double LLM call).
    mockStreamChat.mockImplementation(async function* () {
      yield { event: 'error', data: { message: 'You do not own this map', status: 403 } };
    });

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'edit a map I cannot edit');

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/permission/i);
    expect(mockSendChat).not.toHaveBeenCalled();
  });

  it('ignores malformed style paint payloads instead of applying indexed string keys', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'set_style', layer_id: 'layer-1', paint: 'red' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Ignored malformed paint' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'style malformed');

    expect(await screen.findByText('Ignored malformed paint')).toBeInTheDocument();
    expect(props.onPaintChange).not.toHaveBeenCalled();
  });

  it('CH-07: a no-op set_style (empty paint) records zero applied actions and renders no Applied N changes / Undo', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'set_style', layer_id: 'layer-1', paint: {} },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'No changes to apply' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'style nothing');

    expect(await screen.findByText('No changes to apply')).toBeInTheDocument();
    expect(props.onPaintChange).not.toHaveBeenCalled();
    expect(screen.queryByText(/applied/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /undo/i })).not.toBeInTheDocument();
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

  it('undo restores the last AI mutation snapshot for existing layers', async () => {
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
    const originalLayer = makeLayer({
      paint: { 'fill-color': '#111827', 'fill-opacity': 0.4 },
      filter: ['==', ['get', 'type'], 'park'],
      label_config: { column: 'name' },
      style_config: { mode: 'categorical', column: 'type', ramp: 'Viridis' },
      visible: false,
      opacity: 0.35,
    });
    const props = renderPanel({
      layers: [originalLayer],
      onOpacityChange: vi.fn(),
    });

    await typeAndSend(user, 'make it red');

    await waitFor(() => {
      expect(props.onPaintChange).toHaveBeenCalledWith('layer-1', {
        'fill-color': '#ff0000',
        'fill-opacity': 0.4,
      });
    });

    await user.click(await screen.findByRole('button', { name: /undo/i }));

    // Undo restores the full pre-mutation snapshot in a SINGLE atomic call.
    // (Restoring field-by-field clobbered earlier reverts — a later partial
    // update re-stamped stale label_config/paint and the change visibly stuck.)
    const restoreFn = vi.mocked(props.onRestoreLayers);
    expect(restoreFn).toHaveBeenCalledTimes(1);
    const restored = restoreFn.mock.calls[0][0];
    expect(restored).toHaveLength(1);
    expect(restored[0]).toMatchObject({
      id: 'layer-1',
      paint: originalLayer.paint,
      filter: originalLayer.filter,
      label_config: originalLayer.label_config,
      visible: false,
      style_config: originalLayer.style_config,
      opacity: 0.35,
    });
    // The clobbering per-field restore handlers are no longer used by undo.
    expect(props.onStyleConfigChange).not.toHaveBeenCalled();
    expect(props.onLabelChange).not.toHaveBeenCalled();
  });

  it('STALE-01: a query-only turn after a style edit does not leave a stale undo button', async () => {
    mockStreamChat
      .mockImplementationOnce(async function* () {
        yield {
          event: 'actions',
          data: { actions: [{ type: 'set_style', layer_id: 'layer-1', paint: { 'fill-color': '#ff0000' } }] },
        };
        yield { event: 'done', data: { explanation: 'Styled' } };
      })
      .mockImplementationOnce(async function* () {
        yield {
          event: 'actions',
          data: { actions: [{ type: 'show_query_result', rows: [['x']], columns: ['name'], row_count: 1 }] },
        };
        yield { event: 'done', data: { explanation: 'Here are your results' } };
      });

    const user = userEvent.setup();
    renderPanel();

    await typeAndSend(user, 'make it red');
    expect(await screen.findByText('Styled')).toBeInTheDocument();
    // Undo is offered after a replay-safe style turn.
    expect(await screen.findByRole('button', { name: /undo/i })).toBeInTheDocument();

    await typeAndSend(user, 'how many parks');
    expect(await screen.findByText('Here are your results')).toBeInTheDocument();

    // STALE-01: the snapshot is reset at the start of every turn, so the query-only
    // turn (which captures no snapshot) cannot leave a stale Undo button that would
    // revert the earlier, unrelated style edit.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /undo/i })).not.toBeInTheDocument();
    });
  });

  it('Applied-N nit: a pure query-result turn does not render "Applied N changes"', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: { actions: [{ type: 'show_query_result', rows: [['x']], columns: ['name'], row_count: 1 }] },
      };
      yield { event: 'done', data: { explanation: 'Results' } };
    });
    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'how many parks');
    expect(await screen.findByText('Results')).toBeInTheDocument();
    // show_query_result mutates nothing — the "Applied N changes" line must not appear.
    expect(screen.queryByText(/applied/i)).not.toBeInTheDocument();
  });

  it('P1-13: an invalid AI set_filter expression is rejected and never applied', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        // Legacy bare-field "in" form — rejected by the shared filter validator.
        data: { actions: [{ type: 'set_filter', layer_id: 'layer-1', expression: ['in', 'type', 'a', 'b'] }] },
      };
      yield { event: 'done', data: { explanation: 'Tried to filter' } };
    });
    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'filter');
    expect(await screen.findByText('Tried to filter')).toBeInTheDocument();
    expect(props.onFilterChange).not.toHaveBeenCalled();
    // CH-07: a rejected filter is intent, not effect — it must not inflate the applied count.
    expect(screen.queryByText(/applied/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /undo/i })).not.toBeInTheDocument();
  });

  it('P1-13: a valid compound AI set_filter expression is applied', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [{
            type: 'set_filter',
            layer_id: 'layer-1',
            expression: ['all', ['==', ['get', 'type'], 'park'], ['>', ['get', 'area'], 10]],
          }],
        },
      };
      yield { event: 'done', data: { explanation: 'Filtered' } };
    });
    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'filter');
    await waitFor(() => {
      expect(props.onFilterChange).toHaveBeenCalledWith('layer-1', [
        'all', ['==', ['get', 'type'], 'park'], ['>', ['get', 'area'], 10],
      ]);
    });
  });

  it('does not offer undo for remove_layer actions (requires staging accept)', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'remove_layer', layer_id: 'layer-1' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Removed' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'remove the layer');

    // Phase 1135 AI-01: remove_layer is a destructive action — it goes into the staging
    // buffer and only dispatches after the user accepts. Accept it first.
    const acceptAll = await screen.findByRole('button', { name: /accept all/i });
    await user.click(acceptAll);

    await waitFor(() => {
      expect(props.onRemove).toHaveBeenCalledWith('layer-1');
    });
    expect(await screen.findByText('Removed')).toBeInTheDocument();
    // Undo is not offered for remove_layer (supportsUndo was false before staging;
    // staging accept goes through handleChatAction which sets supportsUndo=false).
    expect(screen.queryByRole('button', { name: /undo/i })).not.toBeInTheDocument();
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
    { status: 502, expected: /unavailable/i },
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

  it.each([
    { status: 403, expectedBanner: /permission/i },
    { status: 503, expectedBanner: /unavailable/i },
  ])(
    'WR-03: ApiError status $status via fallback routes to sticky banner, not inline bubble',
    async ({ status, expectedBanner }) => {
      // Stream fails with generic error, then fallback also fails with ApiError
      // eslint-disable-next-line require-yield
      mockStreamChat.mockImplementation(async function* () {
        throw new Error('stream failed');
      });
      mockSendChat.mockRejectedValue(new ApiError('error', status));

      const user = userEvent.setup();
      renderPanel();
      await typeAndSend(user, 'trigger error');

      // Should show sticky banner (role="alert"), not inline error bubble
      const banner = await screen.findByRole('alert');
      expect(banner).toBeInTheDocument();
      expect(banner).toHaveTextContent(expectedBanner);
    },
  );
});

describe('ChatPanel — confirm-before-apply staging (Phase 1135 AI-01 / AI-09)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('AI-01: rejecting the staging tray leaves layers byte-equal to pre-prompt — onAddDataset and onRemove NOT called', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'add_layer', dataset_id: 'ds-new', dataset_name: 'NYC Subway' },
            { type: 'remove_layer', layer_id: 'layer-1' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Two staged changes' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'add subway and remove polygons');

    // Wait for the staging tray to render
    const rejectAllBtn = await screen.findByRole('button', { name: /reject all/i });
    expect(rejectAllBtn).toBeInTheDocument();

    // No mutations should have fired yet — buffer is pre-flush
    expect(props.onAddDataset).not.toHaveBeenCalled();
    expect(props.onRemove).not.toHaveBeenCalled();

    await user.click(rejectAllBtn);

    // After reject: tray gone, NO mutations fired
    expect(screen.queryByRole('button', { name: /reject all/i })).not.toBeInTheDocument();
    expect(props.onAddDataset).not.toHaveBeenCalled();
    expect(props.onRemove).not.toHaveBeenCalled();
  });

  it('AI-01: acceptOne dispatches exactly one action and leaves remaining pending', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'add_layer', dataset_id: 'ds-A', dataset_name: 'A' },
            { type: 'add_layer', dataset_id: 'ds-B', dataset_name: 'B' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Two adds' } };
    });

    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'add A and B');

    // Per-chip Accept buttons render text "Accept" (capital A, exact);
    // "Accept all" is the accept-all button — filter it out by exact text match.
    await screen.findByRole('button', { name: /accept all/i }); // wait for tray to render
    const allButtons = screen.getAllByRole('button');
    const acceptButtons = allButtons.filter(
      (btn) => btn.textContent?.trim() === 'Accept',
    );
    expect(acceptButtons.length).toBe(2);

    await user.click(acceptButtons[0]);
    await waitFor(() => {
      expect(props.onAddDataset).toHaveBeenCalledTimes(1);
      expect(props.onAddDataset).toHaveBeenCalledWith('ds-A');
    });
    // One chip remains — one per-chip Accept button still visible
    const remaining = screen.getAllByRole('button').filter(
      (btn) => btn.textContent?.trim() === 'Accept',
    );
    expect(remaining.length).toBe(1);
  });

  it('AI-01: acceptAll dispatches all pending actions in order', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'add_layer', dataset_id: 'ds-A', dataset_name: 'A' },
            { type: 'remove_layer', layer_id: 'layer-1' },
            { type: 'add_layer', dataset_id: 'ds-C', dataset_name: 'C' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Three staged' } };
    });
    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'do three things');
    const acceptAll = await screen.findByRole('button', { name: /accept all/i });
    await user.click(acceptAll);
    await waitFor(() => {
      expect(props.onAddDataset).toHaveBeenCalledTimes(2);
      expect(props.onRemove).toHaveBeenCalledTimes(1);
    });
    // Order — first call to onAddDataset is 'ds-A', second is 'ds-C'
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const addCalls = (props.onAddDataset as any).mock.calls as [string][];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const removeCalls = (props.onRemove as any).mock.calls as [string][];
    expect(addCalls[0][0]).toBe('ds-A');
    expect(addCalls[1][0]).toBe('ds-C');
    expect(removeCalls[0][0]).toBe('layer-1');
  });

  it('AI-09: staging tray renders for add_layer + remove_layer; chip text format matches UI-SPEC', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'add_layer', dataset_id: 'ds-2', dataset_name: 'NYC Subway' },
            { type: 'remove_layer', layer_id: 'layer-1' },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Two staged' } };
    });
    const user = userEvent.setup();
    renderPanel({
      layers: [makeLayer({ id: 'layer-1', display_name: 'Counties', dataset_feature_count: 5 })],
    });
    await typeAndSend(user, 'change some layers');
    // add_layer chip — name appears
    expect(await screen.findByText(/Add "NYC Subway"/)).toBeInTheDocument();
    // remove_layer chip — feature count appears
    expect(await screen.findByText(/Remove "Counties" \(5 features\)/)).toBeInTheDocument();
  });

  it('AI-09 negative control: set_style action does NOT trigger the staging tray — dispatches immediately', async () => {
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
    const props = renderPanel();
    await typeAndSend(user, 'make it red');
    await waitFor(() => {
      expect(props.onPaintChange).toHaveBeenCalledTimes(1);
    });
    // Negative control: no staging tray for non-destructive actions
    expect(screen.queryByRole('button', { name: /accept all/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reject all/i })).not.toBeInTheDocument();
  });
});

describe('ChatPanel — inline data-analysis card (Phase 1135 AI-08)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('renders inline table card when show_query_result returns rows', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              // Real backend contract: rows are arrays of cell values paired
              // with a separate `columns` array (chat_geojson.py: list[list]).
              columns: ['county', 'area_sqkm', 'population'],
              rows: [
                ['Essex', 4853, 38000],
                ['Hamilton', 4757, 4400],
              ],
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Top 2 counties' } };
    });
    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'biggest counties');
    expect(await screen.findByText(/Essex/)).toBeInTheDocument();
    expect(await screen.findByText(/Hamilton/)).toBeInTheDocument();
    // Scroll region with aria-label should exist
    expect(await screen.findByRole('region', { name: /query result table/i })).toBeInTheDocument();
  });

  it('renders empty-state when show_query_result returns rows: []', async () => {
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: { actions: [{ type: 'show_query_result', rows: [] }] },
      };
      yield { event: 'done', data: { explanation: 'No results' } };
    });
    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'find non-existent thing');
    expect(await screen.findByText(/no rows/i)).toBeInTheDocument();
    expect(await screen.findByText(/broader area or different filter/i)).toBeInTheDocument();
  });

  it('caps visible columns at 5 and shows ellipsis indicator when more exist', async () => {
    const wideColumns = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];
    const wideRow = [1, 2, 3, 4, 5, 6, 7];
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: { actions: [{ type: 'show_query_result', columns: wideColumns, rows: [wideRow] }] },
      };
      yield { event: 'done', data: { explanation: 'Wide row' } };
    });
    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'wide query');
    // First 5 columns visible as headers
    await screen.findByRole('region', { name: /query result table/i });
    const headers = screen.getAllByRole('columnheader');
    // 5 visible column headers + 1 "more columns" indicator = 6 total
    expect(headers.length).toBe(6);
    // The … indicator has aria-label "more columns"
    expect(screen.getByLabelText(/more columns/i)).toBeInTheDocument();
  });

  it('show_query_result with only geojson + bbox (no rows) calls onQueryResult and does NOT render inline card', async () => {
    const geojson = { type: 'FeatureCollection', features: [] };
    const bbox = [-74, 40, -73, 41];
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: { actions: [{ type: 'show_query_result', geojson, bbox }] },
      };
      yield { event: 'done', data: { explanation: 'Spatial result' } };
    });
    const user = userEvent.setup();
    const props = renderPanel();
    await typeAndSend(user, 'find spatial features');
    await waitFor(() => {
      expect(props.onQueryResult).toHaveBeenCalledWith(geojson, bbox);
    });
    // Negative control — no inline card when rows is absent
    expect(screen.queryByRole('region', { name: /query result table/i })).not.toBeInTheDocument();
  });
});

describe('ChatPanel — recoverable error banner (Phase 1135 AI-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('503 surfaces sticky banner with Retry button; Retry re-fires the last user message', async () => {
    // eslint-disable-next-line require-yield
    mockStreamChat.mockImplementationOnce(async function* () {
      throw new ApiError('AI unavailable', 503);
    });
    mockSendChat.mockRejectedValue(new ApiError('AI unavailable', 503));

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'broken request');

    // Banner appears
    const banner = await screen.findByRole('alert');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/AI is unavailable/i);
    const retryBtn = within(banner).getByRole('button', { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();
    // Inline error bubble suppressed — no Retry button OUTSIDE the alert region
    const allRetryButtons = screen.getAllByRole('button', { name: /retry/i });
    expect(allRetryButtons.length).toBe(1); // exactly the banner Retry

    // Retry re-fills the input
    await user.click(retryBtn);
    const input = screen.getByPlaceholderText(/describe a map change/i) as HTMLTextAreaElement;
    expect(input.value).toBe('broken request');
    // Banner cleared
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('403 surfaces sticky banner with Dismiss button; NO Retry button', async () => {
    // eslint-disable-next-line require-yield
    mockStreamChat.mockImplementationOnce(async function* () {
      throw new ApiError('forbidden', 403);
    });
    mockSendChat.mockRejectedValue(new ApiError('forbidden', 403));

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'forbidden request');

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/AI access lost/i);
    // No Retry button anywhere
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
    // Dismiss button present
    const dismiss = within(banner).getByRole('button', { name: /dismiss/i });
    await user.click(dismiss);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('401 falls through to existing inline error bubble — banner NOT rendered', async () => {
    // eslint-disable-next-line require-yield
    mockStreamChat.mockImplementationOnce(async function* () {
      throw new ApiError('session expired', 401);
    });
    mockSendChat.mockRejectedValue(new ApiError('session expired', 401));

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'test-auth-401');

    // No banner
    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    // Existing inline error bubble path renders the session-expired text (t('chat.errorSessionExpired'))
    expect(await screen.findByText(/please log in again|session expired\. please/i)).toBeInTheDocument();
  });

  it('network error falls through to existing inline error bubble — banner NOT rendered', async () => {
    // eslint-disable-next-line require-yield
    mockStreamChat.mockImplementationOnce(async function* () {
      throw new Error('Network unreachable');
    });
    mockSendChat.mockRejectedValue(new Error('Network unreachable'));

    const user = userEvent.setup();
    renderPanel();
    await typeAndSend(user, 'network drops');

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    // Existing inline error bubble renders the generic friendly error
    const errorMessage = await screen.findByText(/something went wrong|trouble|try again|error/i);
    expect(errorMessage).toBeInTheDocument();
  });
});
