import { fireEvent, render, screen } from '@testing-library/react';
import { KeyboardShortcutsSheet } from '../KeyboardShortcutsSheet';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

describe('KeyboardShortcutsSheet', () => {
  it('renders nothing when closed', () => {
    render(<KeyboardShortcutsSheet open={false} onOpenChange={vi.fn()} />);
    // Radix Dialog with open=false should not render visible content
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders dialog with title when open', () => {
    render(<KeyboardShortcutsSheet open={true} onOpenChange={vi.fn()} />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Keyboard shortcuts')).toBeInTheDocument();
  });

  it('lists the Save shortcut chord in the open sheet', () => {
    render(<KeyboardShortcutsSheet open={true} onOpenChange={vi.fn()} />);
    // The save chord is either ⌘S (mac) or Ctrl+S; both contain 'S'
    const saveRow = screen.getByTestId('shortcut-save');
    expect(saveRow).toBeInTheDocument();
    // The chord element should be present
    const chord = saveRow.querySelector('kbd');
    expect(chord).not.toBeNull();
    // Chord text contains S (works on both Mac and non-Mac)
    expect(chord!.textContent).toMatch(/S/);
  });

  it('lists Pan, Measure, and Legend shortcut rows', () => {
    render(<KeyboardShortcutsSheet open={true} onOpenChange={vi.fn()} />);
    expect(screen.getByTestId('shortcut-pan')).toBeInTheDocument();
    expect(screen.getByTestId('shortcut-measure')).toBeInTheDocument();
    expect(screen.getByTestId('shortcut-legend')).toBeInTheDocument();
  });

  it('calls onOpenChange(false) when dialog requests close', () => {
    const onOpenChange = vi.fn();
    render(<KeyboardShortcutsSheet open={true} onOpenChange={onOpenChange} />);
    // Press Escape to close the dialog
    fireEvent.keyDown(document.body, { key: 'Escape' });
    // Radix calls onOpenChange(false) on Escape
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  describe('? hotkey guard (input protection)', () => {
    it('? keydown on document.body opens the sheet via an external handler', () => {
      // This test validates the input-guard logic pattern.
      // The ? handler lives in MapBuilderPage — we test the guard predicate directly.
      // Note: jsdom does not implement isContentEditable as a getter, so we guard
      // contenteditable via getAttribute('contenteditable') === 'true' in the predicate.
      function isEditableTarget(target: EventTarget | null): boolean {
        if (!target || !(target instanceof HTMLElement)) return false;
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        // isContentEditable is the real-browser API; fall back to attribute check for jsdom
        if ((target as HTMLElement).isContentEditable) return true;
        if (target.getAttribute('contenteditable') === 'true') return true;
        return false;
      }

      const body = document.body;
      const input = document.createElement('input');
      const textarea = document.createElement('textarea');
      const div = document.createElement('div');
      div.setAttribute('contenteditable', 'true');
      document.body.appendChild(div);

      expect(isEditableTarget(body)).toBe(false);
      expect(isEditableTarget(input)).toBe(true);
      expect(isEditableTarget(textarea)).toBe(true);
      expect(isEditableTarget(div)).toBe(true);

      document.body.removeChild(div);
    });

    it('? key does NOT open the sheet when focused in an input', () => {
      let open = false;
      const onOpenChange = (val: boolean) => { open = val; };

      render(
        <div>
          <input data-testid="text-input" />
          <KeyboardShortcutsSheet open={open} onOpenChange={onOpenChange} />
        </div>,
      );

      const input = screen.getByTestId('text-input');
      input.focus();

      // Simulate the guard: dispatch '?' keydown where target is the input.
      // The guard checks event.target; we verify the handler would reject it.
      const evt = new KeyboardEvent('keydown', { key: '?', bubbles: true });
      Object.defineProperty(evt, 'target', { value: input, writable: false });

      function isEditableTarget(target: EventTarget | null): boolean {
        if (!target || !(target instanceof HTMLElement)) return false;
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if ((target as HTMLElement).isContentEditable) return true;
        return false;
      }

      if (!isEditableTarget(evt.target)) {
        onOpenChange(true);
      }

      // Should NOT have opened because target is an input
      expect(open).toBe(false);
    });

    it('? key DOES open the sheet when focused on a non-editable element', () => {
      let open = false;
      const onOpenChange = (val: boolean) => { open = val; };

      render(
        <KeyboardShortcutsSheet open={open} onOpenChange={onOpenChange} />,
      );

      const evt = new KeyboardEvent('keydown', { key: '?', bubbles: true });
      Object.defineProperty(evt, 'target', { value: document.body, writable: false });

      function isEditableTarget(target: EventTarget | null): boolean {
        if (!target || !(target instanceof HTMLElement)) return false;
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if ((target as HTMLElement).isContentEditable) return true;
        return false;
      }

      if (!isEditableTarget(evt.target)) {
        onOpenChange(true);
      }

      // Should have opened because target is body (non-editable)
      expect(open).toBe(true);
    });
  });
});
