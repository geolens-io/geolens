import userEvent from '@testing-library/user-event';
import { render, screen, waitFor, within } from '@/test/test-utils';
import { setStoryGroups } from '@/api/stories';
import { listMyGroups } from '@/api/groups';
import { ApiError } from '@/api/client';
import { StoryGroupShare } from '../StoryGroupShare';

vi.mock('@/api/stories', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/stories')>()),
  setStoryGroups: vi.fn(),
}));
vi.mock('@/api/groups', () => ({ listMyGroups: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mockSet = vi.mocked(setStoryGroups);
const SURVEYORS = { id: 'g-1', name: 'Surveyors' };

function blockedBy(maps: { id: string; name: string; can_share: boolean }[]) {
  return new ApiError('Conflict', 409, { code: 'maps_narrower_than_story', maps, unreadable_maps: 0 });
}

async function pickAndSave(onSaved = vi.fn()) {
  const user = userEvent.setup();
  render(<StoryGroupShare storyId="s1" visibility="private" groups={[]} onSaved={onSaved} />);
  await user.type(await screen.findByRole('combobox', { name: 'Add a group' }), 'Surveyors');
  await user.click(await screen.findByRole('option', { name: 'Surveyors' }));
  expect(screen.getByText(/Saving shares this story with specific groups/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Save groups' }));
  return { user, onSaved };
}

describe('StoryGroupShare', () => {
  beforeEach(() => {
    mockSet.mockReset();
    vi.mocked(listMyGroups).mockResolvedValue([SURVEYORS]);
  });

  it('names the chosen-groups list after the story', async () => {
    render(<StoryGroupShare storyId="s1" visibility="restricted" groups={[SURVEYORS]} onSaved={vi.fn()} />);
    expect(await screen.findByRole('list', { name: 'Groups this story is shared with' })).toBeInTheDocument();
  });

  it('shares the story with the picked groups', async () => {
    mockSet.mockResolvedValue({ visibility: 'restricted', groups: [SURVEYORS], shared_map_ids: [] });
    const { onSaved } = await pickAndSave();

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ visibility: 'restricted' })));
    expect(mockSet).toHaveBeenCalledWith('s1', ['g-1'], undefined);
    expect(
      await screen.findByText('Groups saved. This story is now shared with specific groups only.'),
    ).toBeInTheDocument();
  });

  it('shares the author\'s blocking maps only once they confirm', async () => {
    mockSet
      .mockRejectedValueOnce(blockedBy([{ id: 'm1', name: 'Private tracks', can_share: true }]))
      .mockResolvedValueOnce({ visibility: 'restricted', groups: [SURVEYORS], shared_map_ids: ['m1'] });
    const { user, onSaved } = await pickAndSave();

    const dialog = await screen.findByRole('alertdialog', { name: "Some maps can't be read by these groups" });
    expect(within(dialog).getByRole('link', { name: 'Private tracks' })).toHaveAttribute('href', '/maps/m1');
    expect(within(dialog).getByText(/stops working through its share link and embed codes/)).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Share my maps and save' }));

    await waitFor(() => expect(mockSet).toHaveBeenLastCalledWith('s1', ['g-1'], 'share_maps'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(
      await screen.findByText('Groups saved, and 1 of your maps is now shared with them.'),
    ).toBeInTheDocument();
  });

  it('names a map the author can\'t share and offers nothing to confirm', async () => {
    mockSet.mockRejectedValue(blockedBy([{ id: 'm2', name: 'Their tracks', can_share: false }]));
    await pickAndSave();

    const dialog = await screen.findByRole('alertdialog', { name: "Some maps can't be read by these groups" });
    expect(within(dialog).getByText("(you can't share this map)")).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Share my maps and save' })).not.toBeInTheDocument();
    expect(mockSet).toHaveBeenCalledTimes(1);
  });
});
