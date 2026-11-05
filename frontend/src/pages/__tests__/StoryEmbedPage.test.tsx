import { Route, Routes } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { StoryEmbedPage } from '../StoryEmbedPage';
import { getStory } from '@/api/stories';
import { ApiError } from '@/api/client';
import type { StoryResponse } from '@/types/api';

vi.mock('@/api/stories', () => ({ getStory: vi.fn() }));
vi.mock('@/components/stories/StoryReader', () => ({
  StoryReader: ({ title, chromeless, editHref }: { title: string; chromeless?: boolean; editHref?: string }) => (
    <div data-testid="story-reader" data-chromeless={String(!!chromeless)} data-edit={editHref ?? ''}>
      {title}
    </div>
  ),
}));

const STORY: StoryResponse = {
  id: 'story-1',
  title: 'Hurricanes',
  summary: null,
  visibility: 'public',
  created_by: null,
  published_at: '2026-10-29T00:00:00Z',
  cover_asset_id: null,
  created_at: '2026-10-29T00:00:00Z',
  updated_at: '2026-10-29T00:00:00Z',
  can_edit: true,
  document: {
    version: 1,
    chapters: [{ id: 'c1', title: 'One', scene: null, scene_hidden: false, blocks: [] }],
  },
};

function renderEmbed() {
  return render(
    <Routes>
      <Route path="/stories/:id/embed" element={<StoryEmbedPage />} />
    </Routes>,
    { route: '/stories/story-1/embed' },
  );
}

it('renders the published story chromeless, filling the frame', async () => {
  vi.mocked(getStory).mockResolvedValue(STORY);
  renderEmbed();
  const reader = await screen.findByTestId('story-reader');
  expect(reader).toHaveAttribute('data-chromeless', 'true');
  expect(reader).toHaveAttribute('data-edit', '');
  expect(getStory).toHaveBeenCalledWith('story-1');
  expect(screen.getByRole('main')).toHaveClass('h-dvh');
  expect(screen.queryByRole('banner')).not.toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('shows the not-found state, with no way into the app, for a story it cannot read', async () => {
  vi.mocked(getStory).mockRejectedValue(new ApiError('Story not found', 404));
  renderEmbed();
  expect(await screen.findByRole('heading', { name: 'Story not available' })).toBeInTheDocument();
  expect(screen.getByText("This story isn't public, or it has been deleted.")).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(screen.queryByTestId('story-reader')).not.toBeInTheDocument();
});
