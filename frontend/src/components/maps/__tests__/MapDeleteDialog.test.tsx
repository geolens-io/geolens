import { render as rtlRender } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { getMapStories } from '@/api/maps';
import { MapDeleteDialog } from '@/components/maps/MapDeleteDialog';

vi.mock('@/api/maps', () => ({ getMapStories: vi.fn() }));

const mockGetMapStories = vi.mocked(getMapStories);

function renderDialog(open = true) {
  render(
    <MapDeleteDialog
      open={open}
      onOpenChange={vi.fn()}
      mapId="map-1"
      mapName="Parks"
      onConfirm={vi.fn()}
      isDeleting={false}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('MapDeleteDialog stories', () => {
  it('links the stories the caller can read and counts the rest', async () => {
    mockGetMapStories.mockResolvedValue({
      stories: [
        { id: 'story-a', title: 'River walk' },
        { id: 'story-b', title: 'Old mills' },
      ],
      hidden_count: 2,
    });
    renderDialog();

    const link = await screen.findByRole('link', { name: 'River walk' });
    expect(link).toHaveAttribute('href', '/stories/story-a');
    expect(screen.getByRole('link', { name: 'Old mills' })).toHaveAttribute('href', '/stories/story-b');
    expect(
      screen.getByText(
        'This map is used in 4 stories. Their chapters keep their text but lose the scenes on this map.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("2 stories you can't see")).toBeInTheDocument();
    expect(mockGetMapStories).toHaveBeenCalledWith('map-1');
  });

  it('says nothing about stories when none use the map', async () => {
    mockGetMapStories.mockResolvedValue({ stories: [], hidden_count: 0 });
    renderDialog();

    await vi.waitFor(() => expect(mockGetMapStories).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(screen.queryByText(/This map is used in/)).not.toBeInTheDocument();
  });

  it('does not ask for the stories while closed', () => {
    renderDialog(false);

    expect(mockGetMapStories).not.toHaveBeenCalled();
  });

  it('holds Delete while it checks for stories', async () => {
    mockGetMapStories.mockReturnValue(new Promise(() => {}));
    renderDialog();

    expect(await screen.findByRole('status')).toHaveTextContent('Checking which stories use this map…');
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();
  });

  it('warns when the check fails, leaves Delete enabled and can try again', async () => {
    mockGetMapStories
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ stories: [{ id: 'story-a', title: 'River walk' }], hidden_count: 0 });
    renderDialog();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't check which stories use this map. Their chapters lose this map's scenes if any use it.",
    );
    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled();

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('link', { name: 'River walk' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('asks again on reopening and holds Delete until the new answer arrives', async () => {
    // The app's default staleTime, so a cached answer would otherwise be reused.
    const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: false } } });
    const dialog = (open: boolean) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MapDeleteDialog
            open={open}
            onOpenChange={vi.fn()}
            mapId="map-1"
            mapName="Parks"
            onConfirm={vi.fn()}
            isDeleting={false}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );
    mockGetMapStories.mockResolvedValueOnce({ stories: [], hidden_count: 0 });
    const { rerender } = rtlRender(dialog(true));
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled());

    rerender(dialog(false));
    mockGetMapStories.mockReturnValueOnce(new Promise(() => {}));
    rerender(dialog(true));

    expect(await screen.findByRole('status')).toHaveTextContent('Checking which stories use this map…');
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();
    expect(mockGetMapStories).toHaveBeenCalledTimes(2);
  });
});
