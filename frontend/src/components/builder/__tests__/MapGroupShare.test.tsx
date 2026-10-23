import { render, screen, waitFor, within } from '@/test/test-utils';
import { toast } from 'sonner';
import userEvent from '@testing-library/user-event';
import { setMapGroups } from '@/api/maps';
import { listMyGroups } from '@/api/groups';
import { ApiError } from '@/api/client';
import { translateApiErrorDetail } from '@/lib/error-map';
import { MapGroupShare } from '../MapGroupShare';

vi.mock('@/api/maps', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/maps')>()),
  setMapGroups: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/api/groups', () => ({ listMyGroups: vi.fn() }));

const mockSet = vi.mocked(setMapGroups);
const mockMine = vi.mocked(listMyGroups);

const SURVEYORS = { id: 'g-1', name: 'Surveyors' };
const PLANNERS = { id: 'g-2', name: 'Planners' };

function setup(props: { visibility?: string; groups?: typeof SURVEYORS[]; hasLinks?: boolean; focusOnOpen?: boolean } = {}) {
  const user = userEvent.setup();
  render(
    <MapGroupShare
      mapId="map-1"
      visibility={props.visibility ?? 'private'}
      groups={props.groups ?? []}
      hasLinks={props.hasLinks ?? false}
      focusOnOpen={props.focusOnOpen}
    />,
  );
  return { user };
}

async function pick(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.type(await screen.findByRole('combobox', { name: 'Add a group' }), name);
  await user.click(await screen.findByRole('option', { name }));
}

describe('MapGroupShare', () => {
  beforeEach(() => {
    mockSet.mockReset();
    mockMine.mockReset();
    mockMine.mockResolvedValue([SURVEYORS, PLANNERS]);
  });

  it('moves focus to the picker and says what to do next when opened from the level', async () => {
    setup({ focusOnOpen: true });
    const input = await screen.findByRole('combobox', { name: 'Add a group' });
    await waitFor(() => expect(input).toHaveFocus());
    expect(await screen.findByText('Pick groups, then save.')).toBeInTheDocument();
  });

  it('lists the groups a restricted map is shared with', async () => {
    setup({ visibility: 'restricted', groups: [SURVEYORS] });
    expect(await screen.findByText('Surveyors')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove Surveyors' })).toBeInTheDocument();
  });

  it('shares a private map with the picked group and reports it restricted', async () => {
    mockSet.mockResolvedValue({ visibility: 'restricted', groups: [SURVEYORS] });
    const { user } = setup();
    await pick(user, 'Surveyors');

    expect(screen.getByText(/Saving shares this map with specific groups/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith('map-1', ['g-1'], undefined));
    expect(
      await screen.findByText('Groups saved. This map is now shared with specific groups only.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Add a group' })).toHaveFocus();
  });

  it('clears the last group and reports the map private', async () => {
    mockSet.mockResolvedValue({ visibility: 'private', groups: [] });
    const { user } = setup({ visibility: 'restricted', groups: [SURVEYORS] });

    await user.click(await screen.findByRole('button', { name: 'Remove Surveyors' }));
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith('map-1', [], undefined));
    expect(await screen.findByText('Groups removed. Only you and admins can open this map.')).toBeInTheDocument();
  });

  it.each([
    [
      '403',
      new ApiError(translateApiErrorDetail('You can share a map only with groups you belong to.', 403), 403),
      'Could not save groups: You can share only with groups you belong to.',
    ],
    [
      '404',
      new ApiError(translateApiErrorDetail({ message: 'Group not found', group_ids: ['g-2'] }, 404), 404),
      'Could not save groups: Group not found',
    ],
  ])('shows the %s reason and marks nothing saved', async (_status, error, message) => {
    mockSet.mockRejectedValue(error);
    const { user } = setup();
    await pick(user, 'Planners');
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText(/Groups saved/)).not.toBeInTheDocument();
  });

  it.each([
    [true, 1],
    [false, 0],
  ])('with hasLinks=%s shows the link warning %s time(s)', async (hasLinks, count) => {
    const { user } = setup({ hasLinks });
    await pick(user, 'Surveyors');
    expect(screen.queryAllByText(/share link and embed tokens stop working/)).toHaveLength(count);
  });

  it('says an internal map keeps its audience', async () => {
    setup({ visibility: 'internal', groups: [SURVEYORS] });
    expect(await screen.findByText(/don't change who can open this map now/)).toBeInTheDocument();
  });

  describe('confirming layers some groups cannot read', () => {
    const gapBody = (canShare: boolean) => ({
      code: 'layers_hidden_from_groups',
      message: 'Some layers are hidden from the groups',
      layers: [
        {
          layer_id: 'l-1',
          layer_title: 'Parcels',
          dataset_id: 'd-1',
          dataset_title: 'Parcel data',
          group_ids: ['g-1'],
          can_share: canShare,
        },
      ],
    });
    const conflict = (canShare = true) =>
      new ApiError('Some layers are hidden from the groups', 409, gapBody(canShare));

    async function openConfirm(canShare = true) {
      mockSet.mockRejectedValueOnce(conflict(canShare));
      const view = setup();
      await pick(view.user, 'Surveyors');
      await view.user.click(screen.getByRole('button', { name: 'Save groups' }));
      const dialog = await screen.findByRole('alertdialog');
      return { ...view, dialog };
    }

    it('lists each layer with its dataset and the groups that cannot read it, saving nothing yet', async () => {
      const { dialog } = await openConfirm();

      expect(within(dialog).getByText('Parcels (dataset: Parcel data)')).toBeInTheDocument();
      expect(within(dialog).getByText('Not readable by: Surveyors')).toBeInTheDocument();
      expect(within(dialog).getByText('You can share this dataset with those groups.')).toBeInTheDocument();
      expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
      expect(mockSet).toHaveBeenCalledTimes(1);
      expect(screen.queryByText(/Map shared/)).not.toBeInTheDocument();
    });

    it.each([
      ['Share map and datasets', 'share_datasets', ['d-1'], [], 'Map shared, along with 1 dataset.'],
      [
        'Share map and datasets',
        'share_datasets',
        ['d-1', 'd-2'],
        gapBody(true).layers,
        'Map shared, along with 2 datasets. 1 layer stays hidden from some groups.',
      ],
      [
        'Share map only',
        'map_only',
        [],
        gapBody(true).layers,
        'Map shared. 1 layer stays hidden from some groups.',
      ],
    ])('%s repeats the request with its confirm value and reports the result', async (label, confirm, shared, hidden, message) => {
      const { user, dialog } = await openConfirm();
      mockSet.mockResolvedValueOnce({
        visibility: 'restricted',
        groups: [SURVEYORS],
        shared_dataset_ids: shared,
        hidden_layers: hidden,
      });

      await user.click(within(dialog).getByRole('button', { name: label }));

      await waitFor(() => expect(mockSet).toHaveBeenLastCalledWith('map-1', ['g-1'], confirm));
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith(message));
      expect(screen.queryByText(message)).not.toBeInTheDocument();
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(screen.getByRole('combobox', { name: 'Add a group' })).toHaveFocus();
    });

    it('Cancel sends nothing more and keeps the picked groups as a draft', async () => {
      const { user, dialog } = await openConfirm();

      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(mockSet).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', { name: 'Remove Surveyors' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Save groups' })).toBeEnabled();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('says layers whose dataset cannot be shared stay hidden', async () => {
      const { dialog } = await openConfirm(false);

      expect(
        within(dialog).getByText("You can't share this dataset, so the layer stays hidden from them."),
      ).toBeInTheDocument();
      expect(within(dialog).getByText(/stay hidden from those groups either way/)).toBeInTheDocument();
    });

    it.each([
      ['a plain message', 'Another change to this map is in progress. Retry shortly.'],
      ['a body with layers but another code', { code: 'other', message: 'Another change to this map is in progress. Retry shortly.', layers: gapBody(true).layers }],
    ])('treats a 409 with %s as an error, not a confirmation', async (_label, body) => {
      mockSet.mockRejectedValueOnce(
        new ApiError(
          translateApiErrorDetail('Another change to this map is in progress. Retry shortly.', 409),
          409,
          body,
        ),
      );
      const { user } = setup();
      await pick(user, 'Surveyors');
      await user.click(screen.getByRole('button', { name: 'Save groups' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Could not save groups: Another change to this map is in progress. Try again shortly.',
      );
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(screen.queryByText(/Groups saved|Map shared/)).not.toBeInTheDocument();
    });

    it('shows why a confirmed request was refused and saves nothing', async () => {
      const { user, dialog } = await openConfirm();
      mockSet.mockRejectedValueOnce(
        new ApiError(translateApiErrorDetail('You can share a map only with groups you belong to.', 403), 403),
      );

      await user.click(within(dialog).getByRole('button', { name: 'Share map and datasets' }));

      expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent(
        'Could not save groups: You can share only with groups you belong to.',
      );
      expect(screen.queryByText(/Map shared/)).not.toBeInTheDocument();
      expect(toast.success).not.toHaveBeenCalled();
    });
  });
});
