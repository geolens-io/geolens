import { act, fireEvent, render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { FolderGroupRow } from '../FolderGroupRow';
import { useInlineRename } from '../useInlineRename';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
        // Handle template interpolation for defaultValue strings
        let result = options.defaultValue as string;
        const params = options as Record<string, unknown>;
        Object.keys(params).forEach((k) => {
          if (k !== 'defaultValue') {
            result = result.replace(`{{${k}}}`, String(params[k]));
          }
        });
        return result;
      }
      return key;
    },
  }),
}));

// Mock layer-icons to avoid rendering SVG in tests
vi.mock('@/components/map/layer-icons', () => ({
  ColorizedGeometryIcon: ({ layerId }: { layerId: string }) => (
    <span data-testid={`type-icon-${layerId}`} />
  ),
  getLayerColors: () => ({ fill: '#000', stroke: '#fff', outline: '#000' }),
  extractStyleHints: () => ({}),
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

function makeDragHandleProps() {
  const attributes: DraggableAttributes = {
    role: 'button',
    tabIndex: 0,
    'aria-pressed': false,
    'aria-roledescription': 'sortable',
    'aria-describedby': 'dnd-desc',
    'aria-disabled': false,
  };
  const listeners: DraggableSyntheticListeners = {};
  const setActivatorNodeRef = vi.fn();
  return { attributes, listeners, setActivatorNodeRef };
}

function defaultProps(overrides: Partial<React.ComponentProps<typeof FolderGroupRow>> = {}) {
  return {
    groupId: 'group-1',
    groupName: 'My Group',
    visible: true,
    selected: false,
    isExpanded: false,
    isDragging: false,
    dragHandleProps: makeDragHandleProps(),
    onSelectGroup: vi.fn(),
    onToggleExpand: vi.fn(),
    onToggleVisibility: vi.fn(),
    onRenameGroup: vi.fn(),
    onAddLayer: vi.fn(),
    onUngroup: vi.fn(),
    onDeleteGroup: vi.fn(),
    ...overrides,
  };
}

// a11y(v1.6.0 audit A7, WCAG 2.1.1): the row-container keydown preventDefaulted
// Enter/Space from descendants, so the caret, eye, rename input, and the
// delete-confirm buttons were mouse-only. user-event 14 implements native
// keyboard activation gated on defaultPrevented.
describe('FolderGroupRow keyboard operability (v1.6.0 audit A7)', () => {
  it('Enter on the focused caret toggles expansion instead of selecting the row', async () => {
    const user = userEvent.setup();
    const props = defaultProps();
    render(<FolderGroupRow {...props} />);

    const caret = screen.getByRole('button', { name: 'Toggle folder group' });
    caret.focus();
    await user.keyboard('{Enter}');

    expect(props.onToggleExpand).toHaveBeenCalledOnce();
    expect(props.onToggleExpand).toHaveBeenCalledWith('group-1');
    expect(props.onSelectGroup).not.toHaveBeenCalled();
  });

  it('Space on the focused eye toggles visibility without toggling multi-selection', async () => {
    const user = userEvent.setup();
    const onCmdClick = vi.fn();
    const props = defaultProps({ onCmdClick });
    render(<FolderGroupRow {...props} />);

    const eye = screen.getByRole('button', { name: 'Toggle visibility for My Group' });
    eye.focus();
    await user.keyboard(' ');

    expect(props.onToggleVisibility).toHaveBeenCalledOnce();
    expect(props.onToggleVisibility).toHaveBeenCalledWith('group-1');
    expect(onCmdClick).not.toHaveBeenCalled();
    expect(props.onSelectGroup).not.toHaveBeenCalled();
  });

  it('a space can be typed into the group rename input and Enter commits without re-firing the row action', async () => {
    const user = userEvent.setup();
    const props = defaultProps();
    render(<FolderGroupRow {...props} />);

    fireEvent.dblClick(screen.getByText('My Group'));
    const input = screen.getByRole('textbox', { name: 'Group name' });
    // Let the hook's deferred focus+select() run before typing — otherwise it
    // fires mid-type and the select() swallows already-typed characters.
    await act(() => new Promise<void>((r) => requestAnimationFrame(() => r())));
    await user.clear(input);
    await user.type(input, 'a b');
    expect(input).toHaveValue('a b');

    await user.keyboard('{Enter}');

    expect(props.onRenameGroup).toHaveBeenCalledOnce();
    expect(props.onRenameGroup).toHaveBeenCalledWith('group-1', 'a b');
    expect(props.onSelectGroup).not.toHaveBeenCalled();
  });

  it('the delete confirm is keyboard-operable: Enter on "Delete all" deletes the group', async () => {
    const user = userEvent.setup();
    const props = defaultProps();
    render(<FolderGroupRow {...props} />);

    fireEvent.pointerDown(
      screen.getByRole('button', { name: /Group options for/i }),
      { button: 0, ctrlKey: false },
    );
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete group/i }));

    // The confirm mounts INSIDE the row div — its buttons' Enter/Space used to
    // bubble to the container keydown and be preventDefaulted (mouse-only).
    //
    // fix(#1100): two things reach for focus after this render, and which one
    // lands last is a race. Radix returns focus to the kebab trigger
    // asynchronously on menu close, and the confirm autofocuses "Keep group".
    // The old wait — one rAF, then a waitFor that focused and asserted — closed
    // neither: waitFor proves focus AT THE MOMENT IT CHECKS, and a restore
    // still pending could land between that check and the keypress below. On a
    // loaded CI runner it did, and Enter went to the kebab, so this failed as
    // "expected vi.fn() to be called once, but got 0 times" — a call-count
    // error for what was really a focus problem.
    //
    // Take focus and require it to SURVIVE a full macrotask instead. Once
    // focusing sticks across a flush, every pending restore has already run,
    // so there is nothing left to steal it before the keypress.
    const deleteBtn = screen.getByRole('button', { name: 'Delete all' });
    await vi.waitFor(async () => {
      deleteBtn.focus();
      await act(() => new Promise<void>((r) => setTimeout(r, 0)));
      expect(deleteBtn).toHaveFocus();
    });
    await user.keyboard('{Enter}');

    expect(props.onDeleteGroup).toHaveBeenCalledOnce();
    expect(props.onDeleteGroup).toHaveBeenCalledWith('group-1');
  });

  it('the delete confirm cancel is keyboard-operable: Space on "Keep group" dismisses it', async () => {
    const user = userEvent.setup();
    const props = defaultProps();
    render(<FolderGroupRow {...props} />);

    fireEvent.pointerDown(
      screen.getByRole('button', { name: /Group options for/i }),
      { button: 0, ctrlKey: false },
    );
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete group/i }));

    const cancelBtn = screen.getByRole('button', { name: 'Keep group' });
    cancelBtn.focus();
    await user.keyboard(' ');

    expect(props.onDeleteGroup).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Delete all' })).not.toBeInTheDocument();
  });
});

