import { fireEvent, render, screen } from '@/test/test-utils';
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
    onOpacityChange: vi.fn(),
    onRemove: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    ...overrides,
  };
}

describe('StackRow', () => {
  it('renders the six interactive cells in DOM order: grip → eye → name → opacity slider → kebab (caret hidden)', () => {
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

    // Opacity slider
    const slider = screen.getByRole('slider', { name: /Opacity for/i });
    expect(slider).toBeInTheDocument();

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

  it('clicking the kebab trigger does NOT call onSelectLayer; opening menu shows four locked items in order', () => {
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'kebab-layer', dataset_name: 'My Layer' });
    render(<StackRow {...defaultProps({ layer, onSelectLayer })} />);

    const kebabTrigger = screen.getByRole('button', { name: /Layer options for/i });
    // Use pointerDown to open Radix dropdown (matches existing test patterns)
    fireEvent.pointerDown(kebabTrigger, { button: 0, ctrlKey: false });

    expect(onSelectLayer).not.toHaveBeenCalled();

    // Check four locked items in order
    const menuItems = screen.getAllByRole('menuitem');
    const menuTexts = menuItems.map((item) => item.textContent?.trim());
    expect(menuTexts).toContain('Rename layer');
    expect(menuTexts).toContain('Duplicate');
    expect(menuTexts).toContain('Delete layer');
    expect(menuTexts).toContain('Add to group…');

    // Verify order
    const renameIdx = menuTexts.indexOf('Rename layer');
    const dupIdx = menuTexts.indexOf('Duplicate');
    const deleteIdx = menuTexts.indexOf('Delete layer');
    const groupIdx = menuTexts.indexOf('Add to group…');
    expect(renameIdx).toBeLessThan(dupIdx);
    expect(dupIdx).toBeLessThan(deleteIdx);
    expect(deleteIdx).toBeLessThan(groupIdx);
  });

  it('clicking "Delete layer" in the kebab calls onRemove(layer.id)', () => {
    const onRemove = vi.fn();
    const layer = makeLayer({ id: 'delete-layer' });
    render(<StackRow {...defaultProps({ layer, onRemove })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete layer/i }));

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

  it('"Add to group…" item is disabled', () => {
    const layer = makeLayer({ id: 'group-layer' });
    render(<StackRow {...defaultProps({ layer })} />);

    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0, ctrlKey: false });
    const groupItem = screen.getByRole('menuitem', { name: /Add to group/i });
    expect(groupItem).toHaveAttribute('aria-disabled', 'true');
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

  it('opacity slider aria-label reads "Opacity for {layer name}"', () => {
    const layer = makeLayer({ dataset_name: 'My Dataset' });
    render(<StackRow {...defaultProps({ layer })} />);

    const slider = screen.getByRole('slider', { name: /Opacity for My Dataset/i });
    expect(slider).toBeInTheDocument();
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
      style_config: { render_mode: 'hillshade' },
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
      style_config: { render_mode: 'terrain' } as Parameters<typeof makeLayer>[0]['style_config'],
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
      style_config: { render_mode: 'hillshade' },
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
        style_config: style_config as Parameters<typeof makeLayer>[0]['style_config'],
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
