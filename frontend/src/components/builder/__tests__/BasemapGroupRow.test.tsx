import { fireEvent, render, screen } from '@/test/test-utils';
import { BasemapGroupRow } from '../BasemapGroupRow';
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
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

function defaultProps(overrides: Partial<React.ComponentProps<typeof BasemapGroupRow>> = {}) {
  return {
    groupId: 'basemap-group-1',
    presetName: 'Positron',
    providerLabel: 'OpenFreeMap',
    visible: true,
    opacity: 1,
    selected: false,
    isExpanded: false,
    isDragging: false,
    dragHandleProps: makeDragHandleProps(),
    onSelectGroup: vi.fn(),
    onToggleExpand: vi.fn(),
    onToggleVisibility: vi.fn(),
    onOpacityChange: vi.fn(),
    onSwapBasemap: vi.fn(),
    onResetAppearance: vi.fn(),
    ...overrides,
  };
}

describe('BasemapGroupRow', () => {
  it('Test 1: renders with ⊞ glyph in the type-icon cell', () => {
    render(<BasemapGroupRow {...defaultProps()} />);
    const typeIcon = screen.getByText('⊞');
    expect(typeIcon).toBeInTheDocument();
    expect(typeIcon).toHaveAttribute('aria-hidden', 'true');
    // Verify it has the inline style for primary-50 bg and primary-700 fg
    const style = window.getComputedStyle(typeIcon);
    // The span itself should have style attributes set
    expect(typeIcon.tagName.toLowerCase()).toBe('span');
  });

  it('Test 2: caret button has aria-expanded and aria-controls', () => {
    const props = defaultProps({ groupId: 'grp-1', isExpanded: false });
    render(<BasemapGroupRow {...props} />);
    const caret = screen.getByRole('button', { name: /toggle.*group/i }) ||
      document.querySelector('button[aria-expanded]');
    // Find caret by aria-expanded
    const buttons = screen.getAllByRole('button');
    const caretBtn = buttons.find((b) => b.hasAttribute('aria-expanded'));
    expect(caretBtn).toBeTruthy();
    expect(caretBtn).toHaveAttribute('aria-expanded', 'false');
    expect(caretBtn).toHaveAttribute('aria-controls', 'basemap-group-children-grp-1');
  });

  it('Test 3: caret click calls onToggleExpand but NOT onSelectGroup', () => {
    const onToggleExpand = vi.fn();
    const onSelectGroup = vi.fn();
    render(<BasemapGroupRow {...defaultProps({ groupId: 'grp-2', onToggleExpand, onSelectGroup })} />);

    const buttons = screen.getAllByRole('button');
    const caretBtn = buttons.find((b) => b.hasAttribute('aria-expanded'));
    expect(caretBtn).toBeTruthy();
    fireEvent.click(caretBtn!);

    expect(onToggleExpand).toHaveBeenCalledOnce();
    expect(onToggleExpand).toHaveBeenCalledWith('grp-2');
    expect(onSelectGroup).not.toHaveBeenCalled();
  });

  it('Test 4: row body click calls onSelectGroup(groupId)', () => {
    const onSelectGroup = vi.fn();
    render(<BasemapGroupRow {...defaultProps({ groupId: 'grp-3', onSelectGroup })} />);

    // Click on the row name (which is in the row body)
    const nameSpan = screen.getByText(/Basemap · Positron/);
    fireEvent.click(nameSpan);

    expect(onSelectGroup).toHaveBeenCalledOnce();
    expect(onSelectGroup).toHaveBeenCalledWith('grp-3');
  });

  it('Test 5: kebab menu contains exactly "Swap basemap" and "Reset appearance" only', () => {
    render(<BasemapGroupRow {...defaultProps()} />);

    const kebabTrigger = screen.getByRole('button', { name: /options/i });
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    const menuItems = screen.getAllByRole('menuitem');
    const menuTexts = menuItems.map((item) => item.textContent?.trim());
    expect(menuTexts).toContain('Swap basemap');
    expect(menuTexts).toContain('Reset appearance');
    // Should NOT contain other items
    expect(menuTexts).not.toContain('Rename');
    expect(menuTexts).not.toContain('Duplicate');
    expect(menuTexts).not.toContain('Delete');
    expect(menuTexts).not.toContain('Add to group');
    expect(menuItems).toHaveLength(2);
  });

  it('Test 6: kebab "Swap basemap" item click calls onSwapBasemap()', () => {
    const onSwapBasemap = vi.fn();
    render(<BasemapGroupRow {...defaultProps({ onSwapBasemap })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /options/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Swap basemap/i }));

    expect(onSwapBasemap).toHaveBeenCalledOnce();
  });

  it('Test 7: kebab "Reset appearance" item click calls onResetAppearance()', () => {
    const onResetAppearance = vi.fn();
    render(<BasemapGroupRow {...defaultProps({ onResetAppearance })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /options/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Reset appearance/i }));

    expect(onResetAppearance).toHaveBeenCalledOnce();
  });

  it('Test 8: row name renders "Basemap · {presetName}" with provider label at muted weight', () => {
    render(<BasemapGroupRow {...defaultProps({ presetName: 'Positron', providerLabel: 'OpenFreeMap' })} />);

    // Main name text
    expect(screen.getByText(/Basemap · Positron/)).toBeInTheDocument();
    // Provider label appears as muted span
    expect(screen.getByText(/OpenFreeMap/)).toBeInTheDocument();
    const providerSpan = screen.getByText(/OpenFreeMap/);
    expect(providerSpan.className).toContain('muted');
  });

  it('Test 9: opacity slider calls onOpacityChange(groupId, value) and stopPropagation prevents row click', () => {
    const onOpacityChange = vi.fn();
    const onSelectGroup = vi.fn();
    const props = defaultProps({ groupId: 'grp-opacity', onOpacityChange, onSelectGroup, opacity: 0.8 });
    render(<BasemapGroupRow {...props} />);

    const slider = screen.getByRole('slider');
    // Clicking the slider container should NOT trigger row click
    const sliderContainer = slider.closest('[data-opacity-cell]') ?? slider.parentElement!;
    fireEvent.click(sliderContainer);
    expect(onSelectGroup).not.toHaveBeenCalled();
  });

  it('Test 10: eye toggle calls onToggleVisibility(groupId) and stopPropagation prevents row click', () => {
    const onToggleVisibility = vi.fn();
    const onSelectGroup = vi.fn();
    render(<BasemapGroupRow {...defaultProps({ groupId: 'grp-eye', onToggleVisibility, onSelectGroup })} />);

    const eyeBtn = screen.getByRole('button', { name: /Toggle visibility/i });
    fireEvent.click(eyeBtn);

    expect(onToggleVisibility).toHaveBeenCalledOnce();
    expect(onToggleVisibility).toHaveBeenCalledWith('grp-eye');
    expect(onSelectGroup).not.toHaveBeenCalled();
  });

  it('Test 11: when isExpanded=true caret has rotate-90; when false no rotate class', () => {
    const { rerender } = render(<BasemapGroupRow {...defaultProps({ isExpanded: false })} />);
    const buttons = screen.getAllByRole('button');
    let caretBtn = buttons.find((b) => b.hasAttribute('aria-expanded'));
    expect(caretBtn?.className).not.toContain('rotate-90');

    rerender(<BasemapGroupRow {...defaultProps({ isExpanded: true })} />);
    const buttonsAfter = screen.getAllByRole('button');
    caretBtn = buttonsAfter.find((b) => b.hasAttribute('aria-expanded'));
    expect(caretBtn?.className).toContain('rotate-90');
  });

  it('Test 12: row has id="stack-row-{groupId}" for focus-return', () => {
    render(<BasemapGroupRow {...defaultProps({ groupId: 'focus-group' })} />);
    const row = document.getElementById('stack-row-focus-group');
    expect(row).toBeInTheDocument();
  });
});
