import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { streamChatMessage } from '@/api/maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useEphemeralLayers } from '@/components/builder/hooks/use-ephemeral-layers';
import { ViewerChatPanel } from '../ViewerChatPanel';
import type { MapLayerResponse } from '@/types/api';

// scrollIntoView is not available in jsdom
Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/api/maps', () => ({ streamChatMessage: vi.fn() }));
vi.mock('@/hooks/use-ai-availability', () => ({ useAIAvailability: vi.fn() }));
vi.mock('@/components/builder/hooks/use-ephemeral-layers', () => ({ useEphemeralLayers: vi.fn() }));

const mockStream = vi.mocked(streamChatMessage);
const mockAvailability = vi.mocked(useAIAvailability);
const mockEphemeral = vi.mocked(useEphemeralLayers);
const handleQueryResult = vi.fn();

function setAvailable(available: boolean) {
  // Only the isAIAvailable field is read by the component.
  mockAvailability.mockReturnValue({ isAIAvailable: available } as ReturnType<typeof useAIAvailability>);
}

/** One overlay feature. feat(#1241 codex r1): overlay completeness is judged
 *  against row_count, so a fixture's feature COUNT is now load-bearing. */
function feature() {
  return { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.9, 40.8] }, properties: {} };
}

function renderPanel() {
  const mapInstanceRef = { current: null };
  return render(
    <ViewerChatPanel mapId="map-1" layers={[] as MapLayerResponse[]} mapInstanceRef={mapInstanceRef} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockEphemeral.mockReturnValue({
    ephemeralResult: null,
    handleQueryResult,
    handleDismissEphemeral: vi.fn(),
  });
});

describe('ViewerChatPanel', () => {
  it('fix(#542): shows a dismissible query-result badge when the overlay is active', async () => {
    setAvailable(true);
    const handleDismissEphemeral = vi.fn();
    mockEphemeral.mockReturnValue({
      ephemeralResult: {
        geojson: {
          type: 'FeatureCollection',
          features: [
            { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} },
            { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 1] }, properties: {} },
          ],
        },
        bbox: [0, 0, 1, 1],
      },
      handleQueryResult,
      handleDismissEphemeral,
    });

    renderPanel();

    // fix(#674 audit): the badge labels analysis previews as well as query
    // results, so its copy is operation-neutral ("Result", not "Query result").
    expect(screen.getByText(/Result/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss result' }));
    expect(handleDismissEphemeral).toHaveBeenCalled();
  });

  it('renders nothing when AI is unavailable (anon / no use_ai_chat)', () => {
    setAvailable(false);
    renderPanel();
    expect(screen.queryByRole('button', { name: 'Ask AI' })).toBeNull();
  });

  it('opens the panel and streams a read-only answer', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield { event: 'token', data: { text: 'You are viewing read-only.' } };
      yield { event: 'done', data: { explanation: 'You are viewing read-only.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));

    const input = screen.getByPlaceholderText('Ask about this map...');
    await userEvent.type(input, 'what is here?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('You are viewing read-only.');
    expect(mockStream).toHaveBeenCalledWith('map-1', 'what is here?', [], expect.any(String), [], expect.any(AbortSignal));
  });

  it('flies the map to a show_query_result and renders its table', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              geojson: { type: 'FeatureCollection', features: [feature()] },
              bbox: [-1, -1, 1, 1],
              rows: [['Alpha', 10]],
              columns: ['name', 'count'],
              row_count: 1,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Found 1 result.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this map...'), 'count features');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Found 1 result.');
    expect(handleQueryResult).toHaveBeenCalledWith(
      { type: 'FeatureCollection', features: [feature()] },
      [-1, -1, 1, 1],
      {},
    );
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('1 row')).toBeInTheDocument();
  });

  // fix(#1076): the viewer is the surface an embed or a shared link lands on,
  // so a silent truncation here reaches the widest audience. A clip reports no
  // source total, and requiring one dropped the flag before the badge saw it.
  it('forwards a cap that arrives without a total', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              geojson: { type: 'FeatureCollection', features: [] },
              bbox: [-1, -1, 1, 1],
              truncated: true,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Clipped.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(
      screen.getByPlaceholderText('Ask about this map...'),
      'clip the buildings',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Clipped.');
    expect(handleQueryResult).toHaveBeenCalledWith(
      { type: 'FeatureCollection', features: [] },
      [-1, -1, 1, 1],
      { truncated: true },
    );
  });

  // feat(#1241 codex r1): one feature per matched row is what "uncapped" means.
  // The server never emits an empty FeatureCollection (_extract_geojson returns
  // None when no row is mappable), so features:[] with row_count: 12 described
  // an impossible state that now reads, correctly, as a clipped overlay.
  it('forwards no truncation for an uncapped result', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              geojson: { type: 'FeatureCollection', features: [feature()] },
              bbox: [-1, -1, 1, 1],
              row_count: 1,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Clipped.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(
      screen.getByPlaceholderText('Ask about this map...'),
      'clip the buildings',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Clipped.');
    expect(handleQueryResult).toHaveBeenCalledWith(
      { type: 'FeatureCollection', features: [feature()] },
      [-1, -1, 1, 1],
      {},
    );
  });

  // The embed/shared-link surface must disclose a clipped overlay even when the
  // SQL row cap never bit: the server slices the FeatureCollection to its own
  // render budget afterwards, so `truncated: false` says nothing about it.
  it('discloses an overlay clipped below row_count even with truncated false', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              geojson: { type: 'FeatureCollection', features: [feature()] },
              bbox: [-1, -1, 1, 1],
              truncated: false,
              row_count: 300,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Found 300.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(
      screen.getByPlaceholderText('Ask about this map...'),
      'show me every park',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Found 300.');
    expect(handleQueryResult).toHaveBeenCalledWith(
      { type: 'FeatureCollection', features: [feature()] },
      [-1, -1, 1, 1],
      { truncated: true, totalCount: 300 },
    );
  });

  it('applies only the winning (last) query result — no stale flyover (#534)', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            // Superseded spatial result: its flyover must NOT fire...
            {
              type: 'show_query_result',
              geojson: { type: 'FeatureCollection', features: [] },
              bbox: [-1, -1, 1, 1],
              rows: [],
              columns: ['name'],
            },
            // ...the retried non-spatial result is what the table shows.
            { type: 'show_query_result', rows: [[496]], columns: ['count'], row_count: 1 },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Counted on retry.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this map...'), 'count features');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Counted on retry.');
    expect(handleQueryResult).not.toHaveBeenCalled();
    expect(screen.getByText('496')).toBeInTheDocument();
  });

  it('clears the stale overlay when the winning result has no geometry (#676)', async () => {
    setAvailable(true);
    const handleDismissEphemeral = vi.fn();
    mockEphemeral.mockReturnValue({
      ephemeralResult: null,
      handleQueryResult,
      handleDismissEphemeral,
    });
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        // The geometry-less marker an empty run_analysis emits.
        data: { actions: [{ type: 'show_query_result', row_count: 0 }] },
      };
      yield { event: 'done', data: { explanation: 'Nothing found.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this map...'), 'buffer the empty layer');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Nothing found.');
    expect(handleDismissEphemeral).toHaveBeenCalled();
    expect(handleQueryResult).not.toHaveBeenCalled();
  });

  it('shows a retry-able error bubble when the stream fails', async () => {
    setAvailable(true);
    // eslint-disable-next-line require-yield
    mockStream.mockImplementation(async function* () {
      throw new Error('boom');
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this map...'), 'hi');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Something went wrong. Please try again.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
