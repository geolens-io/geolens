import { act, fireEvent, render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { StackRow } from '../StackRow';
import { MAP_COLORS } from '@/lib/map-colors';
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

// fix(#452): no layer-icons mock — the type icon (glyph chip + colorized
// vector icon) is now the shared LayerTypeIcon inside that module, so the DEM
// glyph tests below exercise the real rendering path end-to-end.

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
  describe('keyboard reorder mode (fix #759)', () => {
    const gripName = 'Drag to reorder Population';

    it('announces arm, moves, and drop, and reflects the mode in aria-pressed', () => {
      const onAnnounce = vi.fn();
      const onKeyboardReorder = vi.fn();
      render(<StackRow {...defaultProps({ onAnnounce, onKeyboardReorder })} />);
      const handle = screen.getByRole('button', { name: gripName });
      expect(handle).toHaveAttribute('aria-pressed', 'false');

      fireEvent.keyDown(handle, { key: ' ' });
      expect(handle).toHaveAttribute('aria-pressed', 'true');
      expect(onAnnounce).toHaveBeenCalledWith(
        expect.stringContaining('Reorder mode on for Population'),
      );

      fireEvent.keyDown(handle, { key: 'ArrowUp' });
      expect(onKeyboardReorder).toHaveBeenCalledWith('layer-1', 'up');
      expect(onAnnounce).toHaveBeenCalledWith('Population moved up.');

      fireEvent.keyDown(handle, { key: ' ' });
      expect(handle).toHaveAttribute('aria-pressed', 'false');
      expect(onAnnounce).toHaveBeenCalledWith('Population dropped.');
    });

    it('stays silent when a boundary move does not happen (codex #794)', () => {
      const onAnnounce = vi.fn();
      const onKeyboardReorder = vi.fn(() => false);
      render(<StackRow {...defaultProps({ onAnnounce, onKeyboardReorder })} />);
      const handle = screen.getByRole('button', { name: gripName });
      fireEvent.keyDown(handle, { key: ' ' });
      fireEvent.keyDown(handle, { key: 'ArrowUp' });
      expect(onKeyboardReorder).toHaveBeenCalledWith('layer-1', 'up');
      expect(onAnnounce).not.toHaveBeenCalledWith('Population moved up.');
    });

    it('reports pressed during a pointer drag (codex #794)', () => {
      render(<StackRow {...defaultProps({ isDragging: true })} />);
      expect(
        screen.getByRole('button', { name: gripName }),
      ).toHaveAttribute('aria-pressed', 'true');
    });

    it('announces the exit on Escape without promising a revert (codex #794)', () => {
      const onAnnounce = vi.fn();
      render(<StackRow {...defaultProps({ onAnnounce })} />);
      const handle = screen.getByRole('button', { name: gripName });
      fireEvent.keyDown(handle, { key: ' ' });
      fireEvent.keyDown(handle, { key: 'Escape' });
      // Moves apply immediately in this mode, so Escape must not announce
      // "Drop cancelled" — nothing is reverted.
      expect(onAnnounce).toHaveBeenCalledWith('Population dropped.');
      expect(onAnnounce).not.toHaveBeenCalledWith('Drop cancelled.');
      expect(handle).toHaveAttribute('aria-pressed', 'false');
    });

    it('keeps claimed keys from the dnd-kit activator but forwards the rest', () => {
      const dndKeyDown = vi.fn();
      const props = defaultProps();
      props.dragHandleProps.listeners = {
        onKeyDown: dndKeyDown,
      } as DraggableSyntheticListeners;
      render(<StackRow {...props} />);
      const handle = screen.getByRole('button', { name: gripName });

      // Space is claimed by the fallback reorder mode (preventDefault), so
      // the sensor must NOT also start a keyboard drag.
      fireEvent.keyDown(handle, { key: ' ' });
      expect(dndKeyDown).not.toHaveBeenCalled();
      fireEvent.keyDown(handle, { key: 'Escape' });

      // A key the row does not claim still reaches the sensor.
      fireEvent.keyDown(handle, { key: 'a' });
      expect(dndKeyDown).toHaveBeenCalledTimes(1);
    });
  });

  it('renders the five interactive cells in DOM order: grip → eye → name → kebab (caret hidden)', () => {
    const props = defaultProps();
    render(<StackRow {...props} />);

    // Phase 1052: dropped role="option" from row; locate by id instead.
    const row = document.getElementById(`stack-row-${props.layer.id}`);
    expect(row).not.toBeNull();

    // Caret should be hidden
    const caret = row!.querySelector('[aria-hidden="true"][style*="visibility"]');
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

  it('keyboard drag handle reorders after Space + Arrow key', () => {
    const onKeyboardReorder = vi.fn();
    const layer = makeLayer({ id: 'keyboard-layer' });
    render(<StackRow {...defaultProps({ layer, onKeyboardReorder })} />);

    const grip = screen.getByRole('button', { name: /Drag to reorder/i });
    fireEvent.keyDown(grip, { key: ' ' });
    fireEvent.keyDown(grip, { key: 'ArrowUp' });
    fireEvent.keyDown(grip, { key: 'ArrowDown' });
    fireEvent.keyDown(grip, { key: ' ' });
    fireEvent.keyDown(grip, { key: 'ArrowUp' });

    expect(onKeyboardReorder).toHaveBeenNthCalledWith(1, 'keyboard-layer', 'up');
    expect(onKeyboardReorder).toHaveBeenNthCalledWith(2, 'keyboard-layer', 'down');
    expect(onKeyboardReorder).toHaveBeenCalledTimes(2);
  });

  it('reflects selection via aria-current + data-selected (Phase 1052: dropped role=option)', () => {
    const layer = makeLayer({ id: 'test-layer' });
    const { rerender } = render(<StackRow {...defaultProps({ layer, selected: false })} />);
    const row = document.getElementById(`stack-row-${layer.id}`);
    expect(row).not.toBeNull();
    expect(row).not.toHaveAttribute('aria-current');
    expect(row).not.toHaveAttribute('data-selected');

    rerender(<StackRow {...defaultProps({ layer, selected: true })} />);
    const selectedRow = document.getElementById(`stack-row-${layer.id}`);
    expect(selectedRow).toHaveAttribute('aria-current', 'true');
    expect(selectedRow).toHaveAttribute('data-selected', 'true');
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
    // fix(#585): the group flow lives behind an "Add to group…" submenu trigger
    expect(screen.getByTestId('kebab-add-to-group')).toBeInTheDocument();

    // Verify core order
    const renameIdx = menuTexts.indexOf('Rename layer');
    const dupIdx = menuTexts.indexOf('Duplicate');
    const deleteIdx = menuTexts.indexOf('Delete layer');
    expect(renameIdx).toBeLessThan(dupIdx);
    expect(dupIdx).toBeLessThan(deleteIdx);
  });

  // fix(#585): right-click / Shift+F10 open the same kebab menu.
  it('right-clicking the row opens the kebab menu without selecting the row', () => {
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'ctx-layer' });
    render(<StackRow {...defaultProps({ layer, onSelectLayer })} />);

    fireEvent.contextMenu(document.getElementById('stack-row-ctx-layer')!);

    expect(onSelectLayer).not.toHaveBeenCalled();
    expect(screen.getByRole('menuitem', { name: /Rename layer/i })).toBeInTheDocument();
  });

  it('Shift+F10 on the row opens the kebab menu', () => {
    const layer = makeLayer({ id: 'kbd-ctx-layer' });
    render(<StackRow {...defaultProps({ layer })} />);

    fireEvent.keyDown(document.getElementById('stack-row-kbd-ctx-layer')!, { key: 'F10', shiftKey: true });

    expect(screen.getByRole('menuitem', { name: /Rename layer/i })).toBeInTheDocument();
  });

  it('clicking "Delete layer" in the kebab calls onRemove(layer.id)', () => {
    const onRemove = vi.fn();
    const layer = makeLayer({ id: 'delete-layer' });
    render(<StackRow {...defaultProps({ layer, onRemove })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete layer/i }));

    // The kebab item opens an inline confirm — `onRemove` is invoked only when
    // the destructive `Delete` button inside it is clicked. fix(#788): the
    // confirm is a role="group" (non-modal), labelled by its role="alert"
    // message, no longer an alertdialog it couldn't honor.
    const confirm = screen.getByRole('group', { name: 'Are you sure? This cannot be undone.' });
    expect(within(confirm).getByRole('alert')).toHaveTextContent('Are you sure? This cannot be undone.');
    fireEvent.click(within(confirm).getByRole('button', { name: /^Delete$/ }));

    expect(onRemove).toHaveBeenCalledOnce();
    expect(onRemove).toHaveBeenCalledWith('delete-layer');
  });

  // fix(#788): Escape dismisses the pending confirm (consumed, so it cannot
  // trigger ancestor Escape behavior) and hands focus back to the row.
  it('Escape inside the delete confirm cancels it without calling onRemove and refocuses the row', () => {
    const onRemove = vi.fn();
    const layer = makeLayer({ id: 'esc-layer' });
    render(<StackRow {...defaultProps({ layer, onRemove })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete layer/i }));

    const confirm = screen.getByRole('group', { name: 'Are you sure? This cannot be undone.' });
    fireEvent.keyDown(within(confirm).getByRole('button', { name: /Keep layer/i }), { key: 'Escape' });

    expect(onRemove).not.toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: 'Are you sure? This cannot be undone.' })).not.toBeInTheDocument();
    expect(document.activeElement?.id).toBe('stack-row-esc-layer');
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

  // fix(#585): the kebab links to the dataset detail page — new tab so the
  // unsaved-changes guard never fires mid-edit.
  it('kebab "Open dataset detail" is a new-tab link to /datasets/{dataset_id}', () => {
    const layer = makeLayer({ id: 'link-layer', dataset_id: 'ds-42' });
    render(<StackRow {...defaultProps({ layer })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    const link = screen.getByTestId('kebab-view-dataset');
    expect(link).toHaveAttribute('href', '/datasets/ds-42');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  // ux(#772): kebab entry into the Analysis panel, prefilled with this layer.
  it('kebab "Analyze this layer" calls onAnalyzeLayer for an analysable layer', () => {
    const onAnalyzeLayer = vi.fn();
    const layer = makeLayer({ id: 'analyzable-layer' });
    render(<StackRow {...defaultProps({ layer, onAnalyzeLayer })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByTestId('kebab-analyze-layer'));

    expect(onAnalyzeLayer).toHaveBeenCalledOnce();
    expect(onAnalyzeLayer).toHaveBeenCalledWith('analyzable-layer');
  });

  it('hides "Analyze this layer" for a layer the panel would not offer (ux #772)', () => {
    const layer = makeLayer({
      id: 'raster-layer',
      dataset_record_type: 'raster_dataset',
      dataset_geometry_type: null,
    });
    render(<StackRow {...defaultProps({ layer, onAnalyzeLayer: vi.fn() })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    // The menu is open (its siblings render) but the analysis entry is gated
    // on the panel's own eligibility predicate.
    expect(screen.getByTestId('kebab-zoom-to-layer')).toBeInTheDocument();
    expect(screen.queryByTestId('kebab-analyze-layer')).toBeNull();
  });

  it('hides "Analyze this layer" when no handler is wired (ux #772)', () => {
    render(<StackRow {...defaultProps()} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    expect(screen.getByTestId('kebab-zoom-to-layer')).toBeInTheDocument();
    expect(screen.queryByTestId('kebab-analyze-layer')).toBeNull();
  });

  it('"Add to group…" submenu exposes "New group…" when no existing groups (#585)', () => {
    const layer = makeLayer({ id: 'group-layer' });
    render(<StackRow {...defaultProps({ layer, existingFolderGroups: [] })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

    // fix(#585): "Add to group…" is a submenu trigger; its content mounts on open
    const subTrigger = screen.getByTestId('kebab-add-to-group');
    fireEvent.click(subTrigger);
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

  // Phase 1199 STACK-01: live duplicate "Copy N of M" disambiguation badge.
  describe('disambiguation badge (STACK-01)', () => {
    it('renders "Copy 1 of 2" / "Copy 2 of 2" on both duplicate rows and none on a single layer', () => {
      // Two renderings of the same dataset, mirroring how UnifiedStackPanel
      // computes a per-layer label via map-stack's shared helper.
      const layerA = makeLayer({ id: 'dup-a', dataset_name: 'Counties' });
      const layerB = makeLayer({ id: 'dup-b', dataset_name: 'Counties' });

      const { rerender } = render(
        <StackRow {...defaultProps({ layer: layerA })} disambiguationLabel="Copy 1 of 2" />
      );
      const badgeA = screen.getByTestId('stack-row-disambiguation');
      expect(badgeA).toHaveTextContent('Copy 1 of 2');

      rerender(
        <StackRow {...defaultProps({ layer: layerB })} disambiguationLabel="Copy 2 of 2" />
      );
      const badgeB = screen.getByTestId('stack-row-disambiguation');
      expect(badgeB).toHaveTextContent('Copy 2 of 2');
    });

    it('renders no disambiguation badge when disambiguationLabel is null', () => {
      const layer = makeLayer({ id: 'single-layer' });
      render(<StackRow {...defaultProps({ layer })} disambiguationLabel={null} />);
      expect(screen.queryByTestId('stack-row-disambiguation')).not.toBeInTheDocument();
    });

    it('renders no disambiguation badge when disambiguationLabel is omitted (default)', () => {
      const layer = makeLayer({ id: 'no-prop-layer' });
      render(<StackRow {...defaultProps({ layer })} />);
      expect(screen.queryByTestId('stack-row-disambiguation')).not.toBeInTheDocument();
    });
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
    const { container } = render(<StackRow {...defaultProps({ layer })} />);

    // Real ColorizedGeometryIcon output for a single-color POLYGON: a filled
    // Pentagon SVG (the centralized map-icon fallback) — and no raster glyph chip.
    expect(container.querySelector(`svg[fill="${MAP_COLORS.icon.fallback}"]`)).toBeInTheDocument();
    expect(screen.queryByText('▦')).not.toBeInTheDocument();
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

  // codex(#451): the "draws nothing" badge (overlay off + not the terrain
  // source) keeps an eye-on DEM row honest; absent otherwise.
  it('renders the draws-nothing badge only when drawsNothing is set', () => {
    const layer = makeDEMLayerFixture({
      style_config: { render_mode: 'terrain' } as unknown as MapLayerResponse['style_config'],
    });

    const { rerender } = render(<StackRow {...defaultProps({ layer })} drawsNothing={false} />);
    expect(screen.queryByTestId('stack-row-draws-nothing')).not.toBeInTheDocument();

    rerender(<StackRow {...defaultProps({ layer })} drawsNothing />);
    expect(screen.getByTestId('stack-row-draws-nothing')).toBeInTheDocument();
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

  // Test 1: empty existing groups shows only "New group…"
  it('Test 1: shows only "New group…" when existingFolderGroups is empty and parentGroupId is null', () => {
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

    // fix(#585): open the "Add to group…" submenu first
    fireEvent.click(screen.getByTestId('kebab-add-to-group'));
    // Only "New group…" — no other group items
    const menuItems = screen.getAllByRole('menuitem').filter((i) => i.textContent?.includes('New group'));
    expect(menuItems).toHaveLength(1);
    // No group names present
    expect(screen.queryByText('Hydrology')).not.toBeInTheDocument();
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

    // fix(#585): open the "Add to group…" submenu first
    fireEvent.click(screen.getByTestId('kebab-add-to-group'));
    // Both groups appear
    expect(screen.getByText('Hydrology')).toBeInTheDocument();
    expect(screen.getByText('Transit')).toBeInTheDocument();
    // "New group…" also appears
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
    // fix(#585): open the "Add to group…" submenu first
    fireEvent.click(screen.getByTestId('kebab-add-to-group'));
    fireEvent.click(screen.getByText('Hydrology'));

    expect(onAddToGroup).toHaveBeenCalledOnce();
    expect(onAddToGroup).toHaveBeenCalledWith('test-layer', 'g1');
  });

  // Test 4: clicking "New group…" calls onCreateGroupWithLayer
  it('Test 4: clicking "New group…" calls onCreateGroupWithLayer(layerId)', () => {
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
    // fix(#585): open the "Add to group…" submenu first
    fireEvent.click(screen.getByTestId('kebab-add-to-group'));
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

  // ---------------------------------------------------------------------------
  // v3 design — Source moved from panel section into row kebab menu
  // ---------------------------------------------------------------------------
  describe('Source info in kebab menu', () => {
    it('opens kebab and shows the Source info block with dataset metadata', () => {
      const layer = makeLayer({
        id: 'src-layer',
        dataset_name: 'Reefs (10m)',
        dataset_feature_count: 1043,
        dataset_geometry_type: 'MULTILINESTRING',
      });
      render(<StackRow {...defaultProps({ layer })} />);

      fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

      const sourceBlock = screen.getByTestId('stack-row-kebab-source');
      expect(sourceBlock).toBeInTheDocument();
      expect(sourceBlock).toHaveTextContent('Reefs (10m)');
      expect(sourceBlock).toHaveTextContent('1,043');
      expect(sourceBlock).toHaveTextContent('MULTILINESTRING');
    });

    it('Source block renders column count when dataset_column_info is non-empty', () => {
      const layer = makeLayer({
        id: 'cols-layer',
        dataset_column_info: [
          { name: 'a', type: 'text' },
          { name: 'b', type: 'integer' },
          { name: 'c', type: 'numeric' },
        ],
      });
      render(<StackRow {...defaultProps({ layer })} />);

      fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });

      const sourceBlock = screen.getByTestId('stack-row-kebab-source');
      // Columns line shows the count (3)
      expect(sourceBlock).toHaveTextContent('3');
    });
  });
});

// a11y(v1.6.0 audit A7, WCAG 2.1.1): the row-container keydown used to
// preventDefault Enter/Space with no target guard, cancelling native button
// activation on every descendant and swallowing spaces typed into the rename
// input. user-event 14 implements real keyboard activation (gated on
// defaultPrevented), so these prove the descendants work again.
describe('row keydown target guard (v1.6.0 audit A7)', () => {
  it('Space on the focused eye toggle activates it without toggling multi-selection', async () => {
    const user = userEvent.setup();
    const onToggleVisibility = vi.fn();
    const onCmdClick = vi.fn();
    const onSelectLayer = vi.fn();
    render(
      <StackRow {...defaultProps({ onToggleVisibility, onSelectLayer })} onCmdClick={onCmdClick} />,
    );

    const eye = screen.getByRole('button', { name: /Toggle visibility/i });
    eye.focus();
    await user.keyboard(' ');

    expect(onToggleVisibility).toHaveBeenCalledOnce();
    expect(onToggleVisibility).toHaveBeenCalledWith('layer-1');
    expect(onCmdClick).not.toHaveBeenCalled();
    expect(onSelectLayer).not.toHaveBeenCalled();
  });

  it('Enter on the focused eye toggle activates it instead of opening the layer editor', async () => {
    const user = userEvent.setup();
    const onToggleVisibility = vi.fn();
    const onSelectLayer = vi.fn();
    render(<StackRow {...defaultProps({ onToggleVisibility, onSelectLayer })} />);

    const eye = screen.getByRole('button', { name: /Toggle visibility/i });
    eye.focus();
    await user.keyboard('{Enter}');

    expect(onToggleVisibility).toHaveBeenCalledOnce();
    expect(onSelectLayer).not.toHaveBeenCalled();
  });

  it('Enter and Space on the row container itself still select / multi-toggle', () => {
    const onSelectLayer = vi.fn();
    const onCmdClick = vi.fn();
    render(<StackRow {...defaultProps({ onSelectLayer })} onCmdClick={onCmdClick} />);

    const row = document.getElementById('stack-row-layer-1')!;
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(onSelectLayer).toHaveBeenCalledWith('layer-1');
    fireEvent.keyDown(row, { key: ' ' });
    expect(onCmdClick).toHaveBeenCalledWith('layer-1');
  });

  it('Space on the drag grip arms reorder without toggling multi-selection', () => {
    const onCmdClick = vi.fn();
    render(<StackRow {...defaultProps()} onCmdClick={onCmdClick} />);

    const grip = screen.getByRole('button', { name: /Drag to reorder/i });
    fireEvent.keyDown(grip, { key: ' ' });

    expect(grip).toHaveAttribute('aria-pressed', 'true');
    expect(onCmdClick).not.toHaveBeenCalled();
  });

  it('a space can be typed into the rename input and Enter commits without re-firing the row action', async () => {
    // fix(#997): delay: null. user-event's default inserts a real-timer
    // setTimeout(0) between keystrokes, and this is the only test in the file
    // that types more than one — three keystrokes plus a clear, each yielding
    // to the macrotask queue. Under the parallel full-suite run the worker
    // competes for CPU and those yields stretch, which is what made this test
    // (and only this test) fail roughly 1 run in 6 while passing 3/3 in
    // isolation. The two siblings above keep the default: they fire a single
    // key against a focused button, have never been seen to flake, and are
    // worth keeping as controls.
    //
    // Not swapped to fireEvent, which is how the neighbouring rename tests are
    // written. This block exists to prove real keyboard activation works again
    // after the A7 fix, and that activation is gated on defaultPrevented —
    // something only user-event models. Dropping the delay removes the timing
    // dependence without giving up the dispatch semantics under test.
    const user = userEvent.setup({ delay: null });
    const onRename = vi.fn();
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'sp-layer', dataset_name: 'Old' });
    render(<StackRow {...defaultProps({ layer, onRename, onSelectLayer })} />);

    fireEvent.dblClick(screen.getByText('Old'));
    const input = screen.getByTestId('stack-row-rename-input');
    await user.clear(input);
    await user.type(input, 'a b');
    expect(input).toHaveValue('a b');

    await user.keyboard('{Enter}');

    expect(onRename).toHaveBeenCalledOnce();
    expect(onRename).toHaveBeenCalledWith('sp-layer', 'a b');
    // The Enter that commits the rename must not double-fire into the row
    // action and reopen the layer editor.
    expect(onSelectLayer).not.toHaveBeenCalled();
  });

  it('the rename input has an accessible name', () => {
    const layer = makeLayer({ id: 'aria-layer', dataset_name: 'Old' });
    render(<StackRow {...defaultProps({ layer })} />);
    fireEvent.dblClick(screen.getByText('Old'));
    expect(screen.getByRole('textbox', { name: 'Layer name' })).toBe(
      screen.getByTestId('stack-row-rename-input'),
    );
  });

  it('Enter commits the first rename attempt after a previous Escape-cancel', () => {
    // Escape unmounts the input without a blur, so escapeRef used to stay set
    // and swallow the NEXT rename's first Enter.
    const onRename = vi.fn();
    const layer = makeLayer({ id: 'esc-enter', dataset_name: 'Old' });
    render(<StackRow {...defaultProps({ layer, onRename })} />);

    fireEvent.dblClick(screen.getByText('Old'));
    fireEvent.keyDown(screen.getByTestId('stack-row-rename-input'), { key: 'Escape' });
    expect(screen.queryByTestId('stack-row-rename-input')).not.toBeInTheDocument();
    expect(onRename).not.toHaveBeenCalled();

    fireEvent.dblClick(screen.getByText('Old'));
    const input = screen.getByTestId('stack-row-rename-input');
    fireEvent.change(input, { target: { value: 'New' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).toHaveBeenCalledOnce();
    expect(onRename).toHaveBeenCalledWith('esc-enter', 'New');
  });

  it('commit and Escape-cancel hand focus back to the row', async () => {
    const layer = makeLayer({ id: 'focus-back', dataset_name: 'Old' });
    render(<StackRow {...defaultProps({ layer })} />);

    // Commit path.
    fireEvent.dblClick(screen.getByText('Old'));
    fireEvent.keyDown(screen.getByTestId('stack-row-rename-input'), { key: 'Enter' });
    await act(async () => {
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(document.activeElement?.id).toBe('stack-row-focus-back');

    // Escape-cancel path.
    fireEvent.dblClick(screen.getByText('Old'));
    fireEvent.keyDown(screen.getByTestId('stack-row-rename-input'), { key: 'Escape' });
    await act(async () => {
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(document.activeElement?.id).toBe('stack-row-focus-back');
  });
});

describe('label indicator', () => {
  it('labeled-layer-shows-indicator: shows data-testid="label-indicator" with sr-only text when label_config.column is set', () => {
    const layer = makeLayer({
      id: 'labeled-layer',
      dataset_name: 'ADK 46er peaks',
      label_config: { column: 'name' },
      style_config: null,
    });
    render(<StackRow {...defaultProps({ layer })} />);

    const indicator = screen.getByTestId('label-indicator');
    expect(indicator).toBeInTheDocument();

    // sr-only span text matches interpolated string
    const srOnly = indicator.querySelector('.sr-only');
    expect(srOnly).toBeTruthy();
    expect(srOnly?.textContent).toMatch(/Labels on: name/i);
  });

  it('unlabeled-layer-hides-indicator: shows no data-testid="label-indicator" when label_config is null', () => {
    const layer = makeLayer({
      id: 'unlabeled-layer',
      dataset_name: 'Hiking trails',
      label_config: null,
      style_config: null,
    });
    render(<StackRow {...defaultProps({ layer })} />);

    expect(screen.queryByTestId('label-indicator')).not.toBeInTheDocument();
  });

  it('heatmap-suppression: shows no indicator when label_config.column is set but render_mode is heatmap', () => {
    const layer = makeLayer({
      id: 'heatmap-layer',
      label_config: { column: 'name' },
      style_config: { render_mode: 'heatmap' } as MapLayerResponse['style_config'],
    });
    render(<StackRow {...defaultProps({ layer })} />);

    expect(screen.queryByTestId('label-indicator')).not.toBeInTheDocument();
  });

  // fix(#526 B-042): INVERTED — symbol mode renders label text consolidated in
  // the primary symbol layer, so a symbol point with label_config.column DOES
  // show text on the map and must show the badge (the old suppression was a
  // false negative built on a wrong comment).
  it('symbol mode: shows the indicator when label_config.column is set', () => {
    const layer = makeLayer({
      id: 'symbol-layer',
      label_config: { column: 'name' },
      style_config: { render_mode: 'symbol' } as MapLayerResponse['style_config'],
    });
    render(<StackRow {...defaultProps({ layer })} />);

    expect(screen.getByTestId('label-indicator')).toBeInTheDocument();
  });
});

// ux(#840): categorical layers name their styled column inline so the row
// answers "what do the colors mean" without opening the legend.
describe('categorical subtitle (ux #840)', () => {
  const categoricalConfig = {
    mode: 'categorical',
    column: 'fall',
    categories: [
      { value: 'Fell', color: '#f59e0b' },
      { value: 'Found', color: '#94a3b8' },
    ],
  } as MapLayerResponse['style_config'];

  it('shows "column · N categories" for a categorical layer', () => {
    const layer = makeLayer({ dataset_geometry_type: 'POINT', style_config: categoricalConfig });
    render(<StackRow {...defaultProps({ layer })} />);
    expect(screen.getByTestId('stack-row-categories')).toHaveTextContent('fall · 2 categories');
  });

  it('renders no subtitle for single-color, heatmap, or symbol layers', () => {
    const { unmount } = render(<StackRow {...defaultProps({ layer: makeLayer() })} />);
    expect(screen.queryByTestId('stack-row-categories')).not.toBeInTheDocument();
    unmount();

    // codex(#841): symbol mode keeps column/categories for round-tripping but
    // renders marker icons — the color-category summary would mislead.
    for (const render_mode of ['heatmap', 'symbol'] as const) {
      const layer = makeLayer({
        dataset_geometry_type: 'POINT',
        style_config: { ...categoricalConfig, render_mode } as MapLayerResponse['style_config'],
      });
      const r = render(<StackRow {...defaultProps({ layer })} />);
      expect(screen.queryByTestId('stack-row-categories')).not.toBeInTheDocument();
      r.unmount();
    }
  });
});
