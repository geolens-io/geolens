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

    expect(screen.getByText(/Query result/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss query result' }));
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
              geojson: { type: 'FeatureCollection', features: [] },
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
      { type: 'FeatureCollection', features: [] },
      [-1, -1, 1, 1],
    );
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('1 row')).toBeInTheDocument();
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
