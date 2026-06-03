/**
 * Phase 1041 — Multi-selection tests for UnifiedStackPanel (POL-06, POL-07, POL-10, POL-11)
 *
 * Test surface: selection model, visual state, clearing rules, basemap boundary, Shift+Arrow.
 *
 * Worker-safety: no file-level vi.mock('@dnd-kit/core', ...). Per POL-20, that pattern causes
 * worker exits. All dnd-kit hooks run from their real implementations wrapped in a DndContext
 * via the test-utils wrapper (which is already DndContext-free — UnifiedStackPanel renders its
 * own internal DndContext). We stub only the specific modules that would reach the network.
 *
 * Test boundary: render UnifiedStackPanel directly with controlled props (callbacks as vi.fn()).
 * This mirrors the existing UnifiedStackPanel.test.tsx pattern.
 */

import { fireEvent, render, screen, waitFor, act } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import type { MapLayerResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Module mocks — kept to the minimum needed to avoid network / icon library issues
// ---------------------------------------------------------------------------

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

vi.mock('../EmptyStackState', () => ({
  EmptyStackState: ({ onOpenAddData }: { onOpenAddData: (query?: string) => void }) => (
    <div data-testid="empty-stack-state">
      <button onClick={() => onOpenAddData()}>Browse</button>
    </div>
  ),
}));

vi.mock('../BasemapGroupRow', () => ({
  BasemapGroupRow: ({
    groupId,
    presetName,
    isExpanded,
    onToggleExpand,
    onSelectGroup,
    isMultiSelectionActive,
  }: {
    groupId: string;
    presetName: string;
    isExpanded: boolean;
    onToggleExpand: (id: string) => void;
    onSelectGroup: (id: string) => void;
    isMultiSelectionActive?: boolean;
  }) => (
    <div
      data-testid={`basemap-group-row-${groupId}`}
      data-expanded={isExpanded ? 'true' : 'false'}
      data-multi-selection-active={isMultiSelectionActive ? 'true' : 'false'}
      id={`stack-row-${groupId}`}
      className={isMultiSelectionActive ? 'cursor-not-allowed' : ''}
    >
      <span>Basemap · {presetName}</span>
      <button
        data-testid={`basemap-group-expand-${groupId}`}
        onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
      >toggle</button>
      <button
        data-testid={`basemap-group-select-${groupId}`}
        onClick={() => onSelectGroup(groupId)}
      >select</button>
    </div>
  ),
}));

vi.mock('../FolderGroupRow', () => ({
  FolderGroupRow: ({
    groupId,
    groupName,
    isExpanded,
    onToggleExpand,
    onSelectGroup,
    isMultiSelected,
    isMultiSelectionActive,
    onCmdClick,
    onShiftClick,
    onCheckboxClick,
  }: {
    groupId: string;
    groupName: string;
    isExpanded: boolean;
    onToggleExpand: (id: string) => void;
    onSelectGroup: (id: string) => void;
    isMultiSelected?: boolean;
    isMultiSelectionActive?: boolean;
    onCmdClick?: (id: string) => void;
    onShiftClick?: (id: string) => void;
    onCheckboxClick?: (id: string) => void;
  }) => (
    <div
      data-testid={`folder-group-row-${groupId}`}
      data-expanded={isExpanded ? 'true' : 'false'}
      data-multi-selected={isMultiSelected ? 'true' : 'false'}
      data-selected={isMultiSelected ? 'true' : undefined}
      aria-current={isMultiSelected ? 'true' : undefined}
      id={`stack-row-${groupId}`}
      data-row-id={groupId}
    >
      <span>{groupName}</span>
      <button
        data-testid={`folder-group-expand-${groupId}`}
        onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
      >toggle</button>
      <button
        data-testid={`folder-group-select-${groupId}`}
        onClick={() => onSelectGroup(groupId)}
      >select</button>
      {isMultiSelectionActive && (
        <input
          type="checkbox"
          checked={isMultiSelected}
          onChange={() => onCheckboxClick?.(groupId)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select ${groupName}`}
        />
      )}
      <button
        data-testid={`folder-group-cmd-${groupId}`}
        onClick={() => onCmdClick?.(groupId)}
      >cmd</button>
      <button
        data-testid={`folder-group-shift-${groupId}`}
        onClick={() => onShiftClick?.(groupId)}
      >shift</button>
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// ResizeObserver stub for dnd-kit in JSDOM
// ---------------------------------------------------------------------------
beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeLayer(
  overrides: Omit<Partial<MapLayerResponse>, 'layer_type'> & { layer_type?: string; parent_group_id?: string | null } = {},
): MapLayerResponse {
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
    layer_type: (overrides.layer_type ?? null) as MapLayerResponse['layer_type'],
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  } as MapLayerResponse;
}

const defaultBasemapGroup = {
  id: 'basemap-group',
  presetName: 'Positron',
  providerLabel: 'OpenFreeMap',
  visible: true,
  opacity: 1,
  sublayers: [
    { id: 'basemap:roads', name: 'Roads', visible: true, opacity: 1, kind: 'vector' as const },
  ],
};

// Build a standard set of layers for selection tests:
// bm(basemap), a, b, c (loose vector), r1 (raster), g1 (folder group)
const layerA = makeLayer({ id: 'a', dataset_name: 'Alpha', sort_order: 0, dataset_record_type: 'vector_dataset' });
const layerB = makeLayer({ id: 'b', dataset_name: 'Beta', sort_order: 1, dataset_record_type: 'vector_dataset' });
const layerC = makeLayer({ id: 'c', dataset_name: 'Gamma', sort_order: 2, dataset_record_type: 'vector_dataset' });
const layerR1 = makeLayer({ id: 'r1', dataset_name: 'Satellite', sort_order: 3, dataset_record_type: 'raster_dataset', layer_type: 'raster_geolens' });
const layerG1 = makeLayer({ id: 'g1', dataset_name: 'My Group', sort_order: 4, layer_type: 'group:folder' });

const mockLayers = [layerA, layerB, layerC, layerR1, layerG1];

function defaultProps(overrides: Partial<React.ComponentProps<typeof UnifiedStackPanel>> = {}) {
  return {
    layers: mockLayers,
    selectedLayerId: null,
    onSelectLayer: vi.fn(),
    onToggleVisibility: vi.fn(),
    onReorder: vi.fn(),
    onOpacityChange: vi.fn(),
    onRemove: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    onAddDataClick: vi.fn(),
    onSettingsClick: vi.fn(),
    groupMeta: {},
    onToggleGroupExpand: vi.fn(),
    basemapGroup: null,
    isBasemapExpanded: false,
    onToggleSublayerVisibility: vi.fn(),
    onSublayerOpacityChange: vi.fn(),
    onSwapBasemap: vi.fn(),
    onResetBasemapAppearance: vi.fn(),
    onRenameGroup: vi.fn(),
    onAddLayerToGroup: vi.fn(),
    onUngroup: vi.fn(),
    onDeleteGroup: vi.fn(),
    onAddLayerToExistingGroup: vi.fn(),
    onCreateGroupWithLayer: vi.fn(),
    onMoveLayerOutOfGroup: vi.fn(),
    existingFolderGroups: [],
    // Phase 1041 multi-selection props
    selectedIds: new Set<string>(),
    isMultiSelectionActive: false,
    selectableRowIds: ['a', 'b', 'c', 'r1', 'g1'],
    onCmdClick: vi.fn(),
    onShiftClick: vi.fn(),
    onCheckboxClick: vi.fn(),
    onClearSelection: vi.fn(),
    onBulkVisibility: vi.fn(),
    onBulkOpacity: vi.fn(),
    onBulkGroup: vi.fn(),
    onBulkUngroup: vi.fn(),
    onBulkDelete: vi.fn(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Phase 1041 — selection model (POL-06)
// ---------------------------------------------------------------------------

describe('Phase 1041 — selection model (POL-06)', () => {
  it('Test 1: Cmd-click on a row calls onCmdClick(id) and NOT onSelectLayer', () => {
    const onCmdClick = vi.fn();
    const onSelectLayer = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onCmdClick, onSelectLayer })} />);

    const rowA = document.getElementById('stack-row-a');
    expect(rowA).toBeInTheDocument();
    fireEvent.click(rowA!, { metaKey: true });

    expect(onCmdClick).toHaveBeenCalledWith('a');
    expect(onSelectLayer).not.toHaveBeenCalled();
  });

  it('Test 2: Shift-click on a row calls onShiftClick(id)', () => {
    const onShiftClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onShiftClick })} />);

    const rowC = document.getElementById('stack-row-c');
    expect(rowC).toBeInTheDocument();
    fireEvent.click(rowC!, { shiftKey: true });

    expect(onShiftClick).toHaveBeenCalledWith('c');
  });

  it('Test 3: Plain click on a row calls onSelectLayer(id) and NOT onCmdClick', () => {
    const onSelectLayer = vi.fn();
    const onCmdClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onSelectLayer, onCmdClick })} />);

    const rowB = document.getElementById('stack-row-b');
    expect(rowB).toBeInTheDocument();
    fireEvent.click(rowB!);

    expect(onSelectLayer).toHaveBeenCalledWith('b');
    expect(onCmdClick).not.toHaveBeenCalled();
  });

  it('Test 4: Space key on a focused row calls onCmdClick(id)', () => {
    const onCmdClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onCmdClick })} />);

    const rowA = document.getElementById('stack-row-a');
    expect(rowA).toBeInTheDocument();
    rowA!.focus();
    fireEvent.keyDown(rowA!, { key: ' ' });

    expect(onCmdClick).toHaveBeenCalledWith('a');
  });
});

// ---------------------------------------------------------------------------
// Phase 1041 — visual state (POL-07)
// ---------------------------------------------------------------------------

describe('Phase 1041 — visual state (POL-07)', () => {
  it('Test 5: isMultiSelectionActive=true renders a Checkbox for multi-selected row', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
        })}
      />
    );

    // StackRow renders a Checkbox (Radix Checkbox renders role=checkbox) when isMultiSelectionActive=true
    const checkboxes = screen.getAllByRole('checkbox');
    // At least one checkbox should be checked (for row 'a')
    const checkedCheckbox = checkboxes.find((cb) => cb.getAttribute('aria-checked') === 'true' || (cb as HTMLInputElement).checked);
    expect(checkedCheckbox).toBeDefined();
  });

  it('Test 6: isMultiSelectionActive=false shows no Checkboxes', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a']),
          isMultiSelectionActive: false,
        })}
      />
    );

    // No Checkboxes rendered when multi-selection is inactive
    const checkboxes = screen.queryAllByRole('checkbox');
    expect(checkboxes).toHaveLength(0);
  });

  it('Test 7: aria-current on row reflects isMultiSelected=true even when selected=false', () => {
    // Phase 1052: replaced aria-selected with aria-current after dropping
    // role="option" from rows (axe nested-interactive). The mock used in
    // this test mirrors the production wiring: aria-current="true" when
    // isMultiSelected, undefined otherwise.
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedLayerId: null, // no single-selection
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
        })}
      />
    );

    const rowA = document.getElementById('stack-row-a');
    expect(rowA).toHaveAttribute('aria-current', 'true');
    expect(rowA).toHaveAttribute('data-selected', 'true');
  });

  it('Test 8: The stack panel exposes aria-label="Map layers" (Phase 1052: no role=listbox)', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);

    const panel = document.querySelector('[aria-label="Map layers"]') as HTMLElement;
    expect(panel).toBeInTheDocument();
    expect(panel).not.toHaveAttribute('role');
    expect(panel).not.toHaveAttribute('aria-multiselectable');
  });
});

// ---------------------------------------------------------------------------
// Phase 1041 — clearing rules (POL-10)
// ---------------------------------------------------------------------------

describe('Phase 1041 — clearing rules (POL-10)', () => {
  it('Test 9: Escape key fires onClearSelection when selection is non-empty', () => {
    const onClearSelection = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a']),
          onClearSelection,
        })}
      />
    );

    // Phase 1042 carry-over: keydown listener is scoped to stackPanelRef (listbox), not document.
    const listbox = document.querySelector('[aria-label="Map layers"]') as HTMLElement;
    fireEvent.keyDown(listbox, { key: 'Escape' });
    expect(onClearSelection).toHaveBeenCalledOnce();
  });

  it('Test 10: mousedown outside the stack panel fires onClearSelection', async () => {
    const onClearSelection = vi.fn();
    const { container } = render(
      <div>
        <UnifiedStackPanel
          {...defaultProps({
            selectedIds: new Set(['a']),
            onClearSelection,
          })}
        />
        <div data-testid="outside">outside</div>
      </div>
    );

    const outside = container.querySelector('[data-testid="outside"]')!;
    fireEvent.mouseDown(outside);

    await waitFor(() => {
      expect(onClearSelection).toHaveBeenCalledOnce();
    });
  });

  it('Test 11: mousedown inside the stack panel does NOT fire onClearSelection', async () => {
    const onClearSelection = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a']),
          onClearSelection,
        })}
      />
    );

    const listbox = document.querySelector('[aria-label="Map layers"]') as HTMLElement;
    fireEvent.mouseDown(listbox);

    // Allow microtask flush
    await act(async () => {});
    expect(onClearSelection).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Phase 1041 — basemap boundary (POL-11)
// ---------------------------------------------------------------------------

describe('Phase 1041 — basemap boundary (POL-11)', () => {
  it('Test 12: BasemapGroupRowWrapper passes isMultiSelectionActive to BasemapGroupRow', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          layers: [layerA],
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
        })}
      />
    );

    const basemapRow = screen.getByTestId('basemap-group-row-basemap-group');
    expect(basemapRow).toBeInTheDocument();
    // The mock passes isMultiSelectionActive as data attribute and cursor-not-allowed class
    expect(basemapRow).toHaveAttribute('data-multi-selection-active', 'true');
    expect(basemapRow.className).toContain('cursor-not-allowed');
  });

  it('Test 13: Cmd-click on basemap group row invokes onSelectGroup, NOT onCmdClick', () => {
    const onCmdClick = vi.fn();
    const onSelectLayer = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          layers: [layerA],
          onCmdClick,
          onSelectLayer,
        })}
      />
    );

    // The basemap row is rendered by BasemapGroupRowWrapper which uses BasemapGroupRow;
    // our mock's main div does not wire onCmdClick — it uses onSelectGroup. A metaKey
    // click on the row div itself should NOT reach our onCmdClick callback because
    // BasemapGroupRow does not expose onCmdClick.
    const basemapRowDiv = screen.getByTestId('basemap-group-row-basemap-group');
    fireEvent.click(basemapRowDiv, { metaKey: true });

    // onCmdClick should not be called — basemap row doesn't expose it
    expect(onCmdClick).not.toHaveBeenCalled();
  });

  it('Test 14: When isMultiSelectionActive=true, basemap group row shows cursor-not-allowed', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          layers: [layerA],
          isMultiSelectionActive: true,
        })}
      />
    );

    const basemapRow = screen.getByTestId('basemap-group-row-basemap-group');
    expect(basemapRow.className).toContain('cursor-not-allowed');
  });
});

// ---------------------------------------------------------------------------
// Phase 1041 — Shift+Arrow keyboard extension (POL-06)
// ---------------------------------------------------------------------------

describe('Phase 1041 — Shift+Arrow keyboard extension (POL-06)', () => {
  it('Test 16: Shift+ArrowDown calls onShiftClick with the next selectable row id', async () => {
    const onShiftClick = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [layerA, layerB, layerC],
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
          selectableRowIds: ['a', 'b', 'c'],
          onShiftClick,
        })}
      />
    );

    // Focus row 'a'
    const rowA = document.getElementById('stack-row-a')!;
    act(() => { rowA.focus(); });

    // Phase 1042 carry-over: keydown listener is scoped to listbox (stackPanelRef), not document.
    const listbox = document.querySelector('[aria-label="Map layers"]') as HTMLElement;
    fireEvent.keyDown(listbox, { key: 'ArrowDown', shiftKey: true });

    await waitFor(() => {
      expect(onShiftClick).toHaveBeenCalledWith('b');
    });
  });

  it('Test 17: Shift+ArrowUp at top of selectable rows is a no-op (no onShiftClick call)', async () => {
    const onShiftClick = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [layerA, layerB, layerC],
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
          selectableRowIds: ['a', 'b', 'c'],
          onShiftClick,
        })}
      />
    );

    // Focus row 'a' — the topmost selectable row
    const rowA = document.getElementById('stack-row-a')!;
    act(() => { rowA.focus(); });

    // Phase 1042 carry-over: keydown listener is scoped to listbox (stackPanelRef).
    const listbox = document.querySelector('[aria-label="Map layers"]') as HTMLElement;
    fireEvent.keyDown(listbox, { key: 'ArrowUp', shiftKey: true });

    // Wait a tick for any async effects
    await act(async () => {});
    expect(onShiftClick).not.toHaveBeenCalled();
  });

  it('Test 18: Plain ArrowDown (no Shift) does NOT call onShiftClick', async () => {
    const onShiftClick = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [layerA, layerB, layerC],
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
          selectableRowIds: ['a', 'b', 'c'],
          onShiftClick,
        })}
      />
    );

    const rowA = document.getElementById('stack-row-a')!;
    act(() => { rowA.focus(); });

    // Plain arrow — no Shift. Phase 1042 carry-over: scoped to listbox.
    const listbox = document.querySelector('[aria-label="Map layers"]') as HTMLElement;
    fireEvent.keyDown(listbox, { key: 'ArrowDown', shiftKey: false });

    await act(async () => {});
    expect(onShiftClick).not.toHaveBeenCalled();
  });
});
