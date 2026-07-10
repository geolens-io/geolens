// BLDR-03 regression pin: terrain-mode DEM layers are suppressed from the
// UnifiedStackPanel stack render via the visibleStackLayers memo.
// Hillshade-mode DEM layers still render rows (⛰ glyph); terrain-mode DEM
// layers are filtered out and produce no [data-row-id] element.
//
// Reuses the UnifiedStackPanel render harness from
// UnifiedStackPanel.basemap-drag.test.tsx (same required props, providers,
// i18n + icon mocks).

import { render } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
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

vi.mock('../EmptyStackState', () => ({
  eyebrowClassName: 'block text-2xs font-semibold tracking-wide text-muted-foreground uppercase px-1',
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeDemLayer(
  id: string,
  renderMode: 'hillshade' | 'terrain' | 'image',
): MapLayerResponse {
  return {
    id,
    dataset_id: `dataset-${id}`,
    dataset_name: `DEM ${id}`,
    dataset_geometry_type: null,
    dataset_table_name: `dem_${id}`,
    dataset_extent_bbox: [0, 0, 1, 1],
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: { render_mode: renderMode } as MapLayerResponse['style_config'],
    layer_type: null,
    dataset_record_type: 'raster_dataset',
    show_in_legend: true,
    is_dem: true,
    dem_vertical_units: null,
  };
}

const defaultBasemapGroup = {
  id: 'basemap-group',
  presetName: 'Positron',
  providerLabel: 'OpenFreeMap',
  visible: true,
  opacity: 1,
  sublayers: [],
};

function defaultProps(
  layers: MapLayerResponse[],
  overrides: Partial<React.ComponentProps<typeof UnifiedStackPanel>> = {},
) {
  return {
    layers,
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
    onBulkVisibility: vi.fn(),
    onBulkOpacity: vi.fn(),
    onBulkGroup: vi.fn(),
    onBulkUngroup: vi.fn(),
    onBulkDelete: vi.fn(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('UnifiedStackPanel BLDR-03: terrain-mode DEM row suppression', () => {
  it('hillshade DEM row IS rendered (data-row-id present); terrain-mode DEM row is NOT rendered (data-row-id absent)', () => {
    const hillshadeDem = makeDemLayer('dem-hillshade', 'hillshade');
    const terrainDem = makeDemLayer('dem-terrain', 'terrain');

    render(
      <UnifiedStackPanel
        {...defaultProps([hillshadeDem, terrainDem])}
      />,
    );

    // Hillshade DEM: visibleStackLayers includes it → StackRow renders with data-row-id
    const hillshadeRow = document.querySelector('[data-row-id="dem-hillshade"]');
    expect(hillshadeRow).toBeTruthy();

    // Terrain-mode DEM: visibleStackLayers filters it out via isDemTerrainVisualSuppressed
    // → no SortableStackRow is rendered for this layer id
    const terrainRow = document.querySelector('[data-row-id="dem-terrain"]');
    expect(terrainRow).toBeNull();
  });

  it('non-DEM layer rows are unaffected by the terrain suppression filter', () => {
    const terrainDem = makeDemLayer('dem-terrain', 'terrain');
    const vectorLayer: MapLayerResponse = {
      id: 'vector-pop',
      dataset_id: 'dataset-pop',
      dataset_name: 'Population',
      dataset_geometry_type: 'POLYGON',
      dataset_table_name: 'population',
      dataset_extent_bbox: [0, 0, 1, 1],
      dataset_column_info: null,
      dataset_feature_count: null,
      dataset_sample_values: null,
      display_name: null,
      sort_order: 1,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: null,
      layer_type: null,
      dataset_record_type: 'vector_dataset',
      show_in_legend: true,
      is_dem: false,
      dem_vertical_units: null,
    };

    render(
      <UnifiedStackPanel
        {...defaultProps([terrainDem, vectorLayer])}
      />,
    );

    // Vector layer should render normally
    const vectorRow = document.querySelector('[data-row-id="vector-pop"]');
    expect(vectorRow).toBeTruthy();

    // Terrain-mode DEM is still suppressed
    const terrainRow = document.querySelector('[data-row-id="dem-terrain"]');
    expect(terrainRow).toBeNull();
  });

  it('hillshade and image DEM rows both render (only terrain mode is suppressed)', () => {
    const hillshadeDem = makeDemLayer('dem-hillshade', 'hillshade');
    const imageDem = makeDemLayer('dem-image', 'image');
    const terrainDem = makeDemLayer('dem-terrain', 'terrain');

    render(
      <UnifiedStackPanel
        {...defaultProps([hillshadeDem, imageDem, terrainDem])}
      />,
    );

    expect(document.querySelector('[data-row-id="dem-hillshade"]')).toBeTruthy();
    expect(document.querySelector('[data-row-id="dem-image"]')).toBeTruthy();
    expect(document.querySelector('[data-row-id="dem-terrain"]')).toBeNull();
  });
});
