import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { CreateDatasetDialog } from '../CreateDatasetDialog';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useCreateDataset: () => ({ mutate: vi.fn(), isPending: false }),
}));

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
