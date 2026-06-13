/**
 * Phase 1201-02 — Layer search/filter box tests for UnifiedStackPanel (ENH-07)
 *
 * Tests that:
 * 1. The search input appears when the stack is non-empty.
 * 2. Typing a substring narrows visible layer rows to those matching (case-insensitive).
 * 3. Non-matching rows are removed from the document.
 * 4. Clearing the query restores all rows.
 * 5. The search input is hidden when the stack is empty.
 *
 * Mock strategy: mirrors UnifiedStackPanel.multi-select.test.tsx — StackRow,
 * BasemapGroupRow, FolderGroupRow, EmptyStackState mocked to lightweight stubs
 * that expose the layer name as visible text and render id="stack-row-{id}" so
 * the standard row-presence queries work.
 */

import { fireEvent, render, screen } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import type { MapLayerResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// Module mocks
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
  eyebrowClassName: 'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1',
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
    onSelectGroup,
  }: {
    groupId: string;
    presetName: string;
    isExpanded: boolean;
    onToggleExpand: (id: string) => void;
    onSelectGroup: (id: string) => void;
  }) => (
    <div
      data-testid={`basemap-group-row-${groupId}`}
      id={`stack-row-${groupId}`}
    >
      <span>Basemap · {presetName}</span>
      <button onClick={() => onSelectGroup(groupId)}>select</button>
    </div>
  ),
}));

vi.mock('../FolderGroupRow', () => ({
  FolderGroupRow: ({
    groupId,
    groupName,
    onSelectGroup,
  }: {
    groupId: string;
    groupName: string;
    isExpanded: boolean;
    onToggleExpand: (id: string) => void;
    onSelectGroup: (id: string) => void;
  }) => (
    <div
      data-testid={`folder-group-row-${groupId}`}
      id={`stack-row-${groupId}`}
      data-row-id={groupId}
    >
      <span>{groupName}</span>
      <button onClick={() => onSelectGroup(groupId)}>select</button>
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// ResizeObserver stub required by dnd-kit in JSDOM
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
  overrides: Omit<Partial<MapLayerResponse>, 'layer_type'> & {
    layer_type?: string;
    parent_group_id?: string | null;
  } = {},
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

function defaultProps(
  overrides: Partial<React.ComponentProps<typeof UnifiedStackPanel>> = {},
) {
  return {
    layers: [],
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
    selectableRowIds: [],
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
// ENH-07: search/filter box tests
// ---------------------------------------------------------------------------

describe('UnifiedStackPanel — ENH-07: layer search/filter', () => {
  const layerAlpha = makeLayer({ id: 'a', dataset_name: 'Alpha Layer', sort_order: 0 });
  const layerBeta  = makeLayer({ id: 'b', dataset_name: 'Beta Layer',  sort_order: 1 });
  const layerGamma = makeLayer({ id: 'c', dataset_name: 'Gamma Layer', sort_order: 2 });
  const threeLayerProps = defaultProps({ layers: [layerAlpha, layerBeta, layerGamma] });

  it('renders the search input when the stack is non-empty', () => {
    render(<UnifiedStackPanel {...threeLayerProps} />);
    const input = screen.getByRole('searchbox');
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute('placeholder', 'Filter layers…');
  });

  it('does not render the search input when the stack is empty', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers: [] })} />);
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });

  it('search narrows visible rows to those matching the query (case-insensitive substring)', () => {
    render(<UnifiedStackPanel {...threeLayerProps} />);

    // All three rows are initially visible
    expect(document.getElementById('stack-row-a')).toBeInTheDocument();
    expect(document.getElementById('stack-row-b')).toBeInTheDocument();
    expect(document.getElementById('stack-row-c')).toBeInTheDocument();

    // Type "alpha" (lowercase) — should match only "Alpha Layer"
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'alpha' } });

    expect(document.getElementById('stack-row-a')).toBeInTheDocument();
    expect(document.getElementById('stack-row-b')).not.toBeInTheDocument();
    expect(document.getElementById('stack-row-c')).not.toBeInTheDocument();
  });

  it('clearing the query restores all rows', () => {
    render(<UnifiedStackPanel {...threeLayerProps} />);

    const input = screen.getByRole('searchbox');

    // Filter to a single row
    fireEvent.change(input, { target: { value: 'beta' } });
    expect(document.getElementById('stack-row-a')).not.toBeInTheDocument();
    expect(document.getElementById('stack-row-b')).toBeInTheDocument();
    expect(document.getElementById('stack-row-c')).not.toBeInTheDocument();

    // Clear the query — all rows return
    fireEvent.change(input, { target: { value: '' } });
    expect(document.getElementById('stack-row-a')).toBeInTheDocument();
    expect(document.getElementById('stack-row-b')).toBeInTheDocument();
    expect(document.getElementById('stack-row-c')).toBeInTheDocument();
  });

  it('search is case-insensitive and matches a mid-string substring', () => {
    render(<UnifiedStackPanel {...threeLayerProps} />);

    // "LAYER" should match ALL three (each ends in " Layer")
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'LAYER' } });

    expect(document.getElementById('stack-row-a')).toBeInTheDocument();
    expect(document.getElementById('stack-row-b')).toBeInTheDocument();
    expect(document.getElementById('stack-row-c')).toBeInTheDocument();
  });

  it('a query matching no layer hides all data rows', () => {
    render(<UnifiedStackPanel {...threeLayerProps} />);

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzznomatch' } });

    expect(document.getElementById('stack-row-a')).not.toBeInTheDocument();
    expect(document.getElementById('stack-row-b')).not.toBeInTheDocument();
    expect(document.getElementById('stack-row-c')).not.toBeInTheDocument();
  });

  it('uses display_name when set, falling back to dataset_name', () => {
    // display_name overrides dataset_name for match purposes
    const layerWithDisplay = makeLayer({
      id: 'x',
      dataset_name: 'Raw Dataset',
      display_name: 'Pretty Name',
      sort_order: 0,
    });
    render(<UnifiedStackPanel {...defaultProps({ layers: [layerWithDisplay] })} />);

    // "Pretty" matches display_name
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Pretty' } });
    expect(document.getElementById('stack-row-x')).toBeInTheDocument();

    // "Raw" does NOT match because display_name takes precedence
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Raw' } });
    expect(document.getElementById('stack-row-x')).not.toBeInTheDocument();
  });

  it('does not hide the basemap dock row when a search query is active', () => {
    const basemapGroup = {
      id: 'basemap-group',
      presetName: 'Positron',
      providerLabel: 'OpenFreeMap',
      visible: true,
      opacity: 1,
      sublayers: [],
    };
    render(
      <UnifiedStackPanel
        {...threeLayerProps}
        basemapGroup={basemapGroup}
        isBasemapExpanded={false}
      />,
    );

    // Filter to nothing matching
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzz' } });

    // Basemap row must remain (it is never filtered)
    expect(screen.getByTestId('basemap-group-row-basemap-group')).toBeInTheDocument();
  });
});
