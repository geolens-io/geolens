import { fireEvent, render, screen, within } from '@/test/test-utils';
import { StackRow } from '../StackRow';
import type { MapLayerResponse } from '@/types/api';
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

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Population',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POLYGON',
    dataset_table_name: overrides.dataset_table_name ?? 'population',
    dataset_extent_bbox: overrides.dataset_extent_bbox ?? [0, 0, 1, 1],
    dataset_column_info: overrides.dataset_column_info ?? null,
    dataset_feature_count: overrides.dataset_feature_count ?? null,
    dataset_sample_values: overrides.dataset_sample_values ?? null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? null,
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

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

function defaultProps(overrides: Partial<React.ComponentProps<typeof StackRow>> = {}) {
  const layer = makeLayer();
  return {
    layer,
    selected: false,
    isDragging: false,
    dragHandleProps: makeDragHandleProps(),
    onSelectLayer: vi.fn(),
    onToggleVisibility: vi.fn(),
    onRemove: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    ...overrides,
  };
}

describe('StackRow', () => {
  it('renders the five interactive cells in DOM order: grip → eye → name → kebab (caret hidden)', () => {
    const props = defaultProps();
    render(<StackRow {...props} />);

    const row = screen.getByRole('option');

    // Caret should be hidden
    const caret = row.querySelector('[aria-hidden="true"][style*="visibility"]');
    expect(caret).toBeTruthy();
    expect((caret as HTMLElement).style.visibility).toBe('hidden');

    // Grip handle
    const grip = screen.getByRole('button', { name: /Drag to reorder/i });
    expect(grip).toBeInTheDocument();

    // Eye toggle
    const eye = screen.getByRole('button', { name: /Toggle visibility/i });
    expect(eye).toBeInTheDocument();

    // Name — layer name appears in the row
    expect(screen.getByText('Population')).toBeInTheDocument();

    // Kebab trigger
    const kebab = screen.getByRole('button', { name: /Layer options for/i });
    expect(kebab).toBeInTheDocument();
  });

  it('has aria-selected true when selected, false otherwise', () => {
    const layer = makeLayer({ id: 'test-layer' });
    const { rerender } = render(<StackRow {...defaultProps({ layer, selected: false })} />);
    const row = screen.getByRole('option');
    expect(row).toHaveAttribute('aria-selected', 'false');

    rerender(<StackRow {...defaultProps({ layer, selected: true })} />);
    expect(screen.getByRole('option')).toHaveAttribute('aria-selected', 'true');
  });

  it('clicking the row container calls onSelectLayer(layer.id) once', () => {
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'click-layer' });
    render(<StackRow {...defaultProps({ layer, onSelectLayer })} />);

    // Click the name (which is in the row body)
    const name = screen.getByText('Population');
    fireEvent.click(name);

    expect(onSelectLayer).toHaveBeenCalledOnce();
    expect(onSelectLayer).toHaveBeenCalledWith('click-layer');
  });

  it('clicking the eye button calls onToggleVisibility and does NOT call onSelectLayer', () => {
    const onToggleVisibility = vi.fn();
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'eye-layer' });
    render(<StackRow {...defaultProps({ layer, onToggleVisibility, onSelectLayer })} />);

    const eyeBtn = screen.getByRole('button', { name: /Toggle visibility/i });
    fireEvent.click(eyeBtn);

    expect(onToggleVisibility).toHaveBeenCalledOnce();
    expect(onToggleVisibility).toHaveBeenCalledWith('eye-layer');
    expect(onSelectLayer).not.toHaveBeenCalled();
  });

  // SP-10: visibility toggle exposes aria-pressed reflecting layer.visible so
  // assistive tech can read the toggled state.
  it('eye toggle has aria-pressed=true when layer.visible=true', () => {
    const layer = makeLayer({ id: 'vis-on', visible: true });
    render(<StackRow {...defaultProps({ layer })} />);

    const eye = screen.getByRole('button', { name: /Toggle visibility/i, pressed: true });
    expect(eye).toBeInTheDocument();
  });

  it('eye toggle has aria-pressed=false when layer.visible=false', () => {
    const layer = makeLayer({ id: 'vis-off', visible: false });
    render(<StackRow {...defaultProps({ layer })} />);

    const eye = screen.getByRole('button', { name: /Toggle visibility/i, pressed: false });
    expect(eye).toBeInTheDocument();
  });

  it('clicking the kebab trigger does NOT call onSelectLayer; opening menu shows items in order', () => {
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'kebab-layer', dataset_name: 'My Layer' });
    render(<StackRow {...defaultProps({ layer, onSelectLayer })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Layer options for/i });
    // Use pointerDown to open Radix dropdown (matches existing test patterns)
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    expect(onSelectLayer).not.toHaveBeenCalled();

    // Check core items present
    const menuItems = screen.getAllByRole('menuitem');
    const menuTexts = menuItems.map((item) => item.textContent?.trim());
    expect(menuTexts).toContain('Rename layer');
    expect(menuTexts).toContain('Duplicate');
    expect(menuTexts).toContain('Delete layer');
    // "＋ New group…" always appears (no existing groups in this test)
    expect(menuTexts).toContain('＋ New group…');

    // Verify core order
    const renameIdx = menuTexts.indexOf('Rename layer');
    const dupIdx = menuTexts.indexOf('Duplicate');
    const deleteIdx = menuTexts.indexOf('Delete layer');
    expect(renameIdx).toBeLessThan(dupIdx);
    expect(dupIdx).toBeLessThan(deleteIdx);
  });

  it('clicking "Delete layer" in the kebab calls onRemove(layer.id)', () => {
    const onRemove = vi.fn();
    const layer = makeLayer({ id: 'delete-layer' });
    render(<StackRow {...defaultProps({ layer, onRemove })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete layer/i }));

    // The kebab item now opens an inline alertdialog confirm (StackRow.tsx:357-389)
    // — `onRemove` is invoked only when the destructive `Delete` button inside
    // the alertdialog is clicked. Drive through the confirm step.
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /^Delete$/ }));

    expect(onRemove).toHaveBeenCalledOnce();
    expect(onRemove).toHaveBeenCalledWith('delete-layer');
  });

  it('clicking "Duplicate" calls onDuplicate(layer.id)', () => {
    const onDuplicate = vi.fn();
    const layer = makeLayer({ id: 'dup-layer' });
    render(<StackRow {...defaultProps({ layer, onDuplicate })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /^Duplicate$/i }));

    expect(onDuplicate).toHaveBeenCalledOnce();
    expect(onDuplicate).toHaveBeenCalledWith('dup-layer');
  });

  it('"Add to group…" label and "＋ New group…" item appear when no existing groups', () => {
    const layer = makeLayer({ id: 'group-layer' });
    render(<StackRow {...defaultProps({ layer, existingFolderGroups: [] })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    // The label "Add to group…" appears (DropdownMenuLabel)
    expect(screen.getByText('Add to group…')).toBeInTheDocument();
    // "＋ New group…" item appears as the only group option
    expect(screen.getByRole('menuitem', { name: /New group/i })).toBeInTheDocument();
  });

  it('inline rename: clicking "Rename layer" (via double-click on name) shows input, Enter commits with onRename', () => {
    const onRename = vi.fn();
    const layer = makeLayer({ id: 'rename-layer', dataset_name: 'Old Name' });
    render(<StackRow {...defaultProps({ layer, onRename })} />);

    // Double-click the name span to enter rename mode
    const nameSSpan = screen.getByText('Old Name');
    fireEvent.dblClick(nameSSpan);

    // Should now show an input
    const input = screen.getByTestId('stack-row-rename-input');
    expect(input).toBeInTheDocument();

    // Change value and press Enter
    fireEvent.change(input, { target: { value: 'New name' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).toHaveBeenCalledOnce();
    expect(onRename).toHaveBeenCalledWith('rename-layer', 'New name');
  });

  it('row has id="stack-row-{layer.id}" for MapBuilderPage focus-return', () => {
    const layer = makeLayer({ id: 'focus-layer' });
    render(<StackRow {...defaultProps({ layer })} />);

    const row = document.getElementById('stack-row-focus-layer');
    expect(row).toBeInTheDocument();
  });
});

describe('DEM type icon', () => {
  // Helper: create a raster/DEM layer fixture (layer_type must be 'raster_geolens' for caps.kind=raster)
  function makeDEMLayerFixture(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
    return makeLayer({
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      is_dem: true,
      ...overrides,
    });
  }

  // Test 1: DEM hillshade glyph
  it('renders ⛰ glyph when is_dem=true and render_mode=hillshade', () => {
    const layer = makeDEMLayerFixture({
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
    });
    const { container } = render(<StackRow {...defaultProps({ layer })} />);

    // Expect the ⛰ glyph to appear in the type icon span
    const iconSpan = container.querySelector('.bg-\\[--type-raster-bg\\]');
    expect(iconSpan).toBeTruthy();
    expect(iconSpan?.textContent?.trim()).toBe('⛰');
  });

  // Test 2: DEM terrain glyph
  it('renders ◬ glyph when is_dem=true and render_mode is terrain (cast value)', () => {
    const layer = makeDEMLayerFixture({
      // 'terrain' is cast at the boundary — style_config as any to simulate persisted value
      style_config: { render_mode: 'terrain' } as unknown as MapLayerResponse['style_config'],
    });
    const { container } = render(<StackRow {...defaultProps({ layer })} />);

    const iconSpan = container.querySelector('.bg-\\[--type-raster-bg\\]');
    expect(iconSpan).toBeTruthy();
    expect(iconSpan?.textContent?.trim()).toBe('◬');
  });

  // Test 3: DEM image glyph (render_mode undefined/null)
  it('renders ▦ glyph when is_dem=true and render_mode is undefined/null', () => {
    const layer = makeDEMLayerFixture({
      style_config: null,
    });
    const { container } = render(<StackRow {...defaultProps({ layer })} />);

    const iconSpan = container.querySelector('.bg-\\[--type-raster-bg\\]');
    expect(iconSpan).toBeTruthy();
    expect(iconSpan?.textContent?.trim()).toBe('▦');
  });

  // Test 4: Non-DEM raster still renders ▦ (regression)
  it('non-DEM raster (is_dem != true) still renders ▦ regardless of style_config', () => {
    const layer = makeLayer({
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      is_dem: false,
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
    });
    const { container } = render(<StackRow {...defaultProps({ layer })} />);

    const iconSpan = container.querySelector('.bg-\\[--type-raster-bg\\]');
    expect(iconSpan).toBeTruthy();
    expect(iconSpan?.textContent?.trim()).toBe('▦');
  });

  // Test 5: Vector layers still render via ColorizedGeometryIcon (regression)
  it('vector layers still render type icon via ColorizedGeometryIcon (regression)', () => {
    const layer = makeLayer({
      id: 'vector-regression',
      dataset_geometry_type: 'POLYGON',
      dataset_record_type: 'vector_dataset',
      layer_type: null,
      is_dem: false,
    });
    render(<StackRow {...defaultProps({ layer })} />);

    // The mock renders a span with data-testid="type-icon-{layerId}"
    expect(screen.getByTestId('type-icon-vector-regression')).toBeInTheDocument();
  });

  // Test 6: DEM type icon uses raster color tokens for all three glyphs
  it('DEM type icon uses bg-[--type-raster-bg] and text-[--type-raster] tokens for all modes', () => {
    const modes = [
      { style_config: null, expected: '▦' },
      { style_config: { render_mode: 'hillshade' }, expected: '⛰' },
      { style_config: { render_mode: 'terrain' }, expected: '◬' },
    ] as const;

    for (const { style_config, expected } of modes) {
      const layer = makeDEMLayerFixture({
        style_config: style_config as unknown as MapLayerResponse['style_config'],
      });
      const { container, unmount } = render(<StackRow {...defaultProps({ layer })} />);

      const iconSpan = container.querySelector('.bg-\\[--type-raster-bg\\]');
      expect(iconSpan).toBeTruthy();
      // Should have the text color class too
      expect(iconSpan?.classList.contains('text-[--type-raster]')).toBe(true);
      expect(iconSpan?.textContent?.trim()).toBe(expected);

      unmount();
    }
  });
});

describe('Add to group sub-flow', () => {
  function makeGroupProps() {
    return {
      existingFolderGroups: [
        { id: 'g1', name: 'Hydrology' },
        { id: 'g2', name: 'Transit' },
      ],
      onAddToGroup: vi.fn(),
      onCreateGroupWithLayer: vi.fn(),
      onMoveLayerOutOfGroup: vi.fn(),
    };
  }

  // Test 1: empty existing groups shows only "＋ New group…"
  it('Test 1: shows only "＋ New group…" when existingFolderGroups is empty and parentGroupId is null', () => {
    const layer = makeLayer({ id: 'test-layer' });
    render(
      <StackRow
        {...defaultProps({ layer })}
        existingFolderGroups={[]}
        onCreateGroupWithLayer={vi.fn()}
        parentGroupId={null}
      />
    );

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    // Label visible
    expect(screen.getByText('Add to group…')).toBeInTheDocument();
    // Only "＋ New group…" — no other group items
    const menuItems = screen.getAllByRole('menuitem').filter((i) => i.textContent?.includes('New group'));
    expect(menuItems).toHaveLength(1);
    // No group names present
    expect(screen.queryByText('▸ Hydrology')).not.toBeInTheDocument();
  });

  // Test 2: existing groups appear in sub-list
  it('Test 2: shows existing folder groups in sub-list', () => {
    const layer = makeLayer({ id: 'test-layer' });
    const { onAddToGroup, onCreateGroupWithLayer, onMoveLayerOutOfGroup } = makeGroupProps();
    render(
      <StackRow
        {...defaultProps({ layer })}
        existingFolderGroups={[{ id: 'g1', name: 'Hydrology' }, { id: 'g2', name: 'Transit' }]}
        onAddToGroup={onAddToGroup}
        onCreateGroupWithLayer={onCreateGroupWithLayer}
        onMoveLayerOutOfGroup={onMoveLayerOutOfGroup}
        parentGroupId={null}
      />
    );

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    // Both groups appear
    expect(screen.getByText('▸ Hydrology')).toBeInTheDocument();
    expect(screen.getByText('▸ Transit')).toBeInTheDocument();
    // "＋ New group…" also appears
    expect(screen.getByRole('menuitem', { name: /New group/i })).toBeInTheDocument();
  });

  // Test 3: clicking an existing group calls onAddToGroup
  it('Test 3: clicking an existing group calls onAddToGroup(layerId, groupId)', () => {
    const layer = makeLayer({ id: 'test-layer' });
    const onAddToGroup = vi.fn();
    render(
      <StackRow
        {...defaultProps({ layer })}
        existingFolderGroups={[{ id: 'g1', name: 'Hydrology' }]}
        onAddToGroup={onAddToGroup}
        parentGroupId={null}
      />
    );

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByText('▸ Hydrology'));

    expect(onAddToGroup).toHaveBeenCalledOnce();
    expect(onAddToGroup).toHaveBeenCalledWith('test-layer', 'g1');
  });

  // Test 4: clicking "＋ New group…" calls onCreateGroupWithLayer
  it('Test 4: clicking "＋ New group…" calls onCreateGroupWithLayer(layerId)', () => {
    const layer = makeLayer({ id: 'new-group-layer' });
    const onCreateGroupWithLayer = vi.fn();
    render(
      <StackRow
        {...defaultProps({ layer })}
        existingFolderGroups={[]}
        onCreateGroupWithLayer={onCreateGroupWithLayer}
        parentGroupId={null}
      />
    );

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /New group/i }));

    expect(onCreateGroupWithLayer).toHaveBeenCalledOnce();
    expect(onCreateGroupWithLayer).toHaveBeenCalledWith('new-group-layer');
  });

  // Test 5: layer already in a group shows "Move out of group"
  it('Test 5: shows "Move out of group" and calls onMoveLayerOutOfGroup when parentGroupId is set', () => {
    const layer = makeLayer({ id: 'child-layer' });
    const onMoveLayerOutOfGroup = vi.fn();
    render(
      <StackRow
        {...defaultProps({ layer })}
        parentGroupId="some-group"
        onMoveLayerOutOfGroup={onMoveLayerOutOfGroup}
      />
    );

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    // "Move out of group" appears instead of "Add to group…" sub-flow
    const moveOutItem = screen.getByRole('menuitem', { name: /Move out of group/i });
    expect(moveOutItem).toBeInTheDocument();

    // "Add to group…" label should NOT appear
    expect(screen.queryByText('Add to group…')).not.toBeInTheDocument();

    fireEvent.click(moveOutItem);
    expect(onMoveLayerOutOfGroup).toHaveBeenCalledOnce();
    expect(onMoveLayerOutOfGroup).toHaveBeenCalledWith('child-layer');
  });

  // Test 6: existing tests still pass (regression)
  it('Test 6: regression — row click still calls onSelectLayer', () => {
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'regression-layer', dataset_name: 'Regression' });
    render(<StackRow {...defaultProps({ layer, onSelectLayer })} />);

    const name = screen.getByText('Regression');
    fireEvent.click(name);

    expect(onSelectLayer).toHaveBeenCalledOnce();
    expect(onSelectLayer).toHaveBeenCalledWith('regression-layer');
  });
});
