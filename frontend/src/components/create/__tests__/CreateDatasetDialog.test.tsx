import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { CreateDatasetDialog } from '../CreateDatasetDialog';

const mutation = vi.hoisted(() => ({ isPending: false }));
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useCreateDataset: () => ({ mutate: vi.fn(), isPending: mutation.isPending }),
}));

afterEach(() => {
  mutation.isPending = false;
});

function setup() {
  const onOpenChange = vi.fn();
  render(<CreateDatasetDialog open onOpenChange={onOpenChange} />);
  return { onOpenChange, user: userEvent.setup() };
}

it('closes on Escape without asking when nothing was entered', async () => {
  const { onOpenChange, user } = setup();
  await user.keyboard('{Escape}');
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
});

it('asks before closing a filled-in form on Escape', async () => {
  const { onOpenChange, user } = setup();
  await user.type(screen.getByLabelText('Dataset Title'), 'Trees');
  await user.keyboard('{Escape}');
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  expect(onOpenChange).not.toHaveBeenCalled();

  await user.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(onOpenChange).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Dataset Title')).toHaveValue('Trees');
});

it('asks before closing a filled-in form on an outside click, then discards on confirm', async () => {
  const { onOpenChange, user } = setup();
  await user.type(screen.getByLabelText('Dataset Title'), 'Trees');
  await user.click(document.querySelector('[data-slot="dialog-overlay"]') as HTMLElement);
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  expect(onOpenChange).not.toHaveBeenCalled();

  await user.click(screen.getByRole('button', { name: 'Discard' }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

it('asks before Cancel closes a dirty form', async () => {
  const { onOpenChange, user } = setup();
  await user.type(screen.getByPlaceholderText('Column Name'), 'height');
  await user.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  expect(onOpenChange).not.toHaveBeenCalled();
});

it('names each column type picker', () => {
  setup();
  expect(screen.getByRole('combobox', { name: 'Type' })).toBeInTheDocument();
});

it('ignores close requests while the create is pending', async () => {
  const { onOpenChange, user } = setup();
  await user.type(screen.getByLabelText('Dataset Title'), 'Trees');
  mutation.isPending = true;
  await user.type(screen.getByLabelText('Dataset Title'), 's');
  await user.keyboard('{Escape}');
  expect(onOpenChange).not.toHaveBeenCalled();
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Dataset Title')).toHaveValue('Treess');
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
});

it('scrolls the body while the footer stays outside it', () => {
  setup();
  const body = screen.getByTestId('create-dataset-body');
  expect(body).toHaveClass('overflow-y-auto');
  expect(body).toContainElement(screen.getByLabelText('Dataset Title'));
  expect(body).toContainElement(screen.getByRole('button', { name: 'Add Column' }));
  expect(body).not.toContainElement(screen.getByRole('button', { name: 'Cancel' }));
  expect(body).not.toContainElement(screen.getByRole('button', { name: 'Create Dataset' }));
});

it('scrolls a new column into view and focuses its name field', async () => {
  const scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  const { user } = setup();
  await user.click(screen.getByRole('button', { name: 'Add Column' }));
  const names = screen.getAllByPlaceholderText('Column Name');
  expect(names).toHaveLength(2);
  expect(names[1]).toHaveFocus();
  expect(scrollIntoView).toHaveBeenCalled();
});

it.each(['{ArrowDown}', '{ArrowUp}', '{Enter}', ' '])(
  'opens the type picker with %s and moves within the list',
  async (key) => {
    const { user } = setup();
    screen.getByRole('combobox', { name: 'Type' }).focus();
    await user.keyboard(key);
    expect(await screen.findByRole('listbox')).toBeInTheDocument();
    await user.keyboard('{ArrowDown}');
    expect(screen.getAllByRole('option').some((o) => o === document.activeElement)).toBe(true);
  },
);
