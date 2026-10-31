import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { setDatasetGroups } from '@/api/datasets';
import { listMyGroups } from '@/api/groups';
import { ApiError } from '@/api/client';
import { translateApiErrorDetail } from '@/lib/error-map';
import { DatasetGroupShare } from '../DatasetGroupShare';

vi.mock('@/api/datasets', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/datasets')>()),
  setDatasetGroups: vi.fn(),
}));
vi.mock('@/api/groups', () => ({ listMyGroups: vi.fn() }));
vi.mock('sonner', () => ({ toast: { warning: vi.fn() } }));

const mockSet = vi.mocked(setDatasetGroups);
const mockMine = vi.mocked(listMyGroups);

const SURVEYORS = { id: 'g-1', name: 'Surveyors' };
const PLANNERS = { id: 'g-2', name: 'Planners' };

function setup(props: { visibility?: string; groups?: { id: string; name: string }[] } = {}) {
  const user = userEvent.setup();
  render(
    <DatasetGroupShare
      datasetId="ds-1"
      visibility={props.visibility ?? 'private'}
      groups={props.groups ?? []}
    />,
  );
  return user;
}

async function pick(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = await screen.findByRole('combobox', { name: 'Add a group' });
  await user.type(input, name);
  await user.click(await screen.findByRole('option', { name }));
}

describe('DatasetGroupShare', () => {
  beforeEach(() => {
    mockSet.mockReset();
    mockMine.mockReset();
    mockMine.mockResolvedValue([SURVEYORS, PLANNERS]);
  });

  it('names the chosen-groups list after the dataset', async () => {
    setup({ visibility: 'restricted', groups: [SURVEYORS] });
    expect(await screen.findByRole('list', { name: 'Groups this dataset is shared with' })).toBeInTheDocument();
  });

  it('shares a private dataset with the picked group and reports it restricted', async () => {
    mockSet.mockResolvedValue({ visibility: 'restricted', groups: [SURVEYORS] });
    const user = setup();
    await pick(user, 'Surveyors');

    expect(
      screen.getByText(/Saving makes this dataset Restricted/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith('ds-1', ['g-1']));
    expect(await screen.findByText('Groups saved. This dataset is now Restricted.')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Add a group' })).toHaveFocus();
  });

  it('shows the inherited-keyword warning the save returns', async () => {
    const warning = 'Inherited keywords are now visible to people who cannot read the source.';
    mockSet.mockResolvedValue({ visibility: 'restricted', groups: [SURVEYORS], metadata_warnings: [warning] });
    const user = setup();
    await pick(user, 'Surveyors');
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(warning));
  });

  it('unshares with an empty list and says the dataset becomes private', async () => {
    mockSet.mockResolvedValue({ visibility: 'private', groups: [] });
    const user = setup({ visibility: 'restricted', groups: [SURVEYORS] });

    await user.click(await screen.findByRole('button', { name: 'Remove Surveyors' }));
    expect(screen.getByText(/The dataset becomes Private/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith('ds-1', []));
    expect(await screen.findByText('Groups saved. This dataset is now Private.')).toBeInTheDocument();
  });

  it('keeps the audience on an internal dataset and says so before saving', async () => {
    const user = setup({ visibility: 'internal' });
    await pick(user, 'Planners');
    expect(
      screen.getByText(/This dataset is Internal, so saving does not change who can open it/),
    ).toBeInTheDocument();
  });

  it('lists only groups not already picked', async () => {
    const user = setup({ groups: [SURVEYORS] });
    const input = await screen.findByRole('combobox', { name: 'Add a group' });
    await user.click(input);
    await user.keyboard('{ArrowDown}');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Planners']);
  });

  it.each([
    [
      '403',
      'You can share a dataset only with groups you belong to.',
      'Could not save groups: You can share only with groups you belong to.',
    ],
    [
      '422',
      'Cannot restrict visibility: dataset is used in shared maps: Parks map',
      /Could not save groups: .*Parks map/,
    ],
  ])('shows the %s reason, marks nothing saved and keeps the save available', async (status, detail, message) => {
    mockSet.mockRejectedValue(new ApiError(translateApiErrorDetail(detail, Number(status)), Number(status)));
    const user = setup();
    await pick(user, 'Surveyors');
    await user.click(screen.getByRole('button', { name: 'Save groups' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText(/Groups saved/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save groups' })).toBeEnabled();
  });

  it('keeps Save disabled until the list changes', async () => {
    setup({ groups: [SURVEYORS] });
    expect(await screen.findByRole('button', { name: 'Save groups' })).toBeDisabled();
  });
});
