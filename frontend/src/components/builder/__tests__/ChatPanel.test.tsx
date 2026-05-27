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

    expect(props.onPaintChange).toHaveBeenLastCalledWith('layer-1', originalLayer.paint);
    expect(props.onFilterChange).toHaveBeenCalledWith('layer-1', originalLayer.filter);
    expect(props.onLabelChange).toHaveBeenCalledWith('layer-1', originalLayer.label_config);
    expect(props.onToggleVisibility).toHaveBeenCalledWith('layer-1', false);
    expect(props.onStyleConfigChange).toHaveBeenCalledWith('layer-1', originalLayer.style_config, originalLayer.paint);
    expect(props.onOpacityChange).toHaveBeenCalledWith('layer-1', 0.35);
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
              rows: [
                { county: 'Essex', area_sqkm: 4853, population: 38000 },
                { county: 'Hamilton', area_sqkm: 4757, population: 4400 },
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
    const wideRow: Record<string, number> = { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 };
    mockStreamChat.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: { actions: [{ type: 'show_query_result', rows: [wideRow] }] },
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
