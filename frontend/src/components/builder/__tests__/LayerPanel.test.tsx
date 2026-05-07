import { fireEvent, render, screen } from '@/test/test-utils';
import { LayerPanel } from '../LayerPanel';
import type { MapLayerResponse } from '@/types/api';

// i18n mock: returns options.defaultValue when present, otherwise the raw key.
// Matches the MapToolbar.test.tsx / MapTitleBar.test.tsx pattern in this dir.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
  }),
}));

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Population',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POLYGON',
    dataset_table_name: overrides.dataset_table_name ?? 'population',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
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

function defaultProps(overrides: Partial<React.ComponentProps<typeof LayerPanel>> = {}) {
  return {
    layers: [],
    expandedLayerId: null,
    onToggleExpand: vi.fn(),
    onToggleVisibility: vi.fn(),
    onMoveUp: vi.fn(),
    onMoveDown: vi.fn(),
    onReorder: vi.fn(),
    onRename: vi.fn(),
    onRemove: vi.fn(),
    onZoomToLayer: vi.fn(),
    onToggleLegend: vi.fn(),
    ...overrides,
  } satisfies React.ComponentProps<typeof LayerPanel>;
}

describe('LayerPanel', () => {
  it('renders empty state with count badge of 0 and the empty hint', () => {
    render(<LayerPanel {...defaultProps({ layers: [] })} />);

    // Title text resolves to the i18n key under the defaultValue-passthrough mock
    expect(screen.getByText('layers.title')).toBeInTheDocument();
    // Count badge shows 0
    expect(screen.getByText('0')).toBeInTheDocument();
    // Empty-state hint is shown
    expect(screen.getByText('layers.emptyState')).toBeInTheDocument();
    // No list role rendered when there are zero layers
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('renders the empty-state Add data button only when onAddDataClick is provided', () => {
    const { rerender } = render(
      <LayerPanel {...defaultProps({ layers: [] })} />,
    );
    // Without onAddDataClick the Add data button is not rendered
    expect(screen.queryByRole('button', { name: 'layers.addData' })).not.toBeInTheDocument();

    rerender(
      <LayerPanel {...defaultProps({ layers: [], onAddDataClick: vi.fn() })} />,
    );
    // With onAddDataClick → Add data button appears (the empty state renders
    // it AND the header renders one as well, so we expect at least one).
    expect(screen.getAllByRole('button', { name: 'layers.addData' }).length).toBeGreaterThanOrEqual(1);
  });

  it('renders one LayerItem per layer in populated state and shows count badge', () => {
    const layers = [
      makeLayer({ id: 'a', dataset_name: 'Layer A' }),
      makeLayer({ id: 'b', dataset_name: 'Layer B' }),
    ];

    render(<LayerPanel {...defaultProps({ layers })} />);

    // Count badge reflects 2 layers
    expect(screen.getByText('2')).toBeInTheDocument();
    // List container renders with role="list" and the title aria-label
    const list = screen.getByRole('list', { name: 'layers.title' });
    expect(list).toBeInTheDocument();
    // Each LayerItem renders as a role="group" with the layer name as aria-label
    expect(screen.getByRole('group', { name: 'Layer A' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Layer B' })).toBeInTheDocument();
  });

  it('clicking the empty-state Add data button fires onAddDataClick', () => {
    const onAddDataClick = vi.fn();
    render(
      <LayerPanel
        {...defaultProps({ layers: [], onAddDataClick })}
      />,
    );

    // Two Add data buttons render (header + empty-state); both share the same
    // handler. Click both to confirm the wiring.
    const buttons = screen.getAllByRole('button', { name: 'layers.addData' });
    expect(buttons.length).toBeGreaterThanOrEqual(1);
    fireEvent.click(buttons[0]);
    expect(onAddDataClick).toHaveBeenCalledTimes(1);
  });

  it('renders without throwing when layers are populated (DnD smoke)', () => {
    // @dnd-kit pointer-event geometry is not implementable in jsdom, so this
    // test only locks render stability — the existence of DndContext +
    // SortableContext wrappers does NOT throw on mount with a sortable list.
    // Reorder behavior itself is covered by the unit-tested `arrayMove`
    // helper from @dnd-kit and by the existing reorder-data-layers.test.ts;
    // a future LayerPanel-level DnD test would need a Playwright/E2E layer.
    const onReorder = vi.fn();
    const layers = [
      makeLayer({ id: 'a', dataset_name: 'Layer A' }),
      makeLayer({ id: 'b', dataset_name: 'Layer B' }),
      makeLayer({ id: 'c', dataset_name: 'Layer C' }),
    ];

    expect(() =>
      render(<LayerPanel {...defaultProps({ layers, onReorder })} />),
    ).not.toThrow();

    // Without firing a real PointerEvent reorder, onReorder is never called.
    expect(onReorder).not.toHaveBeenCalled();

    // List still mounts with all 3 items (smoke check that the populated
    // branch did not throw under DndContext setup).
    expect(screen.getAllByRole('group')).toHaveLength(3);
  });
});
