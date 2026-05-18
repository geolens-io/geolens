// Phase 1051 UX-03: Basemap row is draggable in the layer order with saved-map
// persistence. Encodes position in MapBasemapConfig.basemap_position (jsonb,
// no backend migration). Drag preserves basemap-as-group semantics — the
// basemap row moves between 'top' and 'bottom' positions in the unified stack.
//
// These tests exercise the rendering + drag-handle wiring contract on
// UnifiedStackPanel and the real BasemapGroupRow (no mock — the prior
// UnifiedStackPanel.test.tsx mocks BasemapGroupRow to a stub that does not
// surface the grip button or the drag handle, so cannot verify the lift to
// useSortable in isolation). Map-sync.ts side of the round-trip is exercised
// by inspecting the reorderBasemapAboveData helper directly.

import { fireEvent, render, screen } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import { reorderBasemapAboveData } from '../map-sync';
import type { MapLayerResponse } from '@/types/api';
import type { Map as MaplibreMap } from 'maplibre-gl';

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

// EmptyStackState mock so empty-state branch resolves cleanly when needed.
vi.mock('../EmptyStackState', () => ({
  eyebrowClassName: 'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1',
  EmptyStackState: ({ onOpenAddData, onAddDataset }: {
    onOpenAddData: (query?: string) => void;
    onAddDataset: (id: string) => void;
  }) => (
    <div data-testid="empty-stack-state">
      <button data-testid="empty-browse-all" onClick={() => onOpenAddData()}>Browse</button>
      <button data-testid="empty-add-dataset" onClick={() => onAddDataset('d-1')}>Pick</button>
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
    basemapGroup: defaultBasemapGroup,
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

describe('UX-03: BasemapGroupRow drag handle (sortable wiring)', () => {
  it('Test 1: basemap row exposes a real drag-handle button (not a hidden span)', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [makeLayer({ id: 'l1' })],
          basemapGroup: defaultBasemapGroup,
        })}
      />,
    );

    const grip = screen.getByTestId('basemap-drag-handle');
    expect(grip).toBeInTheDocument();
    expect(grip.tagName.toLowerCase()).toBe('button');
    // accessible label routed via i18n key with defaultValue
    expect(grip.getAttribute('aria-label')).toMatch(/drag.*basemap/i);
  });

  it('Test 2: grip button renders a Lucide GripVertical SVG', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [makeLayer({ id: 'l1' })],
          basemapGroup: defaultBasemapGroup,
        })}
      />,
    );
    const grip = screen.getByTestId('basemap-drag-handle');
    const svg = grip.querySelector('svg');
    expect(svg).toBeTruthy();
    expect(svg!.getAttribute('class')).toMatch(/lucide-grip-vertical/);
  });

  it('Test 3: when isMultiSelectionActive=true, grip is rendered as cursor-not-allowed (drag suppressed)', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers: [makeLayer({ id: 'l1' })],
          basemapGroup: defaultBasemapGroup,
          isMultiSelectionActive: true,
        })}
      />,
    );
    const grip = screen.getByTestId('basemap-drag-handle');
    // Class signals drag is suppressed; the @dnd-kit listeners are also not
    // spread in this branch (asserted via the className contract — direct
    // listener-spread inspection isn't reliable in jsdom).
    expect(grip.className).toContain('cursor-not-allowed');
  });

  it('Test 4: basemap row appears BEFORE data layers in DOM order when basemapPosition="top"', () => {
    const layers = [
      makeLayer({ id: 'data-1', dataset_name: 'Data 1' }),
      makeLayer({ id: 'data-2', dataset_name: 'Data 2' }),
    ];
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers,
          basemapGroup: defaultBasemapGroup,
          basemapPosition: 'top',
        })}
      />,
    );
    // Find basemap row + first data row by their data-row-id
    const basemapRow = document.querySelector('[data-row-id="basemap-group"]');
    const firstDataRow = document.querySelector('[data-row-id="data-1"]');
    expect(basemapRow).toBeTruthy();
    expect(firstDataRow).toBeTruthy();
    // DOM order: basemap should precede first data row when position='top'
    const pos = basemapRow!.compareDocumentPosition(firstDataRow!);
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('Test 5: basemap row appears AFTER data layers in DOM order when basemapPosition="bottom" (default)', () => {
    const layers = [
      makeLayer({ id: 'data-1', dataset_name: 'Data 1' }),
      makeLayer({ id: 'data-2', dataset_name: 'Data 2' }),
    ];
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers,
          basemapGroup: defaultBasemapGroup,
          basemapPosition: 'bottom',
        })}
      />,
    );
    const basemapRow = document.querySelector('[data-row-id="basemap-group"]');
    const lastDataRow = document.querySelector('[data-row-id="data-2"]');
    expect(basemapRow).toBeTruthy();
    expect(lastDataRow).toBeTruthy();
    const pos = lastDataRow!.compareDocumentPosition(basemapRow!);
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('Test 6: default basemapPosition is "bottom" (legacy compat — undefined → bottom)', () => {
    const layers = [makeLayer({ id: 'data-1' })];
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers,
          basemapGroup: defaultBasemapGroup,
          // basemapPosition intentionally omitted → defaults to 'bottom'
        })}
      />,
    );
    const basemapRow = document.querySelector('[data-row-id="basemap-group"]');
    const dataRow = document.querySelector('[data-row-id="data-1"]');
    expect(basemapRow).toBeTruthy();
    expect(dataRow).toBeTruthy();
    // legacy default: basemap below data → data precedes basemap in DOM
    const pos = dataRow!.compareDocumentPosition(basemapRow!);
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('UX-03: reorderBasemapAboveData (map-sync helper)', () => {
  function makeMockMap(layers: Array<{ id: string; source?: string }>): MaplibreMap {
    const moveLayer = vi.fn();
    return {
      moveLayer,
      getLayer: (id: string) => layers.some((l) => l.id === id) ? { id } : undefined,
      getStyle: () => ({ layers }),
    } as unknown as MaplibreMap;
  }

  it('Test 7: when position="top", moveLayer dispatches for every non-data style layer', () => {
    const styleLayers = [
      { id: 'background', source: undefined }, // basemap background (no source)
      { id: 'water', source: 'openmaptiles' }, // basemap layer (non-data source prefix)
      { id: 'layer-data-1', source: 'source-data-population' }, // data layer
    ];
    const map = makeMockMap(styleLayers);
    reorderBasemapAboveData(map, 'top');
    // 'background' (no source) and 'water' (non-data prefix) should be moved;
    // 'layer-data-1' (source starts with 'source-') should NOT be moved.
    expect(map.moveLayer).toHaveBeenCalledWith('background');
    expect(map.moveLayer).toHaveBeenCalledWith('water');
    expect(map.moveLayer).not.toHaveBeenCalledWith('layer-data-1');
    expect((map.moveLayer as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(2);
  });

  it('Test 8: when position="bottom" (default), moveLayer is NEVER called (no-op)', () => {
    const styleLayers = [
      { id: 'background', source: undefined },
      { id: 'water', source: 'openmaptiles' },
      { id: 'layer-data-1', source: 'source-data-population' },
    ];
    const map = makeMockMap(styleLayers);
    reorderBasemapAboveData(map, 'bottom');
    expect(map.moveLayer).not.toHaveBeenCalled();
  });

  it('Test 9: when position=undefined (legacy), moveLayer is NEVER called', () => {
    const styleLayers = [{ id: 'water', source: 'openmaptiles' }];
    const map = makeMockMap(styleLayers);
    reorderBasemapAboveData(map, undefined);
    expect(map.moveLayer).not.toHaveBeenCalled();
  });

  it('Test 10: ignores layers that no longer exist on the map (getLayer returns undefined)', () => {
    const moveLayer = vi.fn();
    const map = {
      moveLayer,
      // Style still lists 'old-layer' but getLayer says it's gone (race during teardown)
      getLayer: (id: string) => id === 'water' ? { id } : undefined,
      getStyle: () => ({
        layers: [
          { id: 'old-layer', source: 'openmaptiles' },
          { id: 'water', source: 'openmaptiles' },
        ],
      }),
    } as unknown as MaplibreMap;
    reorderBasemapAboveData(map, 'top');
    expect(moveLayer).toHaveBeenCalledWith('water');
    expect(moveLayer).not.toHaveBeenCalledWith('old-layer');
  });

  it('Test 11: respects custom sourcePrefix for viewer/embed contexts', () => {
    const styleLayers = [
      { id: 'water', source: 'openmaptiles' }, // basemap
      { id: 'embed-layer-data-1', source: 'embed-source-data-pop' }, // data (embed prefix)
    ];
    const map = makeMockMap(styleLayers);
    reorderBasemapAboveData(map, 'top', 'embed-source-');
    expect(map.moveLayer).toHaveBeenCalledWith('water');
    expect(map.moveLayer).not.toHaveBeenCalledWith('embed-layer-data-1');
  });
});

describe('UX-03: round-trip persistence shape (MapBasemapConfig.basemap_position)', () => {
  it('Test 12: MapBasemapConfig type accepts optional basemap_position field', () => {
    // Compile-time + runtime assertion via cast — TS will fail if the field
    // doesn't exist on the interface (caught by `npx tsc --noEmit`).
    const cfg: import('@/types/api').MapBasemapConfig = {
      label_mode: 'full',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      basemap_position: 'top',
    };
    expect(cfg.basemap_position).toBe('top');
    // 'bottom' is also valid
    cfg.basemap_position = 'bottom';
    expect(cfg.basemap_position).toBe('bottom');
    // undefined is the legacy default (field is optional)
    cfg.basemap_position = undefined;
    expect(cfg.basemap_position).toBeUndefined();
  });

  it('Test 13: omitting basemap_position from the config is legal (legacy maps)', () => {
    const legacyCfg: import('@/types/api').MapBasemapConfig = {
      label_mode: 'full',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
    };
    // Field is optional — undefined access is allowed
    expect(legacyCfg.basemap_position).toBeUndefined();
  });
});

it('Test 14: clicking on the drag handle button alone does not trigger row selection (stopPropagation)', () => {
  const onSelectLayer = vi.fn();
  render(
    <UnifiedStackPanel
      {...defaultProps({
        layers: [makeLayer({ id: 'l1' })],
        basemapGroup: defaultBasemapGroup,
        onSelectLayer,
      })}
    />,
  );
  const grip = screen.getByTestId('basemap-drag-handle');
  fireEvent.click(grip);
  // onSelectLayer should NOT be called from a grip click (stopPropagation prevents bubble to row onClick).
  // It may be called for other reasons (drag-start clears selection), but a plain click should not select.
  // Allow zero or sublayer-trigger calls; just assert it was not called with the basemap group id from a click bubble.
  const basemapSelectCalls = onSelectLayer.mock.calls.filter((args) => args[0] === 'basemap-group');
  expect(basemapSelectCalls).toHaveLength(0);
});
