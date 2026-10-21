import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { streamGenerateMap } from '@/api/maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { MapCreateDialog } from '@/components/maps/MapCreateDialog';

vi.mock('@/api/maps', () => ({ streamGenerateMap: vi.fn() }));
vi.mock('@/hooks/use-ai-availability', () => ({ useAIAvailability: vi.fn() }));
vi.mock('@/hooks/use-maps', () => ({
  useCreateMap: () => ({ mutateAsync: vi.fn(), reset: vi.fn(), isPending: false, isError: false }),
}));

const mockStream = vi.mocked(streamGenerateMap);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAIAvailability).mockReturnValue({ isAIAvailable: true } as ReturnType<typeof useAIAvailability>);
});

async function generate(events: { event: string; data: Record<string, unknown> }[]) {
  mockStream.mockImplementation(async function* () {
    yield* events;
  });
  render(<MapCreateDialog open onOpenChange={vi.fn()} />);
  await userEvent.click(screen.getByRole('tab', { name: /AI Generate/ }));
  await userEvent.type(screen.getByLabelText('Describe the map you want'), 'parks in Brooklyn');
  await userEvent.click(screen.getByRole('button', { name: /Generate Map/ }));
}

describe('MapCreateDialog AI generation errors', () => {
  it('explains a model that needs the Responses API in the UI language', async () => {
    await generate([
      { event: 'error', data: { message: 'English server text', code: 'model_requires_responses_api' } },
    ]);

    await screen.findByText(
      "This site's AI model needs the OpenAI Responses API. Ask an administrator to turn it on or choose a different model.",
    );
    expect(screen.queryByText('English server text')).not.toBeInTheDocument();
  });

  it('shows the server message for an uncoded error', async () => {
    await generate([{ event: 'error', data: { message: 'No datasets matched' } }]);

    await screen.findByText('No datasets matched');
  });
});

describe('MapCreateDialog AI generation progress', () => {
  it('shows the progress label from the UI language bundle, not the server label', async () => {
    mockStream.mockImplementation(async function* () {
      yield { event: 'tool_start', data: { tool: 'search_datasets', label: 'English server label' } };
      await new Promise(() => {});
    });
    render(<MapCreateDialog open onOpenChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('tab', { name: /AI Generate/ }));
    await userEvent.type(screen.getByLabelText('Describe the map you want'), 'parks in Brooklyn');
    await userEvent.click(screen.getByRole('button', { name: /Generate Map/ }));

    await screen.findByText('Searching datasets...');
    expect(screen.queryByText('English server label')).not.toBeInTheDocument();
  });

  it('falls back to the server label for a tool the bundle does not know', async () => {
    mockStream.mockImplementation(async function* () {
      yield { event: 'tool_start', data: { tool: 'brand_new_tool', label: 'Doing something new...' } };
      await new Promise(() => {});
    });
    render(<MapCreateDialog open onOpenChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('tab', { name: /AI Generate/ }));
    await userEvent.type(screen.getByLabelText('Describe the map you want'), 'parks in Brooklyn');
    await userEvent.click(screen.getByRole('button', { name: /Generate Map/ }));

    await screen.findByText('Doing something new...');
  });
});
