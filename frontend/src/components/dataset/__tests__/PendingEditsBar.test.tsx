import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PendingEditsBar } from '@/components/dataset/PendingEditsBar';
import { InlineEdit } from '@/components/dataset/InlineEdit';

describe('PendingEditsBar', () => {
  it('does not render when there are no pending edits', () => {
    render(
      <PendingEditsBar
        pendingCount={0}
        onSaveAll={vi.fn()}
        onCancelAll={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument();
  });

  it('renders pending count and action buttons when drafts are dirty', () => {
    render(
      <PendingEditsBar
        pendingCount={2}
        onSaveAll={vi.fn()}
        onCancelAll={vi.fn()}
      />,
    );

    expect(screen.getByTestId('pending-edits-bar')).toBeInTheDocument();
    expect(screen.getByTestId('pending-edits-count')).toHaveTextContent('2 unsaved changes');
    expect(screen.getByTestId('pending-edits-save')).toHaveTextContent('Save');
    expect(screen.getByTestId('pending-edits-cancel')).toHaveTextContent('Discard');
  });

  it('wires save and cancel actions to callbacks', async () => {
    const user = userEvent.setup();
    const onSaveAll = vi.fn();
    const onCancelAll = vi.fn();

    render(
      <PendingEditsBar
        pendingCount={1}
        onSaveAll={onSaveAll}
        onCancelAll={onCancelAll}
      />,
    );

    await user.click(screen.getByTestId('pending-edits-cancel'));
    await user.click(screen.getByTestId('pending-edits-save'));

    expect(onCancelAll).toHaveBeenCalledTimes(1);
    expect(onSaveAll).toHaveBeenCalledTimes(1);
  });

  it('shows saving state and disables save button while submitting', () => {
    render(
      <PendingEditsBar
        pendingCount={1}
        onSaveAll={vi.fn()}
        onCancelAll={vi.fn()}
        isSaving
      />,
    );

    expect(screen.getByTestId('pending-edits-save')).toBeDisabled();
    expect(screen.getByTestId('pending-edits-save')).toHaveTextContent('Saving...');
  });
});

describe('InlineEdit dirty lifecycle', () => {
  it('emits dirty state changes while editing and canceling', async () => {
    const user = userEvent.setup();
    const onDirtyChange = vi.fn();

    render(
      <InlineEdit
        value="Original summary"
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDirtyChange={onDirtyChange}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Original summary' }));

    const input = screen.getByDisplayValue('Original summary');
    await user.clear(input);
    await user.type(input, 'Updated summary');

    expect(onDirtyChange).toHaveBeenCalledWith(true);

    await user.keyboard('{Escape}');

    expect(onDirtyChange).toHaveBeenCalledWith(false);
  });
});

