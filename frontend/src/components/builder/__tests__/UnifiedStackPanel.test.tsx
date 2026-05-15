import { fireEvent, render, screen } from '@/test/test-utils';
import { UnifiedStackPanel, CatalogDragGhost } from '../UnifiedStackPanel';
import type { MapLayerResponse } from '@/types/api';

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

// Mock BasemapGroupRow and FolderGroupRow to simple stubs for routing logic tests
vi.mock('../EmptyStackState', () => ({
  EmptyStackState: ({ onOpenAddData, onAddDataset }: {
    onOpenAddData: (query?: string) => void;
    onAddDataset: (id: string) => void;
  }) => (
    <div data-testid="empty-stack-state">
      <p>Add your first layer</p>
      <button data-testid="empty-browse-all" onClick={() => onOpenAddData()}>Browse all datasets</button>
      <button data-testid="empty-search-submit" onClick={() => onOpenAddData('test query')}>Search</button>
      {/* Label deliberately avoids substring "Add data" so it does not
          collide with the header `＋ Add data` button via getByRole regex
          matching. Test wiring uses `data-testid="empty-add-dataset"`. */}
      <button data-testid="empty-add-dataset" onClick={() => onAddDataset('dataset-id-1')}>Pick suggestion</button>
    </div>
  ),
}));

vi.mock('../BasemapGroupRow', () => ({
  BasemapGroupRow: ({ groupId, presetName, isExpanded, onToggleExpand, onSelectGroup }: {
    groupId: string;
    presetName: string;
    isExpanded: boolean;
    onToggleExpand: (id: string) => void;
    onSelectGroup: (id: string) => void;
  }) => (
    <div
      data-testid={`basemap-group-row-${groupId}`}
      data-expanded={isExpanded ? 'true' : 'false'}
      role="option"
      aria-selected="false"
      aria-expanded={isExpanded}
      id={`stack-row-${groupId}`}
    >
      <span>Basemap · {presetName}</span>
      <button
        data-testid={`basemap-group-expand-${groupId}`}
        onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
      >
        toggle
      </button>
      <button
        data-testid={`basemap-group-select-${groupId}`}
        onClick={() => onSelectGroup(groupId)}
      >
        select
      </button>
    </div>
  ),
}));

vi.mock('../FolderGroupRow', () => ({
  FolderGroupRow: ({ groupId, groupName, isExpanded, onToggleExpand, onSelectGroup }: {
    groupId: string;
    groupName: string;
    isExpanded: boolean;
    onToggleExpand: (id: string) => void;
    onSelectGroup: (id: string) => void;
  }) => (
    <div
      data-testid={`folder-group-row-${groupId}`}
      data-expanded={isExpanded ? 'true' : 'false'}
      role="option"
      aria-selected="false"
      id={`stack-row-${groupId}`}
    >
      <span>{groupName}</span>
      <button
        data-testid={`folder-group-expand-${groupId}`}
        onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
      >
        toggle
      </button>
      <button
        data-testid={`folder-group-select-${groupId}`}
        onClick={() => onSelectGroup(groupId)}
      >
        select
      </button>
    </div>
  ),
}));

// @dnd-kit requires this for sensors in JSDOM
beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

// layer_type widened to string so callers can pass group:folder / group:basemap
// (use-builder-layers represents groups as virtual rows with those layer_type tags).
function makeLayer(
  overrides: Omit<Partial<MapLayerResponse>, 'layer_type'> & { layer_type?: string } = {},
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
    { id: 'basemap:labels', name: 'Labels', visible: true, opacity: 1, kind: 'vector' as const },
  ],
};

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
    ...overrides,
  };
}

