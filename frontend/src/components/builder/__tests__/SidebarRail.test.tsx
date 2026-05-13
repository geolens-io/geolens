import { fireEvent, render, screen } from '@/test/test-utils';
import { SidebarRail } from '../SidebarRail';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
  }),
}));

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

function defaultProps(overrides: Partial<React.ComponentProps<typeof SidebarRail>> = {}) {
  return {
    layers: [],
    selectedLayerId: null,
    onSelectLayer: vi.fn(),
    onAddDataClick: vi.fn(),
    onSettingsClick: vi.fn(),
    ...overrides,
  };
}

describe('SidebarRail', () => {
  it('renders 64px-wide column with Settings icon, ＋ Add data icon, and one button per layer', () => {
    const layers = [
      makeLayer({ id: 'l1', dataset_name: 'Alpha' }),
      makeLayer({ id: 'l2', dataset_name: 'Beta' }),
    ];
    const { container } = render(<SidebarRail {...defaultProps({ layers })} />);

    // 64px column — check the rail container class
    const rail = container.firstElementChild;
    expect(rail).toBeTruthy();
    expect(rail!.className).toMatch(/w-16|w-\[64px\]/);

    // Settings button
    expect(screen.getByRole('button', { name: /Settings/i })).toBeInTheDocument();
    // Add data button
    expect(screen.getByRole('button', { name: /Add data/i })).toBeInTheDocument();
    // One button per layer
    expect(screen.getByRole('button', { name: /Alpha/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Beta/i })).toBeInTheDocument();
  });

  it('clicking a layer icon calls onSelectLayer(layer.id)', () => {
    const onSelectLayer = vi.fn();
    const layer = makeLayer({ id: 'click-layer', dataset_name: 'Click Me' });
    render(<SidebarRail {...defaultProps({ layers: [layer], onSelectLayer })} />);

    fireEvent.click(screen.getByRole('button', { name: /Click Me/i }));
    expect(onSelectLayer).toHaveBeenCalledOnce();
    expect(onSelectLayer).toHaveBeenCalledWith('click-layer');
  });

  it('selected layer button has data-selected="true" or primary-50 class', () => {
    const layer = makeLayer({ id: 'selected-layer', dataset_name: 'Selected' });
    render(<SidebarRail {...defaultProps({ layers: [layer], selectedLayerId: 'selected-layer' })} />);

    const btn = screen.getByRole('button', { name: /Selected/i });
    // Either data-selected or a class containing primary-50
    const hasSelectedAttr = btn.getAttribute('data-selected') === 'true';
    const hasSelectedClass = btn.className.includes('primary-50');
    expect(hasSelectedAttr || hasSelectedClass).toBe(true);
  });
});
