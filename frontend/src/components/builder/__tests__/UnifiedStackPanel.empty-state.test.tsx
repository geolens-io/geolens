import { fireEvent, render, screen } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
        return options.defaultValue as string;
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

// Stub EmptyStackState with a predictable UI surface for wiring tests
vi.mock('../EmptyStackState', () => ({
  eyebrowClassName: 'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1',
  EmptyStackState: ({ onOpenAddData, onAddDataset }: {
    onOpenAddData: (query?: string) => void;
    onAddDataset: (id: string) => void;
  }) => (
    <div data-testid="empty-stack-state">
      <p>Add your first layer</p>
      <button
        data-testid="empty-search-submit"
        onClick={() => onOpenAddData('parks near me')}
      >
        Search submit
      </button>
      <button
        data-testid="empty-add-dataset"
        onClick={() => onAddDataset('suggest-dataset-id')}
      >
        Add suggest card
      </button>
      <button
        data-testid="empty-browse-all"
        onClick={() => onOpenAddData()}
      >
        Browse all datasets
      </button>
    </div>
  ),
}));

vi.mock('../BasemapGroupRow', () => ({
  BasemapGroupRow: ({ groupId, presetName }: {
    groupId: string;
    presetName: string;
  }) => (
    <div
      data-testid={`basemap-group-row-${groupId}`}
      role="option"
      aria-selected="false"
      id={`stack-row-${groupId}`}
    >
      <span>Basemap · {presetName}</span>
    </div>
  ),
}));

vi.mock('../FolderGroupRow', () => ({
  FolderGroupRow: ({ groupId, groupName }: {
    groupId: string;
    groupName: string;
  }) => (
    <div
      data-testid={`folder-group-row-${groupId}`}
      role="option"
      aria-selected="false"
      id={`stack-row-${groupId}`}
    >
      <span>{groupName}</span>
    </div>
  ),
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

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

function defaultProps(overrides: Partial<React.ComponentProps<typeof UnifiedStackPanel>> = {}) {
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
    onAddDataset: vi.fn(),
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
    // Phase 1051 WR-02: bulk handlers are required props on UnifiedStackPanel.
    onBulkVisibility: vi.fn(),
    onBulkOpacity: vi.fn(),
    onBulkGroup: vi.fn(),
    onBulkUngroup: vi.fn(),
    onBulkDelete: vi.fn(),
    ...overrides,
  };
}

describe('UnifiedStackPanel — empty-state wiring', () => {
  it('EmptyStackState search submit calls onAddDataClick with the search query', () => {
    const onAddDataClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onAddDataClick, layers: [] })} />);

    expect(screen.getByTestId('empty-stack-state')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('empty-search-submit'));

    expect(onAddDataClick).toHaveBeenCalledWith('parks near me');
  });

  it('EmptyStackState suggest-card add button calls onAddDataset with dataset id', () => {
    const onAddDataset = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onAddDataset, layers: [] })} />);

    fireEvent.click(screen.getByTestId('empty-add-dataset'));
    expect(onAddDataset).toHaveBeenCalledWith('suggest-dataset-id');
  });

  it('basemap dock is visible in empty state when basemapGroup is provided', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [],
          basemapGroup: defaultBasemapGroup,
        })}
      />
    );

    expect(screen.getByTestId('empty-stack-state')).toBeInTheDocument();
    expect(screen.getByTestId('basemap-dock')).toBeInTheDocument();
    expect(screen.getByTestId('basemap-group-row-basemap-group')).toBeInTheDocument();
  });

  it('basemap dock shows "BASEMAP" eyebrow label in empty state', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [],
          basemapGroup: defaultBasemapGroup,
        })}
      />
    );

    expect(screen.getByText('BASEMAP')).toBeInTheDocument();
  });

  it('Browse all button calls onAddDataClick with no arguments', () => {
    const onAddDataClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onAddDataClick, layers: [] })} />);

    fireEvent.click(screen.getByTestId('empty-browse-all'));

    expect(onAddDataClick).toHaveBeenCalledWith(undefined);
  });

  it('EmptyStackState does NOT render when layers are present', () => {
    const layers = [makeLayer({ id: 'l1' })];
    render(<UnifiedStackPanel {...defaultProps({ layers })} />);

    expect(screen.queryByTestId('empty-stack-state')).not.toBeInTheDocument();
  });
});
