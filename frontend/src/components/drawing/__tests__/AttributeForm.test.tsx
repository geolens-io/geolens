import { act, fireEvent, render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AttributeForm } from '@/components/drawing/AttributeForm';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('AttributeForm submission', () => {
  it('keeps the form stable and blocks duplicate edits while a save is pending', async () => {
    const save = deferred();
    const onSubmit = vi.fn(() => save.promise);
    render(
      <AttributeForm
        open
        onOpenChange={vi.fn()}
        columns={[{ name: 'population', type: 'integer' }]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    const input = screen.getByLabelText('population');
    const saveButton = screen.getByRole('button', { name: 'common:save' });
    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(saveButton);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(input).toBeDisabled();
    expect(saveButton).toBeDisabled();
    fireEvent.click(saveButton);
    expect(onSubmit).toHaveBeenCalledTimes(1);

    await act(async () => {
      save.resolve();
      await save.promise;
    });

    expect(input).toBeEnabled();
    expect(input).toHaveValue(250);
  });

  it('blocks Escape dismissal while a save is pending', async () => {
    const save = deferred();
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    render(
      <AttributeForm
        open
        onOpenChange={onOpenChange}
        columns={[{ name: 'population', type: 'integer' }]}
        onSubmit={() => save.promise}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'common:save' }));
    await user.keyboard('{Escape}');

    expect(onOpenChange).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve();
      await save.promise;
    });
  });
});
