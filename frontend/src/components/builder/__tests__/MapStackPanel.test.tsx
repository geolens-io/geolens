import { fireEvent, render, screen, within } from '@/test/test-utils';
import { MapStackPanel } from '../MapStackPanel';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';
import type { BasemapEntry } from '@/api/settings';

const mockBasemaps: BasemapEntry[] = [
  { id: 'openfreemap-positron', label: 'Positron', url: 'https://example.com/positron', enabled: true, is_preset: true },
  { id: 'openfreemap-dark', label: 'Dark', url: 'https://example.com/dark', enabled: true, is_preset: true },
];

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
  }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: vi.fn(() => ({ data: mockBasemaps })),
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

function defaultProps(overrides: Partial<React.ComponentProps<typeof MapStackPanel>> = {}) {
  return {
    layers: [],
    expandedLayerId: null,
    basemapStyle: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    terrainConfig: null,
    widgets: [],
    onToggleExpand: vi.fn(),
    onToggleVisibility: vi.fn(),
    onMoveUp: vi.fn(),
    onMoveDown: vi.fn(),
    onReorder: vi.fn(),
    onRename: vi.fn(),
    onRemove: vi.fn(),
    onZoomToLayer: vi.fn(),
    onToggleLegend: vi.fn(),
    onOpacityChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onRenderAsChange: vi.fn(),
    onDuplicateRendering: vi.fn(),
    onAddDataClick: vi.fn(),
    onBasemapChange: vi.fn(),
    onBasemapLabelsChange: vi.fn(),
    onBasemapConfigChange: vi.fn(),
    onTerrainChange: vi.fn(),
    ...overrides,
  } satisfies React.ComponentProps<typeof MapStackPanel>;
}

