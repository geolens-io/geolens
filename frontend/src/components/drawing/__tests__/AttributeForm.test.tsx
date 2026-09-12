import { act, fireEvent, render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { AttributeForm } from '@/components/drawing/AttributeForm';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const originalTimezone = process.env.TZ;

beforeAll(() => {
  process.env.TZ = 'America/New_York';
});

afterAll(() => {
  if (originalTimezone === undefined) delete process.env.TZ;
  else process.env.TZ = originalTimezone;
});

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('AttributeForm submission', () => {
  it('hydrates and preserves an unchanged timezone-aware instant', () => {
    const onSubmit = vi.fn();
    render(
      <AttributeForm
        open
        onOpenChange={vi.fn()}
        columns={[{ name: 'observed_at', type: 'timestamp with time zone' }]}
        initialValues={{ observed_at: '2026-11-01T06:30:00Z' }}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('observed_at')).toHaveValue('2026-11-01T01:30');
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }));
    expect(onSubmit).toHaveBeenCalledWith({ observed_at: '2026-11-01T06:30:00Z' });
  });

  it('hydrates API precision into valid DOM values and preserves full unchanged values', () => {
    const onSubmit = vi.fn();
    render(
      <AttributeForm
        open
        onOpenChange={vi.fn()}
        columns={[
          { name: 'aware_at', type: 'timestamp with time zone' },
          { name: 'local_at', type: 'timestamp without time zone' },
        ]}
        initialValues={{
          aware_at: '2026-07-11T14:30:00.123456Z',
          local_at: '2026-07-11T10:30:00.123456',
        }}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('aware_at')).toHaveValue('2026-07-11T10:30:00.123');
    expect(screen.getByLabelText('local_at')).toHaveValue('2026-07-11T10:30:00.123');
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }));
    expect(onSubmit).toHaveBeenCalledWith({
      aware_at: '2026-07-11T14:30:00.123456Z',
      local_at: '2026-07-11T10:30:00.123456',
    });
  });

  it('converts a new local timestamp to an explicit instant but preserves a naive wall clock', () => {
    const onSubmit = vi.fn();
    render(
      <AttributeForm
        open
        onOpenChange={vi.fn()}
        columns={[
          { name: 'aware_at', type: 'timestamp' },
          { name: 'local_at', type: 'timestamp without time zone' },
        ]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('aware_at'), { target: { value: '2026-07-11T10:30' } });
    fireEvent.change(screen.getByLabelText('local_at'), { target: { value: '2026-07-11T10:30' } });
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }));

    expect(onSubmit).toHaveBeenCalledWith({
      aware_at: '2026-07-11T10:30-04:00',
      local_at: '2026-07-11T10:30',
    });
  });

  it('leaves an invalid DST-gap wall clock unchanged for backend validation', () => {
    const onSubmit = vi.fn();
    render(
      <AttributeForm
        open
        onOpenChange={vi.fn()}
        columns={[{ name: 'aware_at', type: 'timestamp with time zone' }]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('aware_at'), { target: { value: '2026-03-08T02:30' } });
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }));

    expect(onSubmit).toHaveBeenCalledWith({ aware_at: '2026-03-08T02:30' });
    expect(screen.getByLabelText('aware_at')).toHaveValue('2026-03-08T02:30');
  });

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
