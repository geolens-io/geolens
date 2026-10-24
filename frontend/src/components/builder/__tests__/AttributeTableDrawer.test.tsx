/**
 * Builder attribute-table drawer: eligibility, the converted-filter rows
 * request, the unsupported-filter fallback, and the fit-and-highlight on a
 * row click (click and keyboard activation).
 *
 * The eligibility tests render the REAL kebab (StackRow) and editor header
 * (LayerEditorPanel) so a later refactor that moves the action still fails
 * here until the eligibility contract moves with it.
 */
import { act, fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { beforeAll, beforeEach, vi } from 'vitest';
import { AttributeTableDrawer } from '../AttributeTableDrawer';
import { StackRow } from '../StackRow';
import { LayerEditorPanel, type LayerEditorHandlers } from '../LayerEditorPanel';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import type { EphemeralPreviewRowProps } from '../EphemeralPreviewRow';
import { canOpenAttributeTable } from '@/lib/layer-capabilities';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useUpdateFeature } from '@/hooks/use-features';
import { getFeature } from '@/api/features';
import type { Map as MaplibreMap } from 'maplibre-gl';
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

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));

vi.mock('@/hooks/use-features', () => ({
  useUpdateFeature: vi.fn(),
  useDeleteFeatures: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/use-debounce', () => ({
  useDebouncedValue: (value: unknown) => value,
}));

vi.mock('@/api/features', () => ({
  getFeature: vi.fn(),
}));

// The drawer's fit-and-highlight target: a fake map recording the calls.
// Stateful on purpose: getLayer/getSource report what was added, so the
// drawer's guarded cleanup paths are exercised for real.
function makeFakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  return {
    getLayer: vi.fn((id: string) => (layers.has(id) ? {} : undefined)),
    removeLayer: vi.fn((id: string) => layers.delete(id)),
    getSource: vi.fn((id: string) => (sources.has(id) ? {} : undefined)),
    removeSource: vi.fn((id: string) => sources.delete(id)),
    addSource: vi.fn((_id: string, _def: unknown) => {
      sources.add(_id);
    }),
    addLayer: vi.fn((def: { id: string }) => {
      layers.add(def.id);
    }),
    fitBounds: vi.fn(),
  } as unknown as MaplibreMap & Record<string, ReturnType<typeof vi.fn>>;
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

// jsdom computes no layout, so the real virtualizer renders a zero window of
// rows; render them all instead (same stub as
// AttributeTable.batch-delete.test.tsx).
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        start: index * estimateSize(),
        size: estimateSize(),
      })),
    getTotalSize: () => count * estimateSize(),
    measure: () => {},
  }),
}));

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

function makeEditorHandlers(): LayerEditorHandlers {
  return {
    onTabChange: vi.fn(),
    onPaintChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onFilterChange: vi.fn(),
    onLabelChange: vi.fn(),
    onPopupChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onRenderModeChange: vi.fn(),
    onRemove: vi.fn(),
  };
}

function makeStackRowProps(layer: MapLayerResponse) {
  return {
    layer,
    selected: false,
    isDragging: false,
    dragHandleProps: {
      attributes: {
        role: 'button',
        tabIndex: 0,
        'aria-disabled': false,
        'aria-pressed': false,
        'aria-roledescription': 'sortable',
        'aria-describedby': 'dnd-desc',
      } as never,
      listeners: undefined,
      setActivatorNodeRef: vi.fn(),
    },
    onSelectLayer: vi.fn(),
    onToggleVisibility: vi.fn(),
    onRemove: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    onOpenAttributeTable: vi.fn(),
  };
}

function makeRowsReturn(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      columns: [
        { name: 'gid', type: 'integer' },
        { name: 'name', type: 'text' },
      ],
      rows: [
        { gid: 1, name: 'a' },
        { gid: 2, name: 'b' },
      ],
      next_cursor: null,
      approximate_total: 2,
      sortable_columns: ['name'],
      table_id: 't1',
    },
    isLoading: false,
    isFetching: false,
    isError: false,
    isPlaceholderData: false,
    error: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useDatasetRows).mockReturnValue(makeRowsReturn() as never);
  vi.mocked(useUpdateFeature).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as never);
  vi.mocked(getFeature).mockResolvedValue({
    type: 'Feature',
    id: 2,
    geometry: { type: 'Point', coordinates: [12.5, 48.1] },
    properties: { name: 'b' },
  });
});

// ---------------------------------------------------------------------------
// Drawer behavior
// ---------------------------------------------------------------------------

