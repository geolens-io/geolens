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
});
