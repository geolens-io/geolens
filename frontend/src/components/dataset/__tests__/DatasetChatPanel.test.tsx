import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { streamDatasetChatMessage } from '@/api/maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { DatasetChatPanel } from '@/components/dataset/DatasetChatPanel';

// scrollIntoView is not available in jsdom
Element.prototype.scrollIntoView = vi.fn();

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('@/api/maps', () => ({ streamDatasetChatMessage: vi.fn() }));
vi.mock('@/hooks/use-ai-availability', () => ({ useAIAvailability: vi.fn() }));

const mockMutateAsync = vi.fn();
vi.mock('@/hooks/use-maps', () => ({
  useCreateMap: () => ({ mutateAsync: mockMutateAsync, isPending: false }),
}));

const mockStream = vi.mocked(streamDatasetChatMessage);
const mockAvailability = vi.mocked(useAIAvailability);

function setAvailable(available: boolean) {
  // Only the isAIAvailable field is read by the component.
  mockAvailability.mockReturnValue({ isAIAvailable: available } as ReturnType<typeof useAIAvailability>);
}

function renderPanel(showOpenInBuilder = true) {
  return render(
    <DatasetChatPanel datasetId="ds-1" datasetTitle="NY Parks" showOpenInBuilder={showOpenInBuilder} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

describe('DatasetChatPanel', () => {
  it('renders nothing when AI is unavailable (anon / no use_ai_chat)', () => {
    setAvailable(false);
    renderPanel();
    expect(screen.queryByRole('button', { name: 'Ask AI' })).toBeNull();
  });

  it('opens the panel and streams an answer', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield { event: 'token', data: { text: 'There are 1,200 parks.' } };
      yield { event: 'done', data: { explanation: 'There are 1,200 parks.' } };
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));

    const input = screen.getByPlaceholderText('Ask about this data...');
    await userEvent.type(input, 'how many parks?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('There are 1,200 parks.');
    expect(mockStream).toHaveBeenCalledWith('ds-1', 'how many parks?', expect.any(String), [], expect.any(AbortSignal));
  });

  it('renders a show_query_result table with an open-in-builder action', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              rows: [['Central Park', 843]],
              columns: ['name', 'acres'],
              row_count: 1,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Found 1 result.' } };
    });
    mockMutateAsync.mockResolvedValue({ id: 'map-9' });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this data...'), 'largest park');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Found 1 result.');
    expect(screen.getByText('Central Park')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Open in builder/i }));
    expect(mockMutateAsync).toHaveBeenCalledWith({ name: 'NY Parks Map' });
    // No spatial payload in the result — plain add_dataset URL, nothing stashed.
    expect(mockNavigate).toHaveBeenCalledWith('/maps/map-9?add_dataset=ds-1');
    expect(sessionStorage.getItem('geolens-chat-result')).toBeNull();
  });

  it('carries a spatial query result into the builder via sessionStorage', async () => {
    setAvailable(true);
    const geojson = { type: 'FeatureCollection', features: [] };
    const bbox = [-74.5, 40.4, -73.4, 41.1];
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            {
              type: 'show_query_result',
              rows: [['Central Park', 843]],
              columns: ['name', 'acres'],
              row_count: 1,
              geojson,
              bbox,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Found 1 result.' } };
    });
    mockMutateAsync.mockResolvedValue({ id: 'map-9' });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this data...'), 'largest park');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Found 1 result.');
    await userEvent.click(screen.getByRole('button', { name: /Open in builder/i }));

    expect(mockNavigate).toHaveBeenCalledWith('/maps/map-9?add_dataset=ds-1&chat_result=1');
    expect(JSON.parse(sessionStorage.getItem('geolens-chat-result')!)).toEqual({ geojson, bbox });
  });

  it('does not carry a stale spatial payload when a later table result has none (#533)', async () => {
    setAvailable(true);
    const geojson = { type: 'FeatureCollection', features: [] };
    const bbox = [-74.5, 40.4, -73.4, 41.1];
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            // Spatial result first...
            {
              type: 'show_query_result',
              rows: [['Central Park', 843]],
              columns: ['name', 'acres'],
              row_count: 1,
              geojson,
              bbox,
            },
            // ...then a non-spatial table (e.g. an aggregate) wins the panel.
            {
              type: 'show_query_result',
              rows: [[496]],
              columns: ['count'],
              row_count: 1,
            },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Counted.' } };
    });
    mockMutateAsync.mockResolvedValue({ id: 'map-9' });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this data...'), 'count parks');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Counted.');
    await userEvent.click(screen.getByRole('button', { name: /Open in builder/i }));

    // The shown table is the count — the earlier geometry must not ride along.
    expect(mockNavigate).toHaveBeenCalledWith('/maps/map-9?add_dataset=ds-1');
    expect(sessionStorage.getItem('geolens-chat-result')).toBeNull();
  });

  it('hides the open-in-builder action for non-spatial tables (fix #531)', async () => {
    setAvailable(true);
    mockStream.mockImplementation(async function* () {
      yield {
        event: 'actions',
        data: {
          actions: [
            { type: 'show_query_result', rows: [['a', 1]], columns: ['name', 'n'], row_count: 1 },
          ],
        },
      };
      yield { event: 'done', data: { explanation: 'Done.' } };
    });

    renderPanel(false);
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this data...'), 'count rows');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Done.');
    expect(screen.queryByRole('button', { name: /Open in builder/i })).toBeNull();
  });

  it('shows a retry-able error bubble when the stream fails', async () => {
    setAvailable(true);
    // eslint-disable-next-line require-yield
    mockStream.mockImplementation(async function* () {
      throw new Error('boom');
    });

    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Ask AI' }));
    await userEvent.type(screen.getByPlaceholderText('Ask about this data...'), 'hi');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Something went wrong. Please try again.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