describe('MapStackPanel', () => {
  it('puts an empty map data prompt before stack sections', () => {
    const onAddDataClick = vi.fn();

    render(<MapStackPanel {...defaultProps({ onAddDataClick })} />);

    const prompt = screen.getByTestId('map-stack-empty-data-first');
    expect(prompt).toHaveTextContent('Start with data');
    expect(prompt.compareDocumentPosition(screen.getByRole('heading', { name: 'Surface' })))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);

    fireEvent.click(within(prompt).getByRole('button', { name: 'layers.addData' }));
    expect(onAddDataClick).toHaveBeenCalledTimes(1);
  });

  it('renders the unified stack groups with basemap, data, labels, and interactions', () => {
    const terrainConfig: MapTerrainConfig = {
      enabled: true,
      source_dataset_id: 'dem-dataset',
      exaggeration: 2,
    };
    const layers = [
      makeLayer({
        id: 'data-layer',
        dataset_name: 'Population',
        sort_order: 0,
        label_config: { column: 'name' },
        popup_config: { enabled: true, expression: null, visible_fields: null },
      }),
      makeLayer({
        id: 'dem-layer',
        dataset_id: 'dem-dataset',
        dataset_name: 'Elevation',
        dataset_geometry_type: null,
        dataset_record_type: 'raster_dataset',
        layer_type: 'raster_geolens',
        is_dem: true,
        style_config: {
          mode: 'categorical',
          column: '',
          ramp: '',
          render_mode: 'hillshade',
        },
        sort_order: 1,
      }),
    ];

    render(
      <MapStackPanel
        {...defaultProps({
          layers,
          terrainConfig,
          widgets: ['legend'],
          widgetSidebar: <div data-testid="widget-sidebar" />,
        })}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Map Stack' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Surface' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Relief' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Basemap' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Data' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Labels' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Interactions' })).toBeInTheDocument();
    expect(screen.getByText('Population')).toBeInTheDocument();
    expect(screen.getAllByText('Elevation').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Preset').length).toBeGreaterThan(0);
    expect(screen.getByText('Place labels')).toBeInTheDocument();
    expect(screen.getByText(/visible DEM-derived relief layer\. Terrain remains a surface setting\./)).toBeInTheDocument();
    expect(screen.getByTestId('widget-sidebar')).toBeInTheDocument();
  });

  it('keeps primary layer actions available from stack rows', () => {
    const onToggleVisibility = vi.fn();
    const onToggleExpand = vi.fn();
    const onAddDataClick = vi.fn();
    const layers = [makeLayer({ id: 'layer-1', dataset_name: 'Population' })];

    render(
      <MapStackPanel
        {...defaultProps({
          layers,
          onToggleVisibility,
          onToggleExpand,
          onAddDataClick,
        })}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Hide layer' }));
    expect(onToggleVisibility).toHaveBeenCalledWith('layer-1');

    fireEvent.click(screen.getByRole('button', { name: 'Expand options' }));
    expect(onToggleExpand).toHaveBeenCalledWith('layer-1');

    fireEvent.click(screen.getByRole('button', { name: 'layers.addData' }));
    expect(onAddDataClick).toHaveBeenCalledTimes(1);
  });

  it('renders v1 row controls for renderAs, opacity, and zoom range', () => {
    const layer = makeLayer({
      id: 'layer-1',
      dataset_name: 'Population',
      dataset_geometry_type: 'POLYGON',
      opacity: 0.65,
      layout: { _minzoom: 3, _maxzoom: 14 },
    });

    render(<MapStackPanel {...defaultProps({ layers: [layer] })} />);

    const row = screen.getByTestId('layer-item-layer-1');
    expect(within(row).getByRole('button', { name: 'Render as Fill + Stroke' })).toBeInTheDocument();
    expect(within(row).getByRole('spinbutton', { name: 'Population opacity percent' })).toHaveValue(65);
    expect(within(row).getByRole('button', { name: 'Population zoom range' })).toHaveTextContent('z3-14');
    expect(within(row).getByRole('button', { name: 'Hide layer' })).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Expand options' })).toBeInTheDocument();
  });

  it('writes row opacity and zoom range through existing layer handlers', () => {
    const onOpacityChange = vi.fn();
    const onLayoutChange = vi.fn();
    const layer = makeLayer({
      id: 'layer-1',
      dataset_name: 'Population',
      opacity: 0.65,
      layout: { _minzoom: 3, _maxzoom: 14, 'line-dasharray': [2, 4] },
    });

    render(
      <MapStackPanel
        {...defaultProps({
          layers: [layer],
          onOpacityChange,
          onLayoutChange,
        })}
      />,
    );

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Population opacity percent' }), {
      target: { value: '42' },
    });
    expect(onOpacityChange).toHaveBeenCalledWith('layer-1', 0.42);

    fireEvent.click(screen.getByRole('button', { name: 'Population zoom range' }));
    fireEvent.change(screen.getByLabelText('Min'), { target: { value: '5' } });
    expect(onLayoutChange).toHaveBeenCalledWith('layer-1', {
      _minzoom: 5,
      _maxzoom: 14,
      'line-dasharray': [2, 4],
    });
  });

  it('routes renderAs and duplicate-rendering row actions', () => {
    const onRenderAsChange = vi.fn();
    const onDuplicateRendering = vi.fn();
    const layer = makeLayer({
      id: 'layer-1',
      dataset_name: 'Incidents',
      dataset_geometry_type: 'POINT',
    });

    render(
      <MapStackPanel
        {...defaultProps({
          layers: [layer],
          onRenderAsChange,
          onDuplicateRendering,
        })}
      />,
    );

    fireEvent.pointerDown(screen.getByRole('button', { name: 'layerItem.moreActions' }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole('menuitem', { name: 'Duplicate rendering' }));
    expect(onDuplicateRendering).toHaveBeenCalledWith('layer-1');

    fireEvent.click(screen.getByRole('button', { name: 'Render as Point' }));
    fireEvent.click(screen.getByRole('button', { name: 'Heatmap' }));
    expect(onRenderAsChange).toHaveBeenCalledWith('layer-1', 'heatmap');
  });

  it('renders collapsible dataset-rendering headers only for duplicated dataset renderings', () => {
    const layers = [
      makeLayer({
        id: 'population-fill',
        dataset_id: 'population',
        dataset_name: 'Population',
        dataset_feature_count: 10_000,
        sort_order: 0,
      }),
      makeLayer({
        id: 'population-outline',
        dataset_id: 'population',
        dataset_name: 'Population',
        dataset_feature_count: 10_000,
        sort_order: 1,
      }),
      makeLayer({
        id: 'roads',
        dataset_id: 'roads',
        dataset_name: 'Roads',
        dataset_geometry_type: 'LINESTRING',
        sort_order: 2,
      }),
    ];

    render(<MapStackPanel {...defaultProps({ layers })} />);

    const datasetGroup = screen.getByTestId('dataset-rendering-group-population');
    expect(datasetGroup).toHaveTextContent('Population');
    expect(datasetGroup).toHaveTextContent('Vector Dataset');
    expect(datasetGroup).toHaveTextContent('POLYGON');
    expect(datasetGroup).toHaveTextContent('10,000 features');
    expect(datasetGroup).toHaveTextContent('2 renderings');
    expect(datasetGroup).not.toHaveTextContent('LIVE');
    expect(screen.queryByTestId('dataset-rendering-group-roads')).not.toBeInTheDocument();
  });

  it('exposes selected, hidden, locked, and unsupported row states', () => {
    const layers = [
      makeLayer({
        id: 'active-hidden',
        dataset_name: 'Selected Counties',
        visible: false,
      }),
      makeLayer({
        id: 'unsupported',
        dataset_name: 'Table Only',
        dataset_geometry_type: null,
        layer_type: 'vector_geolens',
        dataset_record_type: 'vector_dataset',
        sort_order: 1,
      }),
    ];

    render(
      <MapStackPanel
        {...defaultProps({
          layers,
          expandedLayerId: 'active-hidden',
          terrainConfig: { enabled: true, source_dataset_id: 'missing-dem', exaggeration: 1 },
        })}
      />,
    );

    expect(screen.getByTestId('layer-item-active-hidden')).toHaveAttribute('data-state', 'selected');
    expect(screen.getByTestId('layer-item-active-hidden')).toHaveAccessibleName(/Selected/);
    expect(screen.getByTestId('layer-item-unsupported')).toHaveAttribute('data-state', 'unsupported');
    expect(screen.getByTestId('layer-item-unsupported')).toHaveAccessibleName(/Unsupported/);
    expect(screen.getAllByTestId('map-stack-item').some((row) => row.getAttribute('data-state') === 'error')).toBe(true);
    expect(screen.getAllByTestId('map-stack-item').some((row) => row.getAttribute('data-locked') === 'true')).toBe(true);
  });

  it('routes basemap label toggles through the labels group row', () => {
    const onBasemapLabelsChange = vi.fn();

    render(
      <MapStackPanel
        {...defaultProps({
          showBasemapLabels: false,
          onBasemapLabelsChange,
        })}
      />,
    );

    const labelsSection = screen.getByRole('heading', { name: 'Labels' }).closest('section');
    expect(labelsSection).not.toBeNull();
    const switchControl = within(labelsSection as HTMLElement).getByRole('switch', {
      name: 'Toggle basemap labels',
    });

    fireEvent.click(switchControl);
    expect(onBasemapLabelsChange).toHaveBeenCalledWith(true);
  });
});
