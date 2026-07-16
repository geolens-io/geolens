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

function renderPanel() {
  return render(<DatasetChatPanel datasetId="ds-1" datasetTitle="NY Parks" />);
}

beforeEach(() => {
  vi.clearAllMocks();
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
    expect(mockNavigate).toHaveBeenCalledWith('/maps/map-9?add_dataset=ds-1');
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
