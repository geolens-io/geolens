import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditableFieldShell } from '@/components/dataset/EditableFieldShell';
import type { DatasetEditCapability } from '@/hooks/use-dataset-edit-capabilities';

function renderShell(capability: DatasetEditCapability, onAttemptEdit?: () => void) {
  return render(
    <EditableFieldShell capability={capability} onAttemptEdit={onAttemptEdit}>
      <span>Summary</span>
    </EditableFieldShell>,
  );
}

describe('EditableFieldShell', () => {
  it('renders editable state with pencil icon and invokes edit callback', async () => {
    const user = userEvent.setup();
    const onAttemptEdit = vi.fn();

    renderShell({
      editable: true,
      canAttempt: true,
      reason: null,
      helper: 'Click to edit this field.',
    }, onAttemptEdit);

    const shell = screen.getByTestId('editable-field-shell');
    expect(shell).toHaveAttribute('data-editable', 'true');
    expect(shell).toHaveClass('bg-primary/5');
    expect(screen.getByTestId('editable-field-shell-icon')).toBeInTheDocument();
    expect(screen.queryByTestId('role-capability-hint')).not.toBeInTheDocument();

    await user.click(shell);

    expect(onAttemptEdit).toHaveBeenCalledTimes(1);
  });

  it('keeps role-denied behavior unchanged for non-editor attempts', async () => {
    const user = userEvent.setup();
    const onAttemptEdit = vi.fn();

    renderShell(
      {
        editable: false,
        canAttempt: true,
        reason: 'insufficient_role',
        helper: 'You can view this field. Editors can make changes.',
      },
      onAttemptEdit,
    );

    expect(screen.queryByTestId('role-capability-hint')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /summary/i }));

    expect(onAttemptEdit).not.toHaveBeenCalled();
    expect(screen.getByTestId('role-capability-hint')).toBeInTheDocument();
    expect(screen.getByText(/you can view this field/i)).toBeInTheDocument();
  });

  it('does not show hint for read-only fields', () => {
    renderShell({
      editable: false,
      canAttempt: false,
      reason: 'read_only_field',
      helper: 'This field is read-only.',
    });

    expect(screen.queryByTestId('role-capability-hint')).not.toBeInTheDocument();
  });
});