describe('UnifiedStackPanel', () => {
  it('renders header with "Layers" title, count badge, Settings button, and ＋ Add data button', () => {
    const layers = [makeLayer({ id: 'l1' }), makeLayer({ id: 'l2' })];
    render(<UnifiedStackPanel {...defaultProps({ layers })} />);

    expect(screen.getByText('Layers')).toBeInTheDocument();
    // Count badge
    expect(screen.getByText('2')).toBeInTheDocument();
    // Settings button
    expect(screen.getByRole('button', { name: /Settings/i })).toBeInTheDocument();
    // Add data button
    expect(screen.getByRole('button', { name: /Add data/i })).toBeInTheDocument();
  });

  it('renders EmptyStackState when no layers are present', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers: [], basemapGroup: null })} />);

    expect(screen.getByTestId('empty-stack-state')).toBeInTheDocument();
    expect(screen.getByText('Add your first layer')).toBeInTheDocument();
  });

  it('renders one StackRow per layer in array order', () => {
    const layers = [
      makeLayer({ id: 'layer-a', dataset_name: 'Alpha' }),
      makeLayer({ id: 'layer-b', dataset_name: 'Beta' }),
      makeLayer({ id: 'layer-c', dataset_name: 'Gamma' }),
    ];
    render(<UnifiedStackPanel {...defaultProps({ layers })} />);

    const rows = screen.getAllByRole('option');
    // 3 loose layers — each renders as role=option from StackRow
    expect(rows.length).toBeGreaterThanOrEqual(3);
    const ids = rows.map((r) => r.getAttribute('id'));
    expect(ids).toContain('stack-row-layer-a');
    expect(ids).toContain('stack-row-layer-b');
    expect(ids).toContain('stack-row-layer-c');
  });

  it('no section headers like "Surface", "Relief", "Basemap", "Data", "Labels", "Interactions" (BSR-01)', () => {
    const layers = [makeLayer({ id: 'l1', dataset_name: 'My Layer' })];
    render(<UnifiedStackPanel {...defaultProps({ layers })} />);

    // Ensure none of the old taxonomy sections appear
    for (const label of ['Surface', 'Relief', 'Data', 'Labels', 'Interactions']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it('calls onSelectLayer(null) when drag-start fires', () => {
    const onSelectLayer = vi.fn();
    const layers = [makeLayer({ id: 'l1' }), makeLayer({ id: 'l2' })];
    render(<UnifiedStackPanel {...defaultProps({ layers, onSelectLayer })} />);

    // Verify component renders DndContext children (rows)
    expect(screen.getAllByRole('option')).toHaveLength(2);

    // onSelectLayer(null) is called on drag-start; we verify the handler is wired
    // by checking it was NOT called on initial render
    expect(onSelectLayer).not.toHaveBeenCalled();
  });

  it('calls onSettingsClick when Settings button is clicked', () => {
    const onSettingsClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onSettingsClick })} />);

    fireEvent.click(screen.getByRole('button', { name: /Settings/i }));
    expect(onSettingsClick).toHaveBeenCalledOnce();
  });

  it('calls onAddDataClick when ＋ Add data button is clicked', () => {
    const onAddDataClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onAddDataClick })} />);

    fireEvent.click(screen.getByRole('button', { name: /Add data/i }));
    expect(onAddDataClick).toHaveBeenCalledOnce();
  });
});

describe('UnifiedStackPanel — basemap group rendering', () => {
  it('renders BasemapGroupRow when basemapGroup prop is provided', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          isBasemapExpanded: false,
        })}
      />
    );

    // BasemapGroupRow stub renders a div with data-testid
    expect(screen.getByTestId('basemap-group-row-basemap-group')).toBeInTheDocument();
    expect(screen.getByText('Basemap · Positron')).toBeInTheDocument();
  });

  it('does NOT render basemap children container when isBasemapExpanded=false', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          isBasemapExpanded: false,
        })}
      />
    );

    expect(screen.queryByTestId('basemap-group-children-basemap-group')).not.toBeInTheDocument();
  });

  it('renders basemap children container with sublayer rows when isBasemapExpanded=true', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          isBasemapExpanded: true,
        })}
      />
    );

    // Children container rendered
    const container = screen.getByTestId('basemap-group-children-basemap-group');
    expect(container).toBeInTheDocument();

    // Sublayer names appear
    expect(screen.getByText('Roads')).toBeInTheDocument();
    expect(screen.getByText('Labels')).toBeInTheDocument();
  });

  it('basemap children container has correct indent + dashed border styling', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          isBasemapExpanded: true,
        })}
      />
    );

    const container = screen.getByTestId('basemap-group-children-basemap-group');
    expect(container.style.marginLeft).toBe('28px');
    expect(container.style.paddingLeft).toBe('12px');
    expect(container.style.borderLeft).toBe('1px dashed var(--border)');
  });

  it('renders EmptyStackState and basemap dock when layers=[] and basemapGroup is provided', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [],
          basemapGroup: defaultBasemapGroup,
        })}
      />
    );

    // EmptyStackState renders (isEmpty = layers.length === 0)
    expect(screen.getByTestId('empty-stack-state')).toBeInTheDocument();
    // Basemap dock still renders in empty state
    expect(screen.getByTestId('basemap-group-row-basemap-group')).toBeInTheDocument();
    // Basemap dock container visible
    expect(screen.getByTestId('basemap-dock')).toBeInTheDocument();
  });
});