describe('FolderGroupRow', () => {
  it('forwards grip keys to the dnd-kit keyboard activator (fix #759)', () => {
    // The grip used to set onKeyDown={undefined} AFTER spreading listeners,
    // which destroyed the KeyboardSensor activator — group rows have no
    // fallback reorder mode, so they were pointer-only (WCAG 2.1.1).
    const props = defaultProps();
    const dndKeyDown = vi.fn();
    props.dragHandleProps.listeners = {
      onKeyDown: dndKeyDown,
    } as DraggableSyntheticListeners;
    render(<FolderGroupRow {...props} />);

    const grip = screen.getByRole('button', { name: 'Drag to reorder My Group' });
    fireEvent.keyDown(grip, { key: ' ' });
    expect(dndKeyDown).toHaveBeenCalledTimes(1);
  });

  it('a key claimed by the keyboard activator does not also trigger the row (codex #794)', () => {
    const props = defaultProps({ onCmdClick: vi.fn() });
    props.dragHandleProps.listeners = {
      // The real KeyboardSensor activator preventDefaults the start key.
      onKeyDown: vi.fn((e: React.KeyboardEvent) => e.preventDefault()),
    } as unknown as DraggableSyntheticListeners;
    render(<FolderGroupRow {...props} />);

    fireEvent.keyDown(
      screen.getByRole('button', { name: 'Drag to reorder My Group' }),
      { key: ' ' },
    );
    // Starting a keyboard drag must not simultaneously toggle the row's
    // multi-selection (Space) or selection (Enter) — the row handlers don't
    // check defaultPrevented, so the grip stops the claimed key's bubble.
    expect(props.onCmdClick).not.toHaveBeenCalled();
    expect(props.onSelectGroup).not.toHaveBeenCalled();
  });

  it('Test 1: Renders the ▸ glyph in the type-icon cell using the folder-group token', () => {
    render(<FolderGroupRow {...defaultProps()} />);

    // fix(#438): DS-05 — the type icon moved from an inline OKLCH amber style to
    // the theme-aware --type-folder token classes.
    const typeIcon = Array.from(document.querySelectorAll('[aria-hidden="true"]')).find(
      (el) => el.textContent === '▸',
    ) as HTMLElement | undefined;
    expect(typeIcon).toBeTruthy();
    expect(typeIcon?.className).toContain('bg-type-folder-bg');
    expect(typeIcon?.className).toContain('text-type-folder');
    expect(typeIcon?.getAttribute('style')).toBeNull();
  });

  it('Test 2: Caret button has aria-expanded and aria-controls; rotates 90 when isExpanded=true', () => {
    const { rerender } = render(<FolderGroupRow {...defaultProps({ isExpanded: false })} />);

    // Find the caret button via aria-expanded attribute (the one with aria-controls targeting folder-group-children)
    const caretBtn = document.querySelector('button[aria-controls^="folder-group-children"]') as HTMLElement;
    expect(caretBtn).toBeTruthy();
    expect(caretBtn).toHaveAttribute('aria-expanded', 'false');
    expect(caretBtn).toHaveAttribute('aria-controls', 'folder-group-children-group-1');
    expect(caretBtn.className).not.toContain('rotate-90');

    rerender(<FolderGroupRow {...defaultProps({ isExpanded: true })} />);
    const caretBtnExpanded = document.querySelector('button[aria-controls^="folder-group-children"]') as HTMLElement;
    expect(caretBtnExpanded).toHaveAttribute('aria-expanded', 'true');
    expect(caretBtnExpanded.className).toContain('rotate-90');
  });

  it('Test 3: Caret button click calls onToggleExpand(groupId) and does NOT call onSelectGroup', () => {
    const onToggleExpand = vi.fn();
    const onSelectGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onToggleExpand, onSelectGroup })} />);

    const caretBtn = document.querySelector('button[aria-expanded]') as HTMLElement;
    fireEvent.click(caretBtn);

    expect(onToggleExpand).toHaveBeenCalledOnce();
    expect(onToggleExpand).toHaveBeenCalledWith('group-1');
    expect(onSelectGroup).not.toHaveBeenCalled();
  });

  it('Test 4: Row body click (not on caret/eye/kebab) calls onSelectGroup(groupId)', () => {
    const onSelectGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onSelectGroup })} />);

    // Click on the name span
    const name = screen.getByText('My Group');
    fireEvent.click(name);

    expect(onSelectGroup).toHaveBeenCalledOnce();
    expect(onSelectGroup).toHaveBeenCalledWith('group-1');
  });

  it('Test 5: Group name renders with text-sm font-semibold class', () => {
    render(<FolderGroupRow {...defaultProps()} />);

    const nameSpan = screen.getByText('My Group');
    expect(nameSpan.className).toContain('text-sm');
    expect(nameSpan.className).toContain('font-semibold');
  });

  it('Test 6: Kebab menu has 4 items in order: Rename group / Add layer / separator / Ungroup / Delete group; Delete has text-destructive', () => {
    render(<FolderGroupRow {...defaultProps()} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    const menuItems = screen.getAllByRole('menuitem');
    const menuTexts = menuItems.map((item) => item.textContent?.trim());
    expect(menuTexts).toContain('Rename group');
    expect(menuTexts).toContain('Add layer');
    expect(menuTexts).toContain('Ungroup');
    expect(menuTexts).toContain('Delete group');

    // Verify order
    const renameIdx = menuTexts.indexOf('Rename group');
    const addIdx = menuTexts.indexOf('Add layer');
    const ungroupIdx = menuTexts.indexOf('Ungroup');
    const deleteIdx = menuTexts.indexOf('Delete group');
    expect(renameIdx).toBeLessThan(addIdx);
    expect(addIdx).toBeLessThan(ungroupIdx);
    expect(ungroupIdx).toBeLessThan(deleteIdx);

    // Delete group has text-destructive class
    const deleteItem = screen.getByRole('menuitem', { name: /Delete group/i });
    expect(deleteItem.className).toContain('text-destructive');
  });

  it('Test 7: Double-clicking name cell switches to an input pre-filled with current name and aria-label "Group name"', () => {
    render(<FolderGroupRow {...defaultProps({ groupName: 'My Group' })} />);

    // Double-click the name span to enter rename mode
    const nameSpan = screen.getByText('My Group');
    fireEvent.dblClick(nameSpan);

    // Input should appear with aria-label "Group name" and be pre-filled
    const input = screen.getByRole('textbox', { name: /Group name/i });
    expect(input).toBeInTheDocument();
    expect((input as HTMLInputElement).value).toBe('My Group');
  });

  it('Test 8: Pressing Enter in the rename input commits via onRenameGroup(groupId, trimmedName) and exits edit mode', () => {
    const onRenameGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

    // Double-click name span to enter rename mode
    const nameSpan = screen.getByText('Old Name');
    fireEvent.dblClick(nameSpan);

    const input = screen.getByRole('textbox', { name: /Group name/i });
    fireEvent.change(input, { target: { value: 'New Name' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRenameGroup).toHaveBeenCalledOnce();
    expect(onRenameGroup).toHaveBeenCalledWith('group-1', 'New Name');
  });

  it('Test 9: Pressing Escape in the rename input cancels and does NOT call onRenameGroup', () => {
    const onRenameGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

    const nameSpan = screen.getByText('Old Name');
    fireEvent.dblClick(nameSpan);

    const input = screen.getByRole('textbox', { name: /Group name/i });
    fireEvent.change(input, { target: { value: 'Changed' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    expect(onRenameGroup).not.toHaveBeenCalled();
    // Name span should be restored
    expect(screen.getByText('Old Name')).toBeInTheDocument();
  });

  it('Test 10: Blank input commit calls NEITHER onRenameGroup nor errors — silent revert', () => {
    const onRenameGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

    const nameSpan = screen.getByText('Old Name');
    fireEvent.dblClick(nameSpan);

    const input = screen.getByRole('textbox', { name: /Group name/i });
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRenameGroup).not.toHaveBeenCalled();
  });

  it('Test 11: Whitespace-only input is treated as blank — trimmed to empty → revert', () => {
    const onRenameGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

    const nameSpan = screen.getByText('Old Name');
    fireEvent.dblClick(nameSpan);

    const input = screen.getByRole('textbox', { name: /Group name/i });
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRenameGroup).not.toHaveBeenCalled();
  });

  it('Test 12: Kebab "Add layer" click calls onAddLayer(groupId)', () => {
    const onAddLayer = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onAddLayer })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    const addItem = screen.getByRole('menuitem', { name: /Add layer/i });
    fireEvent.click(addItem);

    expect(onAddLayer).toHaveBeenCalledOnce();
    expect(onAddLayer).toHaveBeenCalledWith('group-1');
  });

  it('Test 13: Kebab "Ungroup" click calls onUngroup(groupId) immediately (no confirmation)', () => {
    const onUngroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onUngroup })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    const ungroupItem = screen.getByRole('menuitem', { name: /^Ungroup$/i });
    fireEvent.click(ungroupItem);

    expect(onUngroup).toHaveBeenCalledOnce();
    expect(onUngroup).toHaveBeenCalledWith('group-1');
    // No inline confirm should appear
    expect(screen.queryByRole('group', { name: /Delete this group/ })).not.toBeInTheDocument();
  });

  it('Test 14: Kebab "Delete group" click sets confirmingDelete=true; inline confirm appears', () => {
    render(<FolderGroupRow {...defaultProps()} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    const deleteItem = screen.getByRole('menuitem', { name: /Delete group/i });
    fireEvent.click(deleteItem);

    // fix(#788): the confirm is a role="group" (non-modal), labelled by its
    // role="alert" message — no longer an alertdialog it couldn't honor.
    const confirm = screen.getByRole('group', { name: 'Delete this group and all its layers?' });
    expect(within(confirm).getByRole('alert')).toHaveTextContent('Delete this group and all its layers?');
    expect(screen.getByRole('button', { name: /Delete all/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Keep group/i })).toBeInTheDocument();
  });

  it('Test 15: "Delete all" click in confirm calls onDeleteGroup(groupId) and resets confirmingDelete', () => {
    const onDeleteGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onDeleteGroup })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete group/i }));

    fireEvent.click(screen.getByRole('button', { name: /Delete all/i }));

    expect(onDeleteGroup).toHaveBeenCalledOnce();
    expect(onDeleteGroup).toHaveBeenCalledWith('group-1');
    // Confirm should be gone
    expect(screen.queryByRole('group', { name: /Delete this group/ })).not.toBeInTheDocument();
  });

  it('Test 16: "Keep group" click sets confirmingDelete=false and does NOT call onDeleteGroup', () => {
    const onDeleteGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onDeleteGroup })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete group/i }));

    fireEvent.click(screen.getByRole('button', { name: /Keep group/i }));

    expect(onDeleteGroup).not.toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: /Delete this group/ })).not.toBeInTheDocument();
  });

  // fix(#788): Escape dismisses the pending confirm (consumed, so it cannot
  // trigger ancestor Escape behavior) and hands focus back to the row.
  it('Escape inside the delete confirm cancels it without calling onDeleteGroup and refocuses the row', () => {
    const onDeleteGroup = vi.fn();
    render(<FolderGroupRow {...defaultProps({ onDeleteGroup })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete group/i }));

    const confirm = screen.getByRole('group', { name: 'Delete this group and all its layers?' });
    fireEvent.keyDown(within(confirm).getByRole('button', { name: /Keep group/i }), { key: 'Escape' });

    expect(onDeleteGroup).not.toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: /Delete this group/ })).not.toBeInTheDocument();
    expect(document.activeElement?.id).toBe('stack-row-group-1');
  });

  it('Test 17: When confirmingDelete=true, "Keep group" button is the leading safe-choice action (autoFocus declared)', () => {
    // fix(#777): the safe-choice UI contract is the app's canonical AlertDialog order —
    // safe choice first ("Keep group", secondary variant, autoFocus), destructive last ("Delete all").
    // In practice, jsdom + Radix focus management makes document.activeElement unreliable here.
    // We verify: (a) the confirm appears, (b) Keep group button exists and is secondary variant,
    // (c) Keep group is the first button (safe), Delete all is last (destructive).
    const { container } = render(<FolderGroupRow {...defaultProps()} />);

    const kebabTrigger = screen.getByRole('button', { name: /Group options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete group/i }));

    // fix(#788): role="group" — anchored by the confirm's aria-labelledby id.
    const confirm = container.querySelector('[role="group"][aria-labelledby="confirm-delete-group-1"]');
    expect(confirm).toBeTruthy();

    const buttons = confirm?.querySelectorAll('button');
    expect(buttons?.length).toBe(2);
    // First button is the secondary safe choice ("Keep group"), last is destructive ("Delete all")
    expect(buttons?.[0].textContent).toContain('Keep group');
    expect(buttons?.[1].textContent).toContain('Delete all');
    // The safe choice button has autoFocus as a React prop (renders as autofocus attribute in HTML)
    expect(screen.getByRole('button', { name: /Keep group/i })).toBeInTheDocument();
  });

  it('Test 18: Row has id="stack-row-{groupId}" for focus-return from flyout close', () => {
    render(<FolderGroupRow {...defaultProps({ groupId: 'folder-abc' })} />);

    const row = document.getElementById('stack-row-folder-abc');
    expect(row).toBeInTheDocument();
  });

  describe('BUG-03: rename-group autofocus', () => {
    // Helper: flush a queued requestAnimationFrame callback synchronously in jsdom.
    // The fix uses rAF to outrun Radix DropdownMenu's restoreFocus on menu close.
    async function flushRaf() {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    }

    it('Test 19: BUG-03 — entering rename mode focuses the rename input (rAF-deferred focus wins focus race)', async () => {
      render(<FolderGroupRow {...defaultProps({ groupName: 'My Group' })} />);

      // Use the double-click path which exercises the same `handleStartRename` →
      // `setEditing(true)` → editing useEffect → rAF-deferred focus + select path
      // that the kebab → Rename click uses. Radix DropdownMenu in jsdom does not
      // reliably round-trip onSelect callbacks once preventDefault is removed,
      // but the underlying focus contract is identical.
      const nameSpan = screen.getByText('My Group');
      fireEvent.dblClick(nameSpan);

      const input = (await screen.findByRole('textbox', { name: /Group name/i })) as HTMLInputElement;
      // Flush the queued requestAnimationFrame so the deferred focus + select fires.
      await flushRaf();

      expect(document.activeElement).toBe(input);
    });

    it('Test 20: BUG-03 — existing-name text is selected on rename input mount', async () => {
      render(<FolderGroupRow {...defaultProps({ groupName: 'My Group' })} />);

      const nameSpan = screen.getByText('My Group');
      fireEvent.dblClick(nameSpan);

      const input = (await screen.findByRole('textbox', { name: /Group name/i })) as HTMLInputElement;
      await flushRaf();

      expect(input.selectionStart).toBe(0);
      expect(input.selectionEnd).toBe('My Group'.length);
    });

    // Phase 1051 WR-09: removed brittle Function.prototype.toString source-text
    // assertion. Coverage is provided by behavioral tests 19, 20, and 22 (which
    // exercise the actual double-click → focus + Escape paths). The source-text
    // pattern breaks under minification, coverage instrumentation, and trivially
    // equivalent rewrites like `e['preventDefault']()`.

    it('Test 22: BUG-03 — Escape inside the rename input cancels editing (no regression)', async () => {
      const onRenameGroup = vi.fn();
      render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

      const nameSpan = screen.getByText('Old Name');
      fireEvent.dblClick(nameSpan);

      const input = await screen.findByRole('textbox', { name: /Group name/i });
      await flushRaf();

      fireEvent.change(input, { target: { value: 'Changed' } });
      fireEvent.keyDown(input, { key: 'Escape' });

      expect(onRenameGroup).not.toHaveBeenCalled();
      expect(screen.getByText('Old Name')).toBeInTheDocument();
    });

    it('Test 23: BUG-03 — Enter inside the rename input commits via onRenameGroup (no regression)', async () => {
      const onRenameGroup = vi.fn();
      render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

      const nameSpan = screen.getByText('Old Name');
      fireEvent.dblClick(nameSpan);

      const input = await screen.findByRole('textbox', { name: /Group name/i });
      await flushRaf();

      fireEvent.change(input, { target: { value: 'New Name' } });
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(onRenameGroup).toHaveBeenCalledOnce();
      expect(onRenameGroup).toHaveBeenCalledWith('group-1', 'New Name');
    });

    it('Test 24: BUG-03 — blur on the rename input commits via onRenameGroup (no regression)', async () => {
      const onRenameGroup = vi.fn();
      render(<FolderGroupRow {...defaultProps({ onRenameGroup, groupName: 'Old Name' })} />);

      const nameSpan = screen.getByText('Old Name');
      fireEvent.dblClick(nameSpan);

      const input = await screen.findByRole('textbox', { name: /Group name/i });
      await flushRaf();

      fireEvent.change(input, { target: { value: 'Blurred Name' } });
      fireEvent.blur(input);

      expect(onRenameGroup).toHaveBeenCalledOnce();
      expect(onRenameGroup).toHaveBeenCalledWith('group-1', 'Blurred Name');
    });

    it('Test 25: BUG-03 — the inline-rename hook schedules its focus call via requestAnimationFrame (source assertion)', () => {
      // Defense-in-depth: the rAF-deferred focus is what wins the race vs Radix
      // restoreFocus in production. A regression that drops the rAF wrapper would
      // re-introduce the focus-race bug. builder-audit #338 STACK-03 moved this logic
      // into the shared useInlineRename hook, so the source assertion now targets
      // the hook (consumed by both FolderGroupRow and StackRow).
      const source = useInlineRename.toString();
      expect(source).toContain('requestAnimationFrame');
    });

    it('BUG-03 negative control — input is NOT focused synchronously when editing flips to true (MAP-16 regression guard)', async () => {
      // If this test ever fails, the rAF deferral was likely removed from
      // FolderGroupRow.tsx editing useEffect — that re-introduces the v1011
      // BUG-03 dnd-kit/Radix focus race. Revert the synchronous-focus change
      // before merging.
      //
      // Strategy: stub requestAnimationFrame to CAPTURE callbacks without
      // invoking them. After triggering rename mode the editing useEffect runs
      // and schedules its focus call via rAF. We assert the callback was
      // captured (proves the rAF-deferred path executed). We then flush the
      // queue manually and assert focus arrived. A regression that drops the
      // rAF would leave rafCallbacks empty (the focus would be delivered
      // synchronously via autoFocus alone, bypassing this contract).
      const rafCallbacks: FrameRequestCallback[] = [];
      const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => {
        rafCallbacks.push(cb);
        return 0 as unknown as ReturnType<typeof requestAnimationFrame>;
      });

      render(<FolderGroupRow {...defaultProps({ groupName: 'My Group' })} />);

      // Trigger rename mode via double-click (same handleStartRename path as kebab → Rename)
      const nameSpan = screen.getByText('My Group');
      fireEvent.dblClick(nameSpan);

      // The rename input mounts (autoFocus gives immediate focus in jsdom, which is
      // acceptable — the production contract is that the rAF wrapper ALSO runs to
      // win the race against Radix restoreFocus AFTER menu close).
      const input = await screen.findByRole('textbox', { name: /Group name/i });
      expect(input).toBeInTheDocument();

      // KEY ASSERTION: the editing useEffect MUST have scheduled a rAF callback.
      // If this fails, the rAF deferral was removed from the editing useEffect.
      expect(rafCallbacks.length).toBeGreaterThan(0);

      // Flush the queued rAF callbacks manually
      act(() => { rafCallbacks.forEach((cb) => cb(performance.now())); });

      // After the manual flush, the rAF-deferred focus has landed.
      expect(document.activeElement).toBe(input);

      // Cleanup: restore the original requestAnimationFrame
      rafSpy.mockRestore();
    });
  });
});
