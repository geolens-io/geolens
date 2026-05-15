/**
 * Phase 1044-02 — Accessibility contract tests for UnifiedStackPanel (POL-23)
 *
 * Test surface: listbox ARIA role, aria-multiselectable, aria-label, data-row-id
 * presence, Shift+Arrow keyboard extension, Escape-clear, outside-mousedown-clear,
 * and basemap boundary aria-selected non-pollution.
 *
 * These tests assert the ARIA contract that assistive technologies rely on.
 * They are intentionally distinct from the selection-model contract in
 * UnifiedStackPanel.multi-select.test.tsx — overlap in event mechanics is
 * acceptable; duplicating assertions from the AT angle (role, label, attribute) is
 * intentional (screen readers read ARIA attributes, not component state).
 *
 * Worker-safety: no file-level vi.mock('@dnd-kit/core', ...). Per the 1040-04 / 1041-04
 * PATTERNS notes, file-level dnd-kit mocks cause "Worker exited unexpectedly" regressions.
 * Real dnd-kit hooks run inside the DndContext that UnifiedStackPanel brings in.
 */

import { fireEvent, render, screen, waitFor, act, cleanup } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import type { MapLayerResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Module mocks — minimum to avoid network / icon library issues
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      // Return a known string for the listboxLabel so Test 1 can assert the name.
      if (key === 'unifiedStack.listboxLabel') return 'Map layers';
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
    isMultiSelectionActive,
    onSelectGroup,
    onToggleExpand,
    isExpanded,
  }: {
    groupId: string;
    presetName: string;
    isMultiSelectionActive?: boolean;
    onSelectGroup: (id: string) => void;
    onToggleExpand: (id: string) => void;
    isExpanded: boolean;
  }) => (
    <div
      data-testid={`basemap-group-row-${groupId}`}
      data-expanded={isExpanded ? 'true' : 'false'}
      data-multi-selection-active={isMultiSelectionActive ? 'true' : 'false'}
      role="option"
      aria-selected="false"
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
      role="option"
      aria-selected={isMultiSelected ? 'true' : 'false'}
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
  vi.clearAllMocks();
  cleanup();
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

const layerA = makeLayer({ id: 'a', dataset_name: 'Alpha', sort_order: 0 });
const layerB = makeLayer({ id: 'b', dataset_name: 'Beta', sort_order: 1 });
const layerC = makeLayer({ id: 'c', dataset_name: 'Gamma', sort_order: 2 });

function defaultProps(overrides: Partial<React.ComponentProps<typeof UnifiedStackPanel>> = {}) {
  return {
    layers: [layerA, layerB, layerC],
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
    selectedIds: new Set<string>(),
    isMultiSelectionActive: false,
    selectableRowIds: ['a', 'b', 'c'],
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
// Phase 1044-02 — Listbox ARIA contract (POL-23)
// ---------------------------------------------------------------------------

describe('Phase 1044-02 — Listbox ARIA contract (POL-23)', () => {
  it('Test 1: listbox role and label — renders element with role="listbox" and the localized label', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);

    // The i18n mock resolves "unifiedStack.listboxLabel" → "Map layers".
    // getByRole asserts both the role AND the accessible name in one call,
    // catching missing aria-label or broken i18n resolution simultaneously.
    const listbox = screen.getByRole('listbox', { name: 'Map layers' });
    expect(listbox).toBeInTheDocument();
  });

  it('Test 2: aria-multiselectable — listbox element carries aria-multiselectable="true"', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);

    const listbox = screen.getByRole('listbox', { name: 'Map layers' });
    expect(listbox).toHaveAttribute('aria-multiselectable', 'true');
  });

  it('Test 3: data-row-id presence — every rendered layer row has data-row-id matching its id', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);

    // StackRow renders SortableStackRow which sets data-row-id={layer.id} on the wrapper div.
    // All three overlay rows must be present so the Shift+Arrow handler can resolve focus.
    const rowA = document.querySelector('[data-row-id="a"]');
    const rowB = document.querySelector('[data-row-id="b"]');
    const rowC = document.querySelector('[data-row-id="c"]');

    expect(rowA).toBeInTheDocument();
    expect(rowB).toBeInTheDocument();
    expect(rowC).toBeInTheDocument();
  });

  it('Test 4: Shift+ArrowDown extension — fires onShiftClick("b") when "a" is focused and Shift+Down pressed', async () => {
    const onShiftClick = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
          selectableRowIds: ['a', 'b', 'c'],
          onShiftClick,
        })}
      />
    );

    // Focus the inner role="option" tabIndex=0 element (id="stack-row-a").
    // The keydown handler uses document.activeElement.closest('[data-row-id]') to resolve
    // the focused row — the role="option" div is a descendant of the data-row-id wrapper.
    const innerRowA = document.getElementById('stack-row-a') as HTMLElement;
    expect(innerRowA).toBeTruthy();
    act(() => { innerRowA.focus(); });

    // The keydown listener is attached to the listbox div (stackPanelRef) — fire there.
    const listbox = screen.getByRole('listbox', { name: 'Map layers' });
    fireEvent.keyDown(listbox, { key: 'ArrowDown', shiftKey: true });

    await waitFor(() => {
      expect(onShiftClick).toHaveBeenCalledWith('b');
    });
  });

  it('Test 5: Shift+ArrowUp clamp — no onShiftClick when "a" is focused (top of selectable rows)', async () => {
    const onShiftClick = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a']),
          isMultiSelectionActive: true,
          selectableRowIds: ['a', 'b', 'c'],
          onShiftClick,
        })}
      />
    );

    const innerRowA = document.getElementById('stack-row-a') as HTMLElement;
    act(() => { innerRowA.focus(); });

    const listbox = screen.getByRole('listbox', { name: 'Map layers' });
    fireEvent.keyDown(listbox, { key: 'ArrowUp', shiftKey: true });

    await act(async () => {});
    // Clamped at top — adjacent index === current index, so onShiftClick must NOT fire
    expect(onShiftClick).not.toHaveBeenCalled();
  });

  it('Test 6: Escape clears — Escape with non-empty selection fires onClearSelection', () => {
    const onClearSelection = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          selectedIds: new Set(['a', 'b']),
          onClearSelection,
        })}
      />
    );

    // Keydown listener is scoped to the listbox (stackPanelRef)
    const listbox = screen.getByRole('listbox', { name: 'Map layers' });
    fireEvent.keyDown(listbox, { key: 'Escape' });

    expect(onClearSelection).toHaveBeenCalledOnce();
  });

  it('Test 7: Outside mousedown clears — mousedown on document.body (outside panel) fires onClearSelection', async () => {
    const onClearSelection = vi.fn();
    render(
      <div>
        <UnifiedStackPanel
          {...defaultProps({
            selectedIds: new Set(['a']),
            onClearSelection,
          })}
        />
        <div data-testid="outside-element">outside the panel</div>
      </div>
    );

    // The mousedown-outside effect attaches to document and clears when mousedown
    // is on an element NOT inside stackPanelRef.
    const outside = screen.getByTestId('outside-element');
    fireEvent.mouseDown(outside);

    await waitFor(() => {
      expect(onClearSelection).toHaveBeenCalledOnce();
    });
  });

  it('Test 8: Basemap row aria-selected isolation — overlay rows can have aria-selected="true" while basemap row stays "false"', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [layerA, layerB],
          basemapGroup: defaultBasemapGroup,
          selectedIds: new Set(['a', 'b']),
          isMultiSelectionActive: true,
          selectableRowIds: ['a', 'b'],
        })}
      />
    );

    // The basemap group row mock sets aria-selected="false" unconditionally (basemap is
    // excluded from selectableRowIds and cannot be added to the multi-selection set).
    const basemapRow = screen.getByTestId('basemap-group-row-basemap-group');
    expect(basemapRow).toHaveAttribute('aria-selected', 'false');

    // Overlay rows with matching ids in selectedIds should be aria-selected="true"
    const rowA = document.getElementById('stack-row-a');
    expect(rowA).toHaveAttribute('aria-selected', 'true');
  });
});