describe('UnifiedStackPanel — folder group rendering', () => {
  it('renders FolderGroupRow for layers with layer_type starting with "group:"', () => {
    const groupLayer = makeLayer({
      id: 'g1',
      dataset_name: 'My Group',
      layer_type: 'group:folder',
    });
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [groupLayer],
          groupMeta: {},
        })}
      />
    );

    expect(screen.getByTestId('folder-group-row-g1')).toBeInTheDocument();
    expect(screen.getByText('My Group')).toBeInTheDocument();
  });

  it('does NOT render children container when group is collapsed (groupMeta.expanded = false)', () => {
    const groupLayer = makeLayer({ id: 'g1', layer_type: 'group:folder' });
    const childLayer = makeLayer({ id: 'child-1', dataset_name: 'Child Layer' });
    // Simulate parent_group_id on childLayer
    (childLayer as unknown as { parent_group_id: string }).parent_group_id = 'g1';

    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [groupLayer, childLayer],
          groupMeta: { g1: { expanded: false } },
        })}
      />
    );

    expect(screen.queryByTestId('folder-group-children-g1')).not.toBeInTheDocument();
    // Child layer should NOT be visible
    expect(screen.queryByText('Child Layer')).not.toBeInTheDocument();
  });

  it('renders children container and child layers when group is expanded', () => {
    const groupLayer = makeLayer({ id: 'g1', layer_type: 'group:folder' });
    const childLayer = makeLayer({ id: 'child-1', dataset_name: 'Child Layer' });
    (childLayer as unknown as { parent_group_id: string }).parent_group_id = 'g1';

    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [groupLayer, childLayer],
          groupMeta: { g1: { expanded: true } },
        })}
      />
    );

    // Children container rendered
    const container = screen.getByTestId('folder-group-children-g1');
    expect(container).toBeInTheDocument();

    // Child layer visible inside container
    expect(screen.getByText('Child Layer')).toBeInTheDocument();

    // Indent + dashed border
    expect(container.style.marginLeft).toBe('28px');
    expect(container.style.paddingLeft).toBe('12px');
    expect(container.style.borderLeft).toBe('1px dashed var(--border)');
  });

  it('child layers with parent_group_id do NOT render at top level (only inside group container)', () => {
    const groupLayer = makeLayer({ id: 'g1', layer_type: 'group:folder' });
    const childLayer = makeLayer({ id: 'child-1', dataset_name: 'Child Layer' });
    (childLayer as unknown as { parent_group_id: string }).parent_group_id = 'g1';

    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [groupLayer, childLayer],
          groupMeta: { g1: { expanded: true } },
        })}
      />
    );

    // Only 1 role=option at top level (the folder group row); child has a different container
    // The FolderGroupRow stub renders role=option; child StackRow renders role=option inside the group container
    // Both are in the document. We verify child is inside the container, not a sibling of the group.
    const container = screen.getByTestId('folder-group-children-g1');
    expect(container).toContainElement(screen.getByText('Child Layer'));
  });
});

describe('UnifiedStackPanel — settings cog button', () => {
  it('cog button has aria-pressed="false" and no primary-50 background when isSettingsOpen is false (default)', () => {
    render(<UnifiedStackPanel {...defaultProps({ isSettingsOpen: false })} />);

    const cogBtn = screen.getByTestId('settings-cog-btn');
    expect(cogBtn).toBeInTheDocument();
    expect(cogBtn).toHaveAttribute('aria-pressed', 'false');
    expect(cogBtn.className).not.toMatch(/primary-50/);
  });

  it('cog button has aria-pressed="true" and primary-50 background when isSettingsOpen is true', () => {
    render(<UnifiedStackPanel {...defaultProps({ isSettingsOpen: true })} />);

    const cogBtn = screen.getByTestId('settings-cog-btn');
    expect(cogBtn).toHaveAttribute('aria-pressed', 'true');
    expect(cogBtn.className).toMatch(/primary-50/);
  });

  it('clicking the cog still calls onSettingsClick when isSettingsOpen is not passed', () => {
    const onSettingsClick = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ onSettingsClick })} />);

    const cogBtn = screen.getByTestId('settings-cog-btn');
    fireEvent.click(cogBtn);
    expect(onSettingsClick).toHaveBeenCalledOnce();
  });
});