describe('AttributeTableDrawer', () => {
  it('opens for a vector layer: heading names the layer and the rows request carries the converted filter', () => {
    const layer = makeLayer({
      display_name: 'Trails',
      filter: ['==', ['get', 'name'], 'b'] as never,
    });
    const mapRef = { current: makeFakeMap() };
    render(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={mapRef} />);

    expect(screen.getByTestId('attribute-table-drawer-title')).toHaveTextContent('Trails');
    // The legacy maplibre `['==', 'name', 'b']` converts to the CQL2 JSON the
    // rows endpoint reads, sent verbatim as the `filter` param.
    const call = vi.mocked(useDatasetRows).mock.calls.at(-1);
    expect(call?.[0]).toBe('dataset-1');
    expect(call?.[5]).toBe(JSON.stringify({ op: '=', args: [{ property: 'name' }, 'b'] }));
  });

  it('sends no filter param when the layer has no filter', () => {
    render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />,
    );
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBeUndefined();
    expect(screen.queryByTestId('attribute-table-filter-unsupported')).toBeNull();
  });

  it('shows the unsupported notice and requests every row when the filter cannot convert', () => {
    const layer = makeLayer({
      filter: ['match', ['get', 'k'], 'a', true, false] as never,
    });
    render(
      <AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />,
    );
    expect(screen.getByTestId('attribute-table-filter-unsupported')).toHaveTextContent(
      /filter could not be applied/i,
    );
    // The fallback shows every row: no `filter` param goes out.
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBeUndefined();
  });

  it('treats a filter naming an unknown field as unsupported instead of sending a 400', () => {
    // The layer's own column metadata has no `stale_field`; the rows endpoint
    // would reject the converted filter and the table could not load at all.
    const layer = makeLayer({
      dataset_column_info: [{ name: 'name', type: 'text' }],
      filter: ['==', ['get', 'stale_field'], 1] as never,
    });
    render(
      <AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />,
    );
    expect(screen.getByTestId('attribute-table-filter-unsupported')).toBeInTheDocument();
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBeUndefined();
  });

  it('still converts a filter on a field the column metadata knows', () => {
    const layer = makeLayer({
      dataset_column_info: [{ name: 'name', type: 'text' }],
      filter: ['==', ['get', 'name'], 'b'] as never,
    });
    render(
      <AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />,
    );
    expect(screen.queryByTestId('attribute-table-filter-unsupported')).toBeNull();
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBe(
      JSON.stringify({ op: '=', args: [{ property: 'name' }, 'b'] }),
    );
  });

  it('restarts paging from the first page when the layer filter changes', () => {
    // A full page carries a cursor, so the mock always offers one.
    const fullPage = makeRowsReturn();
    fullPage.data.next_cursor = 5 as never;
    vi.mocked(useDatasetRows).mockReturnValue(fullPage as never);
    const mapRef = { current: makeFakeMap() };
    const mounted = render(
      <AttributeTableDrawer layer={makeLayer({ id: 'paged' })} open onClose={vi.fn()} mapRef={mapRef} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[2]).toBe(5);

    // The author edits the layer's filter in the editor while the drawer is
    // open: the drawer re-renders with the same table and a new CQL2 filter.
    // The old cursor positions into the OLD row order and must not survive.
    mounted.rerender(
      <AttributeTableDrawer
        layer={makeLayer({ id: 'paged', filter: ['==', ['get', 'name'], 'b'] as never })}
        open
        onClose={vi.fn()}
        mapRef={mapRef}
      />,
    );
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBe(
      JSON.stringify({ op: '=', args: [{ property: 'name' }, 'b'] }),
    );
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[2]).toBe(0);
  });

  it('shows noResults with the toolbar for a filtered empty page, and noData only without a filter', () => {
    const emptyPage = makeRowsReturn();
    emptyPage.data.rows = [];
    emptyPage.data.approximate_total = 0;
    vi.mocked(useDatasetRows).mockReturnValue(emptyPage as never);
    const mapRef = { current: makeFakeMap() };

    // The layer's filter matched zero rows: the dataset is not empty, the
    // FILTER is — the table keeps its header and Columns toolbar and says no
    // row matches.
    const filtered = render(
      <AttributeTableDrawer
        layer={makeLayer({ filter: ['==', ['get', 'name'], 'zzz'] as never })}
        open
        onClose={vi.fn()}
        mapRef={mapRef}
      />,
    );
    expect(screen.getByText('attributes.noResults')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /columns/i })).toBeInTheDocument();

    filtered.unmount();
    // Without a filter an empty page really is an empty dataset.
    render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={mapRef} />,
    );
    expect(screen.getByText('attributes.noData')).toBeInTheDocument();
  });

  it('closes with Escape and with the close button', () => {
    const onClose = vi.fn();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={onClose} mapRef={{ current: makeFakeMap() }} />);

    fireEvent.keyDown(screen.getByTestId('attribute-table-drawer-title'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Close attribute table' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('fits the map to a clicked row and highlights it', async () => {
    const map = makeFakeMap();
    render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );

    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => {
      expect(vi.mocked(getFeature)).toHaveBeenCalledWith('dataset-1', 2);
    });
    await waitFor(() => {
      expect(map.fitBounds).toHaveBeenCalledTimes(1);
    });
    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.addLayer).toHaveBeenCalledTimes(2);
  });

  // Rows are focusable and activate from the keyboard, not just the pointer:
  // both activation keys are pinned because a template-copied handler can
  // carry only one of them.
  it.each([
    { key: 'Enter', label: 'Enter' },
    { key: ' ', label: 'Space' },
  ])('activates a row with $label', async ({ key }) => {
    const map = makeFakeMap();
    render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );

    fireEvent.keyDown(screen.getByRole('row', { name: 'Show row 2 on the map' }), { key });
    await waitFor(() => {
      expect(vi.mocked(getFeature)).toHaveBeenCalledWith('dataset-1', 2);
    });
    await waitFor(() => {
      expect(map.fitBounds).toHaveBeenCalledTimes(1);
    });
  });

  it('replaces a previous layer’s highlight when another layer’s row is clicked', async () => {
    const map = makeFakeMap();
    const first = render(
      <AttributeTableDrawer layer={makeLayer({ id: 'l1' })} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );
    fireEvent.click(screen.getByRole('row', { name: 'Show row 1 on the map' }));
    await waitFor(() => expect(map.addLayer).toHaveBeenCalledTimes(2));

    first.unmount();
    render(
      <AttributeTableDrawer layer={makeLayer({ id: 'l2', dataset_id: 'dataset-2' })} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );
    // Mounting the second drawer cleared the first one's highlight.
    expect(map.removeLayer).toHaveBeenCalledWith('attribute-table-highlight-line');
    expect(map.removeLayer).toHaveBeenCalledWith('attribute-table-highlight-point');
    expect(map.removeSource).toHaveBeenCalledWith('attribute-table-highlight');
  });

  it('paints only the newest of two rapid clicks on the same layer', async () => {
    const map = makeFakeMap();
    const pending: Array<(value: Awaited<ReturnType<typeof getFeature>>) => void> = [];
    vi.mocked(getFeature).mockImplementation(
      () => new Promise((resolve) => { pending.push(resolve); }),
    );
    render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );

    // Two rapid clicks, and the SECOND request resolves first.
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    fireEvent.click(screen.getByRole('row', { name: 'Show row 1 on the map' }));
    await act(async () => {
      pending[1]({
        type: 'Feature',
        id: 1,
        geometry: { type: 'Point', coordinates: [3, 4] },
        properties: {},
      });
    });

    // The newest response painted: one source, two highlight layers, one fit.
    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.addLayer).toHaveBeenCalledTimes(2);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);

    // The older response must not repaint over it.
    await act(async () => {
      pending[0]({
        type: 'Feature',
        id: 2,
        geometry: { type: 'Point', coordinates: [12.5, 48.1] },
        properties: {},
      });
    });
    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.addLayer).toHaveBeenCalledTimes(2);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });

  it('ignores an in-flight row response once the drawer moved to another layer', async () => {
    const map = makeFakeMap();
    let resolveFeature!: (value: Awaited<ReturnType<typeof getFeature>>) => void;
    vi.mocked(getFeature).mockImplementationOnce(
      () => new Promise((resolve) => { resolveFeature = resolve; }),
    );
    const { rerender } = render(
      <AttributeTableDrawer
        layer={makeLayer({ id: 'layer-a', dataset_id: 'dataset-a' })}
        open
        onClose={vi.fn()}
        mapRef={{ current: map }}
      />,
    );

    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    expect(vi.mocked(getFeature)).toHaveBeenCalledWith('dataset-a', 2);

    // The page reuses the drawer instance for the next layer while the click's
    // request is still in flight.
    rerender(
      <AttributeTableDrawer
        layer={makeLayer({ id: 'layer-b', dataset_id: 'dataset-b' })}
        open
        onClose={vi.fn()}
        mapRef={{ current: map }}
      />,
    );
    await act(async () => {
      resolveFeature({
        type: 'Feature',
        id: 2,
        geometry: { type: 'Point', coordinates: [1, 2] },
        properties: {},
      });
    });

    // The stale response belongs to layer A: no highlight, no fit.
    expect(map.addLayer).not.toHaveBeenCalled();
    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.fitBounds).not.toHaveBeenCalled();
  });

  it('leaves the map alone when the clicked feature has no geometry', async () => {
    vi.mocked(getFeature).mockResolvedValueOnce({
      type: 'Feature',
      id: 3,
      geometry: null as never,
      properties: {},
    });
    const map = makeFakeMap();
    render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => expect(vi.mocked(getFeature)).toHaveBeenCalled());
    expect(map.fitBounds).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Eligibility
// ---------------------------------------------------------------------------

describe('attribute-table action eligibility', () => {
  // Every denylist member is pinned on its own: a denylist missing one
  // entry would otherwise pass the suite while offering an action the rows
  // endpoint refuses for that record type.
  it.each(['raster_dataset', 'vrt_dataset', 'tiles3d_dataset', 'pointcloud_dataset'] as const)(
    'excludes %s datasets from the attribute-table action',
    (recordType) => {
      expect(canOpenAttributeTable(makeLayer({ dataset_record_type: recordType }))).toBe(false);
    },
  );

  // add_layer lets the caller's layer_type override the dataset-derived one,
  // so a vector dataset can be stored with the raster renderer: the record
  // type alone does not say what the layer draws.
  it('excludes a vector dataset rendered as a raster layer', () => {
    expect(
      canOpenAttributeTable(makeLayer({ layer_type: 'raster_geolens' })),
    ).toBe(false);
  });

  it('offers the action on a vector dataset layer row', () => {
    render(<StackRow {...makeStackRowProps(makeLayer({ id: 'vec' }))} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0 });
    expect(screen.getByTestId('kebab-open-attribute-table')).toBeInTheDocument();
  });

  it('does not offer the action for a raster layer', () => {
    render(
      <StackRow
        {...makeStackRowProps(makeLayer({ id: 'raster', dataset_record_type: 'raster_dataset' }))}
      />,
    );
    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0 });
    expect(screen.queryByTestId('kebab-open-attribute-table')).toBeNull();
  });

  it('does not offer the action for a terrain (DEM) layer', () => {
    render(<StackRow {...makeStackRowProps(makeLayer({ id: 'dem', is_dem: true }))} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: /Layer options for/i }), { button: 0 });
    expect(screen.queryByTestId('kebab-open-attribute-table')).toBeNull();
  });

  it('does not offer the action for an unsaved preview row, while a saved layer row keeps it', () => {
    const preview: EphemeralPreviewRowProps = {
      featureCount: 5,
      onDismiss: vi.fn(),
    };
    render(
      <UnifiedStackPanel
        layers={[makeLayer({ id: 'saved-layer' })]}
        selectedLayerId={null}
        onSelectLayer={vi.fn()}
        onToggleVisibility={vi.fn()}
        onReorder={vi.fn()}
        onOpacityChange={vi.fn()}
        onRemove={vi.fn()}
        onRename={vi.fn()}
        onDuplicate={vi.fn()}
        onOpenAttributeTable={vi.fn()}
        onAddDataClick={vi.fn()}
        onSettingsClick={vi.fn()}
        onBulkVisibility={vi.fn()}
        onBulkOpacity={vi.fn()}
        onBulkGroup={vi.fn()}
        onBulkUngroup={vi.fn()}
        onBulkDelete={vi.fn()}
        preview={preview}
      />,
    );
    // The preview row renders with no kebab of its own; the only attribute-table
    // action in the DOM belongs to the saved layer row.
    fireEvent.pointerDown(screen.getAllByRole('button', { name: /Layer options for/i })[0], { button: 0 });
    const items = screen.getAllByTestId('kebab-open-attribute-table');
    expect(items).toHaveLength(1);
  });

  it('offers the action from the layer editor header for a table-backed layer', () => {
    const onOpenAttributeTable = vi.fn();
    render(
      <LayerEditorPanel
        layer={makeLayer()}
        onClose={vi.fn()}
        isDrillDown={false}
        handlers={makeEditorHandlers()}
        activeTab="style"
        editorScene="default"
        onOpenAttributeTable={onOpenAttributeTable}
      />,
    );
    fireEvent.click(screen.getByTestId('layer-editor-open-attribute-table'));
    expect(onOpenAttributeTable).toHaveBeenCalledWith('layer-1');
  });

  it('hides the editor-header action for a raster layer and in non-default scenes', () => {
    const handlers = makeEditorHandlers();
    const { rerender } = render(
      <LayerEditorPanel
        layer={makeLayer({ dataset_record_type: 'raster_dataset' })}
        onClose={vi.fn()}
        isDrillDown={false}
        handlers={handlers}
        activeTab="style"
        editorScene="default"
        onOpenAttributeTable={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('layer-editor-open-attribute-table')).toBeNull();

    rerender(
      <LayerEditorPanel
        layer={makeLayer()}
        onClose={vi.fn()}
        isDrillDown={false}
        handlers={handlers}
        activeTab="style"
        editorScene="settings"
        sceneContent={<div />}
        onOpenAttributeTable={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('layer-editor-open-attribute-table')).toBeNull();
  });
});
