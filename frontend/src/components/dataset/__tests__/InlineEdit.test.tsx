/**
 * BUG-040: InlineEdit save() must wrap onSave in try/catch.
 * A thrown onSave must NOT strand the editor or produce an unhandled rejection.
 * It MUST call toast.error with a translated key.
 *
 * Tests are RED pre-fix (onSave throw → unhandled rejection, editing stays true
 * but no toast) and GREEN post-fix.
 */
import { render, fireEvent, waitFor } from '@testing-library/react';
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

describe('InlineEdit allowClear (#458 E-04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function enterEditAndClear(container: HTMLElement) {
    const displayEl = container.querySelector('[role="button"]') as HTMLElement;
    fireEvent.click(displayEl);
    const input = container.querySelector('input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Enter' });
  }

  it('emits an emptied value when allowClear is set', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <InlineEdit value="existing text" onSave={onSave} canEdit allowClear />,
    );

    enterEditAndClear(container);

    await waitFor(() => expect(onSave).toHaveBeenCalledWith(''));
  });

  it('drops an emptied value without allowClear (title-style fields)', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <InlineEdit value="existing text" onSave={onSave} canEdit />,
    );

    enterEditAndClear(container);

    await waitFor(() => {
      const input = container.querySelector('input');
      expect(input).toBeNull(); // editor closed
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('does not emit a clear when the value was already empty', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <InlineEdit value="" onSave={onSave} canEdit allowClear placeholder="add" />,
    );

    enterEditAndClear(container);

    await waitFor(() => {
      const input = container.querySelector('input');
      expect(input).toBeNull();
    });
    expect(onSave).not.toHaveBeenCalled();
  });
});

/**
 * fix(#458 E-32): multiline drafts had no working save affordance —
 * (1) the unmount cleanup re-ran whenever the parent passed a new inline-arrow
 *     onDirtyChange, instantly self-reverting the dirty flag (so the
 *     pending-edits bar never appeared), and
 * (2) Ctrl+Enter was the only save path; blur cancelled. Visible Save/Cancel
 *     buttons now commit without being defeated by the textarea blur.
 */
describe('InlineEdit multiline (E-32)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderMultiline(onDirtyChange: (d: boolean) => void, onSave = vi.fn()) {
    const view = render(
      <InlineEdit
        value="original"
        onSave={onSave}
        canEdit
        multiline
        onDirtyChange={onDirtyChange}
      />,
    );
    const displayEl = view.container.querySelector('[role="button"]') as HTMLElement;
    fireEvent.click(displayEl);
    return view;
  }

  it('keeps the dirty flag when the parent re-renders with a new onDirtyChange identity', () => {
    const dirtyCalls: boolean[] = [];
    const { container, rerender } = renderMultiline((d) => dirtyCalls.push(d));

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited value' } });
    expect(dirtyCalls).toEqual([true]);

    // Parent re-render with a NEW inline arrow — exactly what DetailPanel/
    // SourceQualityTab do. The old [emitDirtyChange]-dep cleanup fired
    // onDirtyChange(false) here, self-reverting the flag.
    rerender(
      <InlineEdit
        value="original"
        onSave={vi.fn()}
        canEdit
        multiline
        onDirtyChange={(d) => dirtyCalls.push(d)}
      />,
    );
    expect(dirtyCalls).toEqual([true]);
  });

  it('clears the dirty flag on true unmount', () => {
    const dirtyCalls: boolean[] = [];
    const { container, unmount } = renderMultiline((d) => dirtyCalls.push(d));
    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited value' } });
    unmount();
    expect(dirtyCalls).toEqual([true, false]);
  });

  it('saves via the visible Save button despite the textarea blur-cancel', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container, getByText } = renderMultiline(vi.fn(), onSave);

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited value' } });

    const saveBtn = getByText('common:save');
    // mousedown is prevented so blur→cancel can't fire first; click commits.
    fireEvent.mouseDown(saveBtn);
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith('edited value');
    });
  });

  it('cancels via the visible Cancel button without saving', () => {
    const onSave = vi.fn();
    const { container, getByText } = renderMultiline(vi.fn(), onSave);

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited value' } });

    const cancelBtn = getByText('common:cancel');
    fireEvent.mouseDown(cancelBtn);
    fireEvent.click(cancelBtn);

    expect(onSave).not.toHaveBeenCalled();
    expect(container.querySelector('textarea')).toBeNull();
  });
});

/**
 * fix(#528 review): Tab from the textarea to the editor's own Save/Cancel
 * buttons must not blur-cancel — keyboard users need to reach the buttons.
 */
describe('InlineEdit multiline keyboard reachability (#528 review)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the editor open when focus moves to its own Save button, and Save commits', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container, getByText } = render(
      <InlineEdit value="original" onSave={onSave} canEdit multiline />,
    );
    fireEvent.click(container.querySelector('[role="button"]') as HTMLElement);

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited value' } });

    const saveBtn = getByText('common:save');
    // Simulate Tab: blur with focus landing on the editor's own button.
    fireEvent.blur(textarea, { relatedTarget: saveBtn });
    expect(container.querySelector('textarea')).not.toBeNull();

    fireEvent.click(saveBtn);
    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith('edited value');
    });
  });

  it('still cancels when focus leaves the editor entirely', () => {
    const onSave = vi.fn();
    const { container } = render(
      <InlineEdit value="original" onSave={onSave} canEdit multiline />,
    );
    fireEvent.click(container.querySelector('[role="button"]') as HTMLElement);

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited value' } });
    fireEvent.blur(textarea, { relatedTarget: document.body });

    expect(container.querySelector('textarea')).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
  });
});