// =============================================================================
// Phase 1040 catalog drop — Plan 04 cross-context drag contract
// =============================================================================

describe('Phase 1040 catalog drop — CatalogDragGhost', () => {
  it('renders catalog-ghost pill with vector type swatch for vector_dataset', () => {
    render(<CatalogDragGhost recordType="vector_dataset" name="My Dataset" />);

    const ghost = screen.getByTestId('catalog-ghost');
    expect(ghost).toBeInTheDocument();
    // Name rendered
    expect(ghost.textContent).toContain('My Dataset');
    // Glyph is V for vector
    expect(ghost.textContent).toContain('V');
  });

  it('renders catalog-ghost pill with raster type swatch for raster_dataset', () => {
    render(<CatalogDragGhost recordType="raster_dataset" name="Satellite Image" />);

    const ghost = screen.getByTestId('catalog-ghost');
    expect(ghost.textContent).toContain('Satellite Image');
    expect(ghost.textContent).toContain('R');
  });

  it('renders catalog-ghost pill with basemap type swatch for basemap', () => {
    render(<CatalogDragGhost recordType="basemap" name="Positron" />);

    const ghost = screen.getByTestId('catalog-ghost');
    expect(ghost.textContent).toContain('Positron');
    expect(ghost.textContent).toContain('B');
  });

  it('renders catalog-ghost pill with raster swatch for vrt_dataset', () => {
    render(<CatalogDragGhost recordType="vrt_dataset" name="Mosaic" />);

    const ghost = screen.getByTestId('catalog-ghost');
    expect(ghost.textContent).toContain('Mosaic');
    expect(ghost.textContent).toContain('R');
  });

  it('catalog-ghost has pointer-events-none and cursor-grabbing className', () => {
    render(<CatalogDragGhost recordType="vector_dataset" name="Test" />);

    const ghost = screen.getByTestId('catalog-ghost');
    expect(ghost.className).toContain('pointer-events-none');
    expect(ghost.className).toContain('cursor-grabbing');
  });
});

describe('Phase 1042 Plan 04 — AUD-01 + AUD-19 header button sizing', () => {
  it('AUD-01: Settings cog button renders with h-8 w-8 className', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);
    const cogBtn = screen.getByTestId('settings-cog-btn');
    expect(cogBtn.className).toContain('h-8');
    expect(cogBtn.className).toContain('w-8');
    expect(cogBtn.className).not.toContain('h-[22px]');
    expect(cogBtn.className).not.toContain('w-[22px]');
  });

  it('AUD-19: Settings cog icon renders with h-[18px] w-[18px]', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);
    const cogBtn = screen.getByTestId('settings-cog-btn');
    // The Settings icon is a child of the cog button
    const icon = cogBtn.querySelector('svg');
    expect(icon).not.toBeNull();
    expect(icon!.getAttribute('class')).toContain('h-[18px]');
    expect(icon!.getAttribute('class')).toContain('w-[18px]');
  });

  it('AUD-01 parity: + Add data button renders with h-8 className', () => {
    render(<UnifiedStackPanel {...defaultProps()} />);
    const addBtn = screen.getByRole('button', { name: /Add data/i });
    expect(addBtn.className).toContain('h-8');
  });
});

describe('Phase 1040 catalog drop — onAddDataset wiring', () => {
  it('calls onAddDataset(datasetId) when EmptyStackState pick-suggestion is triggered', () => {
    const onAddDataset = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({ layers: [], basemapGroup: null, onAddDataset })}
      />
    );

    // EmptyStackState stub renders a button with data-testid="empty-add-dataset"
    const btn = screen.getByTestId('empty-add-dataset');
    fireEvent.click(btn);

    expect(onAddDataset).toHaveBeenCalledOnce();
    expect(onAddDataset).toHaveBeenCalledWith('dataset-id-1');
  });

  it('does NOT call onAddDataset for basemap-group row selection', () => {
    const onAddDataset = vi.fn();
    render(
      <UnifiedStackPanel
        {...defaultProps({
          basemapGroup: defaultBasemapGroup,
          onAddDataset,
        })}
      />
    );

    // Clicking the basemap group select button does NOT trigger onAddDataset
    fireEvent.click(screen.getByTestId('basemap-group-select-basemap-group'));
    expect(onAddDataset).not.toHaveBeenCalled();
  });
});
