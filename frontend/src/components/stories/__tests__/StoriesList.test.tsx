import userEvent from '@testing-library/user-event';
import { render, screen, waitFor, within } from '@/test/test-utils';
import { StoriesList } from '../StoriesList';
import { deleteStory, duplicateStory, listStories } from '@/api/stories';
import type { StorySummary } from '@/types/api';

vi.mock('@/api/stories', () => ({
  listStories: vi.fn(),
  duplicateStory: vi.fn(),
  deleteStory: vi.fn(),
  storyAssetPath: (story: string, asset: string) => `/stories/${story}/assets/${asset}`,
}));
const blob = vi.hoisted(() => ({ paths: [] as string[] }));
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  apiFetchBlob: async (path: string) => {
    blob.paths.push(path);
    return new Blob(['x'], { type: 'image/webp' });
  },
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const perm = vi.hoisted(() => ({ editMetadata: false }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'edit_metadata' && perm.editMetadata }),
}));
vi.mock('sonner', () => ({ toast }));

function summary(overrides: Partial<StorySummary>): StorySummary {
  return {
    id: 'story-1',
    title: 'Hurricanes',
    summary: 'Where they go',
    visibility: 'public',
    created_by: 'owner',
    published_at: '2026-10-29T00:00:00Z',
    cover_asset_id: null,
    created_at: '2026-10-29T00:00:00Z',
    updated_at: '2026-10-29T00:00:00Z',
    can_edit: false,
    ...overrides,
  };
}

const OWN = summary({ id: 'own', title: 'My draft', visibility: 'private', published_at: null, can_edit: true });
const OTHER = summary({ id: 'other', title: 'Their story' });

function renderList(editMetadata: boolean) {
  perm.editMetadata = editMetadata;
  return render(<StoriesList />);
}

beforeEach(() => {
  vi.mocked(listStories).mockResolvedValue({ stories: [OWN, OTHER], total: 2 });
  vi.mocked(duplicateStory).mockReset();
  vi.mocked(deleteStory).mockReset();
  toast.success.mockReset();
});

it('links each story to its reader and marks unpublished ones', async () => {
  renderList(false);
  expect(await screen.findByRole('link', { name: 'My draft' })).toHaveAttribute('href', '/stories/own');
  expect(screen.getByRole('link', { name: 'Their story' })).toHaveAttribute('href', '/stories/other');
  const own = screen.getAllByTestId('story-card')[0];
  expect(within(own).getByText('Not published')).toBeInTheDocument();
});

it('offers delete only on stories the caller can edit, and duplicate only to creators', async () => {
  const { unmount } = renderList(false);
  await screen.findByRole('link', { name: 'My draft' });
  expect(screen.getByRole('button', { name: 'Delete My draft' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete Their story' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Duplicate/ })).not.toBeInTheDocument();
  unmount();

  renderList(true);
  await screen.findByRole('link', { name: 'My draft' });
  expect(screen.getByRole('button', { name: 'Duplicate Their story' })).toBeInTheDocument();
});

it('duplicates a story and refreshes the list', async () => {
  vi.mocked(duplicateStory).mockResolvedValue({ ...OTHER, id: 'copy', title: 'Their story (copy)' } as never);
  const user = userEvent.setup();
  renderList(true);
  await user.click(await screen.findByRole('button', { name: 'Duplicate Their story' }));
  await waitFor(() => expect(duplicateStory).toHaveBeenCalledWith('other'));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Their story (copy)')));
  await waitFor(() => expect(listStories).toHaveBeenCalledTimes(2));
});

it('deletes a story only after the confirm', async () => {
  vi.mocked(deleteStory).mockResolvedValue(undefined);
  const user = userEvent.setup();
  renderList(true);
  await user.click(await screen.findByRole('button', { name: 'Delete My draft' }));
  const dialog = screen.getByRole('alertdialog');
  expect(within(dialog).getByText('My draft')).toBeInTheDocument();
  expect(deleteStory).not.toHaveBeenCalled();

  await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
  await waitFor(() => expect(deleteStory).toHaveBeenCalledWith('own'));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  expect(toast.success).toHaveBeenCalledWith('Story deleted');
});

it('links the editor only for stories the caller can edit, and only with edit_metadata', async () => {
  const { unmount } = renderList(false);
  await screen.findByRole('link', { name: 'My draft' });
  expect(screen.queryByRole('link', { name: 'Edit My draft' })).not.toBeInTheDocument();
  unmount();

  renderList(true);
  expect(await screen.findByRole('link', { name: 'Edit My draft' })).toHaveAttribute('href', '/stories/own/edit');
  expect(screen.queryByRole('link', { name: 'Edit Their story' })).not.toBeInTheDocument();
});

it('steps back a page after deleting the only story on the last page', async () => {
  const twenty = Array.from({ length: 20 }, (_, i) => summary({ id: `s${i}`, title: `Story ${i}` }));
  vi.mocked(listStories).mockImplementation(async (params) =>
    params?.skip === 20
      ? { stories: [summary({ id: 'last', title: 'Last one', can_edit: true })], total: 21 }
      : { stories: twenty, total: 21 },
  );
  vi.mocked(deleteStory).mockResolvedValue(undefined);
  const user = userEvent.setup();
  renderList(true);
  await screen.findByRole('link', { name: 'Story 0' });
  await user.click(screen.getByRole('button', { name: /next/i }));
  await user.click(await screen.findByRole('button', { name: 'Delete Last one' }));
  vi.mocked(listStories).mockImplementation(async (params) =>
    params?.skip === 20 ? { stories: [], total: 20 } : { stories: twenty, total: 20 },
  );
  vi.mocked(listStories).mockClear();
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
  expect(await screen.findByRole('link', { name: 'Story 0' })).toBeInTheDocument();
  // The emptied page isn't fetched on the way back.
  expect(vi.mocked(listStories).mock.calls.map(([params]) => params?.skip)).toEqual([0]);
});


it('shows a story’s cover on its card, decoratively', async () => {
  const covered = summary({ id: 'covered', title: 'With cover', cover_asset_id: 'cover-1' });
  vi.mocked(listStories).mockResolvedValue({ stories: [covered, OTHER], total: 2 });
  renderList(false);
  await screen.findByRole('link', { name: 'With cover' });
  const [card, plain] = screen.getAllByTestId('story-card');
  await waitFor(() => expect(card.querySelector('img')).not.toBeNull());
  expect(card.querySelector('img')).toHaveAttribute('alt', '');
  expect(blob.paths).toContain('/stories/covered/assets/cover-1');
  expect(plain.querySelector('img')).toBeNull();
});
