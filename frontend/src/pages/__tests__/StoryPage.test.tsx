import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router';
import userEvent from '@testing-library/user-event';
import { render, screen, within } from '@/test/test-utils';
import { StoryPage } from '../StoryPage';
import { ThemeProvider } from '@/components/theme-provider';
import { getStory } from '@/api/stories';
import { ApiError } from '@/api/client';
import type { StoryResponse } from '@/types/api';

const auth = vi.hoisted(() => ({ token: null as string | null, canEdit: false }));
vi.mock('@/api/stories', () => ({ getStory: vi.fn() }));
vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (selector: (s: { token: string | null }) => unknown) => selector({ token: auth.token }),
}));
vi.mock('@/hooks/use-settings', () => ({ useTileConfig: () => ({ data: undefined }) }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'edit_metadata' && auth.canEdit }),
}));
vi.mock('@/components/stories/StoryReader', () => ({
  StoryReader: ({
    title,
    editHref,
    headerActions,
    settings,
  }: {
    title: string;
    editHref?: string;
    headerActions?: ReactNode;
    settings?: { layout: string } | null;
  }) => (
    <div data-testid="story-reader" data-edit={editHref ?? ''} data-layout={settings?.layout ?? ''}>
      {title}
      {headerActions}
    </div>
  ),
}));

beforeEach(() => {
  auth.token = null;
  auth.canEdit = false;
});

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
  can_edit: false,
  document: {
    version: 1,
    chapters: [{ id: 'c1', title: 'One', scene: null, scene_hidden: false, blocks: [] }],
  },
};

function renderPage() {
  return render(
    <Routes>
      <Route path="/stories/:id" element={<StoryPage />} />
    </Routes>,
    { route: '/stories/story-1' },
  );
}

it('reads the published story', async () => {
  vi.mocked(getStory).mockResolvedValue(STORY);
  renderPage();
  expect(await screen.findByTestId('story-reader')).toHaveTextContent('Hurricanes');
  expect(getStory).toHaveBeenCalledWith('story-1');
});

it("hands the published document's reader settings to the reader", async () => {
  const settings = { navigation: true, layout: 'floating', panel_position: 'right', theme: 'follow', transition: 'fly' } as const;
  vi.mocked(getStory).mockResolvedValue({ ...STORY, document: { ...STORY.document!, settings } });
  renderPage();
  expect(await screen.findByTestId('story-reader')).toHaveAttribute('data-layout', 'floating');
});

it('offers a signed-out reader sign-in for a story they cannot see', async () => {
  vi.mocked(getStory).mockRejectedValue(new ApiError('Story not found', 404));
  renderPage();
  expect(await screen.findByRole('heading', { name: 'Story not available' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
});

it('points a signed-in reader back to the stories list instead', async () => {
  auth.token = 'token';
  vi.mocked(getStory).mockRejectedValue(new ApiError('Story not found', 404));
  renderPage();
  expect(await screen.findByRole('link', { name: 'Open stories' })).toHaveAttribute('href', '/maps?type=stories');
  expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
});

it('links the editor only for a reader who can edit the story and has edit_metadata', async () => {
  vi.mocked(getStory).mockResolvedValue({ ...STORY, can_edit: true });
  const { unmount } = renderPage();
  expect(await screen.findByTestId('story-reader')).toHaveAttribute('data-edit', '');
  unmount();

  auth.canEdit = true;
  renderPage();
  expect(await screen.findByTestId('story-reader')).toHaveAttribute('data-edit', '/stories/story-1/edit');
});

it('tells the owner an unpublished story has nothing to read yet', async () => {
  vi.mocked(getStory).mockResolvedValue({ ...STORY, published_at: null, document: null });
  renderPage();
  expect(await screen.findByText("This story hasn't been published yet.")).toBeInTheDocument();
  expect(screen.queryByTestId('story-reader')).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument();
});

it('offers the owner the editor for an unpublished story', async () => {
  auth.canEdit = true;
  vi.mocked(getStory).mockResolvedValue({ ...STORY, can_edit: true, published_at: null, document: null });
  renderPage();
  expect(await screen.findByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/stories/story-1/edit');
});

describe('reader theme', () => {
  function renderThemed() {
    return render(
      <ThemeProvider defaultTheme="light">
        <Routes>
          <Route path="/stories/:id" element={<StoryPage />} />
        </Routes>
      </ThemeProvider>,
      { route: '/stories/story-1' },
    );
  }

  afterEach(() => document.documentElement.classList.remove('light', 'dark'));

  it('shows a dark story dark to a reader on light', async () => {
    vi.mocked(getStory).mockResolvedValue({
      ...STORY,
      document: { ...STORY.document!, settings: { navigation: true, layout: 'side', panel_position: 'right', theme: 'dark', transition: 'fly' } },
    });
    renderThemed();
    await screen.findByTestId('story-reader');
    expect(document.documentElement).toHaveClass('dark');
  });

  it('leaves the reader\'s theme alone when the story follows', async () => {
    vi.mocked(getStory).mockResolvedValue(STORY);
    renderThemed();
    await screen.findByTestId('story-reader');
    expect(document.documentElement).toHaveClass('light');
  });
});

describe('embed snippet', () => {
  it('offers the iframe snippet for a published public story', async () => {
    const user = userEvent.setup();
    vi.mocked(getStory).mockResolvedValue({ ...STORY, title: 'Hurricanes & "storms"' });
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Embed' }));

    const dialog = await screen.findByRole('dialog', { name: 'Embed this story' });
    const code = (within(dialog).getByRole('textbox', { name: 'Embed code' }) as HTMLTextAreaElement).value;
    const iframe = new DOMParser().parseFromString(code, 'text/html').querySelector('iframe')!;
    expect(iframe.getAttribute('src')).toBe(`${window.location.origin}/stories/story-1/embed`);
    expect(iframe.getAttribute('title')).toBe('Hurricanes & "storms"');
    expect(iframe.getAttribute('sandbox')?.split(' ')).toEqual(
      expect.arrayContaining(['allow-scripts', 'allow-same-origin']),
    );
    expect(within(dialog).getByRole('button', { name: 'Copy embed code' })).toBeInTheDocument();
  });

  it.each([
    ['private', { visibility: 'private' }],
    ['restricted', { visibility: 'restricted' }],
    ['internal', { visibility: 'internal' }],
    ['unpublished', { published_at: null }],
  ] as const)('is not offered for a %s story', async (_name, change) => {
    vi.mocked(getStory).mockResolvedValue({ ...STORY, ...change } as StoryResponse);
    renderPage();
    await screen.findByTestId('story-reader');
    expect(screen.queryByRole('button', { name: 'Embed' })).not.toBeInTheDocument();
  });
});
