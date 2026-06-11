/**
 * BUG-040: InlineEdit save() must wrap onSave in try/catch.
 * A thrown onSave must NOT strand the editor or produce an unhandled rejection.
 * It MUST call toast.error with a translated key.
 *
 * Tests are RED pre-fix (onSave throw → unhandled rejection, editing stays true
 * but no toast) and GREEN post-fix.
 */
import React from 'react';
import { render, fireEvent, waitFor, screen } from '@testing-library/react';
import { InlineEdit } from '@/components/dataset/InlineEdit';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
  }),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

import { toast } from 'sonner';

describe('InlineEdit (BUG-040)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls toast.error and does not strand editor when onSave throws', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('save failed'));

    const { container } = render(
      <InlineEdit value="original" onSave={onSave} canEdit />,
    );

    // Enter edit mode
    const displayEl = container.querySelector('[role="button"]') as HTMLElement;
    fireEvent.click(displayEl);

    const input = container.querySelector('input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'new value' } });

    // Trigger save via Enter key (non-multiline)
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      // toast.error must have been called with a translated key string
      expect(toast.error).toHaveBeenCalledTimes(1);
    });

    // Editor must not be stranded — it should exit editing mode after the error
    expect(container.querySelector('input')).toBeNull();
  });

  it('calls toast.error and does not strand editor when onSave throws via blur', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('network error'));

    const { container } = render(
      <InlineEdit value="original" onSave={onSave} canEdit />,
    );

    // Enter edit mode
    const displayEl = container.querySelector('[role="button"]') as HTMLElement;
    fireEvent.click(displayEl);

    const input = container.querySelector('input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'changed value' } });

    // Trigger save via blur
    fireEvent.blur(input);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1);
    });

    // Editor must exit editing mode
    expect(container.querySelector('input')).toBeNull();
  });

  it('does NOT call toast when onSave succeeds', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);

    const { container } = render(
      <InlineEdit value="original" onSave={onSave} canEdit />,
    );

    const displayEl = container.querySelector('[role="button"]') as HTMLElement;
    fireEvent.click(displayEl);

    const input = container.querySelector('input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'new value' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      // no input means editing exited
      expect(container.querySelector('input')).toBeNull();
    });

    expect(toast.error).not.toHaveBeenCalled();
  });
});
