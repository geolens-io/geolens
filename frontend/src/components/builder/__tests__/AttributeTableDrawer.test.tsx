/**
 * Builder attribute-table drawer: eligibility, the converted-filter rows
 * request, the unsupported-filter fallback, and the fit-and-highlight on a
 * row click (click and keyboard activation).
 *
 * The eligibility tests render the REAL kebab (StackRow) and editor header
 * (LayerEditorPanel) so a later refactor that moves the action still fails
 * here until the eligibility contract moves with it.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { beforeAll, beforeEach, vi } from 'vitest';
import { AttributeTableDrawer } from '../AttributeTableDrawer';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import * as attributeTableModule from '@/components/dataset/AttributeTable';
import { applyBasemapConfigToMap, reorderDataLayers, toSyncInput } from '../map-sync';
import { applyMapBasemapAppearance, syncMapComposition } from '../map-composition-sync';
import { DEFAULT_BASEMAP_CONFIG, isBasemapOwnedLayer } from '@/lib/basemap-utils';
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
  let styleLoadFired = false;
  // Registered 'style.load' listeners: the round-5 tests fire a style
  // replacement through these and assert the drawer unsubscribed on unmount.
  const styleLoadListeners = new Set<() => void>();
  const idleListeners = new Set<() => void>();
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
    resize: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    // MapLibre exposes the parsed style even while sources are still loading.
    getStyle: vi.fn(() => styleLoadFired ? { version: 8, sources: {}, layers: [] } : undefined),
    on: vi.fn((event: string, handler: () => void) => {
      if (event === 'style.load') styleLoadListeners.add(handler);
      if (event === 'idle') idleListeners.add(handler);
    }),
    off: vi.fn((event: string, handler: () => void) => {
      if (event === 'style.load') styleLoadListeners.delete(handler);
      if (event === 'idle') idleListeners.delete(handler);
    }),
    once: vi.fn((event: string, handler: () => void) => {
      const listeners = event === 'style.load' ? styleLoadListeners : idleListeners;
      const once = () => {
        listeners.delete(once);
        handler();
      };
      listeners.add(once);
    }),
    fire: vi.fn((event: string) => {
      const listeners = event === 'style.load' ? styleLoadListeners : idleListeners;
      for (const handler of [...listeners]) handler();
    }),
    // A style replacement drops the custom sources and layers, then runs the
    // registered 'style.load' listeners.
    fireStyleLoad: () => {
      styleLoadFired = true;
      sources.clear();
      layers.clear();
      for (const handler of [...styleLoadListeners]) handler();
    },
    styleLoadListenerCount: () => styleLoadListeners.size,
  } as unknown as MaplibreMap & Record<string, ReturnType<typeof vi.fn>> & {
    fireStyleLoad: () => void;
    styleLoadListenerCount: () => number;
  };
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  // The drawer reads useBuilderLayout's isEditorHidden to pick the docked
  // section vs the <800px sheet; jsdom has no matchMedia, so hand the hook a
  // never-matching one (>=800px: the table stays docked). Assigned directly
  // rather than vi.stubGlobal so vi.unstubAllGlobals() in the round-4
  // describe's afterEach cannot clear it mid-file.
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
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

  it('resets scroll on a cql2Filter change while the cursor is already zero', () => {
    const filter = (name: string) => JSON.stringify({ op: '=', args: [{ property: 'name' }, name] });
    const mounted = render(<AttributeTable datasetId="dataset-1" cql2Filter={filter('original')} />);
    const region = screen.getByRole('region', { name: 'attributes.tableLabel' });
    region.scrollTop = 44;
    region.scrollLeft = 16;
    expect(region.scrollTop).toBe(44);
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[2]).toBe(0);

    const response = makeRowsReturn();
    vi.mocked(useDatasetRows).mockReturnValue({
      ...response,
      data: { ...response.data, rows: [{ gid: 3, name: 'filtered' }] },
    } as never);
    mounted.rerender(<AttributeTable datasetId="dataset-1" cql2Filter={filter('filtered')} />);

    expect(screen.getByText('filtered')).toBeInTheDocument();
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[2]).toBe(0);
    expect(region.scrollTop).toBe(0);
    expect(region.scrollLeft).toBe(16);
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

  it('Escape does not close the docked table; the close button does', () => {
    const onClose = vi.fn();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={onClose} mapRef={{ current: makeFakeMap() }} />);

    // Escape stays with the map: no Escape handler closes the table.
    fireEvent.keyDown(screen.getByTestId('attribute-table-drawer-title'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Close attribute table' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it.each([
    Number('9007199254740993'),
    '9007199254740993',
    BigInt('9007199254740993'),
  ])('does not activate an unsafe gid (%s)', (gid) => {
    const response = makeRowsReturn();
    vi.mocked(useDatasetRows).mockReturnValue({
      ...response,
      data: { ...response.data, rows: [{ gid, name: 'unsafe' }] },
    } as never);
    const onRowClick = vi.fn();
    render(<AttributeTable datasetId="dataset-1" onRowClick={onRowClick} />);
    const row = screen.getByText('unsafe').closest('tr')!;

    fireEvent.click(row);
    expect(onRowClick).not.toHaveBeenCalled();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(onRowClick).not.toHaveBeenCalled();
    fireEvent.keyDown(row, { key: ' ' });
    expect(onRowClick).not.toHaveBeenCalled();
    expect(row).not.toHaveAttribute('tabindex');
    expect(row).not.toHaveAttribute('aria-label');
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

// ---------------------------------------------------------------------------
// Round 4: docked attribute-table contracts (red until round 4 lands)
// ---------------------------------------------------------------------------

describe('docked attribute table (round 4)', () => {
  // The post-implementation table root is a <section> (role region) named by
  // the layer; until the dock lands the component renders a Radix sheet, so
  // helpers route through whichever shape exists and let the contract
  // assertions fail.
  function tableRoot(name: string | RegExp = 'Population'): HTMLElement | null {
    return (
      screen.queryByRole('region', { name })
      ?? document.querySelector<HTMLElement>('[data-slot="sheet-content"]')
    );
  }

  /** The rendered data rows (virtualized rows carry data-index). */
  function dataRows(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>('tr[data-index]'));
  }

  function assertOrder(elements: Element[]): void {
    for (let i = 1; i < elements.length; i++) {
      expect(
        elements[i - 1].compareDocumentPosition(elements[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  }

  const resizeHandle = () => screen.getByRole('separator');
  const valuenow = () => Number(resizeHandle().getAttribute('aria-valuenow'));

  /** invocationCallOrder of a recording map method (the fake types them as
   *  MaplibreMap members, so reach for the vi.fn underneath). */
  const invocationOrder = (fn: unknown): number[] =>
    (fn as unknown as { mock: { invocationCallOrder: number[] } }).mock.invocationCallOrder;

  // jsdom computes no layout; the clamp bounds come from window.innerHeight
  // (MAX_DRAWER_HEIGHT_RATIO), so pin the window to a known size. jsdom also
  // has no pointer capture, which the resize handle calls directly.
  beforeEach(() => {
    vi.stubGlobal('innerHeight', 1000);
    Object.defineProperty(Element.prototype, 'setPointerCapture', {
      configurable: true,
      writable: true,
      value: () => {},
    });
    Object.defineProperty(Element.prototype, 'releasePointerCapture', {
      configurable: true,
      writable: true,
      value: () => {},
    });
  });

  afterEach(() => {
    delete (Element.prototype as unknown as Record<string, unknown>).setPointerCapture;
    delete (Element.prototype as unknown as Record<string, unknown>).releasePointerCapture;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders the table as a section named by the layer, not a dialog', () => {
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />);

    const table = screen.getByRole('region', { name: 'Population' });
    expect(table.tagName).toBe('SECTION');
    // The name comes from the header's title element via aria-labelledby.
    expect(table).toHaveAttribute('aria-labelledby');
    const titleId = (table.getAttribute('aria-labelledby') ?? '').split(/\s+/)[0];
    expect(document.getElementById(titleId)).toContainElement(
      screen.getByTestId('attribute-table-drawer-title'),
    );

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeNull();
  });

  it('Escape on the section and inside the table does not close it; the close button does', () => {
    const onClose = vi.fn();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={onClose} mapRef={{ current: makeFakeMap() }} />);

    // The section root (a sheet content until the dock lands).
    fireEvent.keyDown(tableRoot()!, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();

    // Inside the table: a data row.
    fireEvent.keyDown(dataRows()[0], { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Close attribute table' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape on the below-800px sheet does not close it and does not lose focus', () => {
    // Below the editor's breakpoint the table renders as a sheet; the drawer
    // reads the real useBuilderLayout, whose initial state takes innerWidth.
    vi.stubGlobal('innerWidth', 640);
    const onClose = vi.fn();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={onClose} mapRef={{ current: makeFakeMap() }} />);

    expect(screen.queryByRole('region', { name: 'Population' })).toBeNull();
    const sheet = document.querySelector<HTMLElement>('[data-slot="sheet-content"]')!;
    expect(sheet).not.toBeNull();

    // Escape stays with the map: the sheet stays open and focused.
    const close = within(sheet).getByRole('button', { name: 'Close attribute table' });
    close.focus();
    fireEvent.keyDown(sheet, { key: 'Escape' });
    expect(document.querySelector('[data-slot="sheet-content"]')).not.toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(close);

    // The close button still closes it.
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fits with exactly { padding: 40, maxZoom: 18 } at several table heights', async () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    const row2 = screen.getByRole('row', { name: 'Show row 2 on the map' });
    fireEvent.click(row2);
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));
    expect(map.fitBounds).toHaveBeenNthCalledWith(1, [[12.5, 48.1], [12.5, 48.1]], { padding: 40, maxZoom: 18 });

    // Vary the table height through the resize contract; the fit options must
    // not depend on it.
    fireEvent.keyDown(resizeHandle(), { key: 'ArrowUp' });
    expect(resizeHandle()).toHaveAttribute('aria-valuenow');
    const afterUp = valuenow();
    fireEvent.click(row2);
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(2));
    expect(map.fitBounds).toHaveBeenNthCalledWith(2, [[12.5, 48.1], [12.5, 48.1]], { padding: 40, maxZoom: 18 });

    fireEvent.keyDown(resizeHandle(), { key: 'ArrowDown' });
    expect(valuenow()).not.toBe(afterUp);
    fireEvent.click(row2);
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(3));
    expect(map.fitBounds).toHaveBeenNthCalledWith(3, [[12.5, 48.1], [12.5, 48.1]], { padding: 40, maxZoom: 18 });
  });

  it('resize: keyboard steps and past-bound drags clamp, and aria-value* track the height', () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    const handle = screen.getByRole('separator');
    expect(handle).toHaveAttribute('aria-valuenow');
    expect(handle).toHaveAttribute('aria-valuemin');
    expect(handle).toHaveAttribute('aria-valuemax');
    const min = Number(handle.getAttribute('aria-valuemin'));
    const max = Number(handle.getAttribute('aria-valuemax'));
    expect(min).toBeGreaterThan(0);
    expect(max).toBeLessThan(window.innerHeight);
    expect(min).toBeLessThan(max);

    const section = handle.closest('section');
    expect(section).not.toBeNull();
    const heightOf = () => parseFloat(section!.style.height);
    const now = () => Number(handle.getAttribute('aria-valuenow'));
    // One consistent unit: the current height is the aria value.
    expect(heightOf()).toBe(now());

    const beforeUp = heightOf();
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    expect(heightOf()).toBeGreaterThan(beforeUp);
    expect(heightOf()).toBe(now());

    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    expect(heightOf()).toBeLessThan(beforeUp);
    expect(heightOf()).toBe(now());

    fireEvent.keyDown(handle, { key: 'Home' });
    expect(heightOf()).toBe(max);
    expect(now()).toBe(max);

    fireEvent.keyDown(handle, { key: 'End' });
    expect(heightOf()).toBe(min);
    expect(now()).toBe(min);

    // Pointer drags past either bound pin the height at that bound.
    fireEvent.pointerDown(handle, { clientY: 400 });
    fireEvent.pointerMove(handle, { clientY: -10000 });
    expect(heightOf()).toBe(max);
    expect(now()).toBe(max);
    fireEvent.pointerUp(handle, { clientY: -10000 });

    fireEvent.pointerDown(handle, { clientY: 400 });
    fireEvent.pointerMove(handle, { clientY: 10000 });
    expect(heightOf()).toBe(min);
    expect(now()).toBe(min);
    fireEvent.pointerUp(handle, { clientY: 10000 });
  });

  it('a smaller window lowers the maximum and re-clamps an over-tall table', () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    const handle = screen.getByRole('separator');
    const section = handle.closest('section')!;
    fireEvent.keyDown(handle, { key: 'Home' });
    const maxBefore = Number(handle.getAttribute('aria-valuemax'));
    expect(parseFloat(section.style.height)).toBe(maxBefore);

    // The column's height follows the window: shrink it under the open table.
    vi.stubGlobal('innerHeight', 500);
    act(() => {
      window.dispatchEvent(new Event('resize'));
    });

    // The maximum follows the window and the over-tall table re-clamps to it,
    // consistently across the section height and all three aria values.
    const maxAfter = Number(handle.getAttribute('aria-valuemax'));
    expect(maxAfter).toBe(Math.round(500 * 0.7));
    expect(maxAfter).toBeLessThan(maxBefore);
    expect(handle.getAttribute('aria-valuemin')).toBe('120');
    expect(Number(handle.getAttribute('aria-valuenow'))).toBe(maxAfter);
    expect(parseFloat(section.style.height)).toBe(maxAfter);
  });

  it('pointer drag calls map.resize at most once per frame, with a final call on drag end', () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    const handle = screen.getByRole('separator');

    const frames: FrameRequestCallback[] = [];
    const flushFrame = () => {
      const due = frames.splice(0);
      for (const cb of due) cb(performance.now());
    };
    const realRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = (cb: FrameRequestCallback) => {
      frames.push(cb);
      return frames.length;
    };

    try {
      // Two moves inside one frame coalesce into exactly one resize.
      fireEvent.pointerDown(handle, { clientY: 500 });
      fireEvent.pointerMove(handle, { clientY: 495 });
      fireEvent.pointerMove(handle, { clientY: 490 });
      flushFrame();
      expect(map.resize).toHaveBeenCalledTimes(1);

      // The next frame with further moves gives another.
      fireEvent.pointerMove(handle, { clientY: 485 });
      fireEvent.pointerMove(handle, { clientY: 480 });
      flushFrame();
      expect(map.resize).toHaveBeenCalledTimes(2);

      // Drag end gives a final resize.
      fireEvent.pointerUp(handle, { clientY: 480 });
      flushFrame();
      expect(map.resize).toHaveBeenCalledTimes(3);
    } finally {
      window.requestAnimationFrame = realRaf;
    }
  });

  function expectMergedHeader(table: HTMLElement, opts: { notice: boolean }) {
    const title = within(table).getByTestId('attribute-table-drawer-title');
    const header = title.closest('header');
    expect(header).not.toBeNull();
    expect(table).toContainElement(header!);

    const count = within(header!).getByText('attributes.showingExact');
    const columns = within(header!).getByRole('button', { name: /columns/i });
    const close = within(header!).getByRole('button', { name: 'Close attribute table' });
    const notice = opts.notice
      ? within(header!).getByTestId('attribute-table-filter-unsupported')
      : null;
    assertOrder([title, count, ...(notice ? [notice] : []), columns, close]);

    // The name keeps a visible minimum width and truncates.
    expect(title).toHaveClass('truncate');
    expect(title.className).toMatch(/min-w-/);
    // The pieces that can squeeze the name yield space first.
    expect(count.className).not.toContain('shrink-0');
    if (notice) expect(notice.className).not.toContain('shrink-0');
  }

  function renderTableWithTotalExact() {
    const rows = makeRowsReturn();
    (rows.data as { total_kind?: string }).total_kind = 'exact';
    vi.mocked(useDatasetRows).mockReturnValue(rows as never);
  }

  it('one header holds name, row count, Columns and the close control in order', () => {
    renderTableWithTotalExact();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />);

    const table = screen.getByRole('region', { name: 'Population' });
    expectMergedHeader(table, { notice: false });
  });

  it('the merged header keeps its order with the unsupported-filter notice present', () => {
    renderTableWithTotalExact();
    const layer = makeLayer({ filter: ['match', ['get', 'k'], 'a', true, false] as never });
    render(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />);

    const table = screen.getByRole('region', { name: 'Population' });
    expectMergedHeader(table, { notice: true });
  });

  it('the dataset render stays as before: no drawer header, no picker, no row selection', () => {
    renderTableWithTotalExact();
    render(<AttributeTable datasetId="dataset-1" />);

    expect(document.querySelector('header')).toBeNull();
    expect(screen.queryByTestId('attribute-table-drawer-title')).toBeNull();
    // No docked section (and so no header picker) — the pagination bar's own
    // page-size select is the dataset page's only combobox.
    expect(document.querySelector('section')).toBeNull();
    for (const row of document.querySelectorAll('tr[data-index]')) {
      // Absence, not merely "not 'true'": the dataset page never opts rows
      // into selection, so the attribute itself must not appear.
      expect(row.hasAttribute('aria-selected')).toBe(false);
    }
    // The dataset toolbar is unchanged.
    expect(screen.getByRole('button', { name: /columns/i })).toBeInTheDocument();
  });

  it('a highlighted click selects exactly one row with the inset primary marker; it moves, keeps through a no-geometry click, and clears on a layer switch', async () => {
    const map = makeFakeMap();
    const view = render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );

    const row1 = screen.getByRole('row', { name: 'Show row 1 on the map' });
    const row2 = screen.getByRole('row', { name: 'Show row 2 on the map' });
    fireEvent.click(row2);
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));

    const selected = dataRows().filter((row) => row.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(selected[0].className).toContain('selection-inset');
    // The other rows carry aria-selected="false" or none — all in one form.
    const otherForms = new Set(
      dataRows().filter((row) => row !== selected[0]).map((row) => row.getAttribute('aria-selected')),
    );
    expect(otherForms.size).toBe(1);
    expect([...otherForms][0] === 'false' || [...otherForms][0] === null).toBe(true);

    // A second highlighted click moves the selection.
    fireEvent.click(row1);
    await waitFor(() => {
      expect(dataRows().find((row) => row.getAttribute('aria-selected') === 'true')).toBe(row1);
    });

    // A click without usable geometry leaves it.
    vi.mocked(getFeature).mockResolvedValueOnce({
      type: 'Feature',
      id: 2,
      geometry: null as never,
      properties: {},
    });
    fireEvent.click(row2);
    await waitFor(() => expect(vi.mocked(getFeature)).toHaveBeenCalledTimes(3));
    await act(async () => {});
    // Both valid clicks fitted (the default response carries usable geometry),
    // so the no-geometry click must leave the map at two fits, not revert it.
    expect(map.fitBounds).toHaveBeenCalledTimes(2);
    expect(dataRows().find((row) => row.getAttribute('aria-selected') === 'true')).toBe(row1);

    // A layer switch clears it.
    view.rerender(
      <AttributeTableDrawer
        layer={makeLayer({ id: 'layer-2', dataset_id: 'dataset-2' })}
        open
        onClose={vi.fn()}
        mapRef={{ current: map }}
      />,
    );
    expect(dataRows().find((row) => row.getAttribute('aria-selected') === 'true')).toBeUndefined();
  });

  const BOUNDS_CASES: Array<{
    name: string;
    geometry: Record<string, unknown>;
    fits: [number, number, number, number] | null;
  }> = [
    { name: 'a Point', geometry: { type: 'Point', coordinates: [5, 7] }, fits: [5, 7, 5, 7] },
    { name: 'a MultiPoint', geometry: { type: 'MultiPoint', coordinates: [[1, 2], [3, 4]] }, fits: [1, 2, 3, 4] },
    { name: 'a LineString', geometry: { type: 'LineString', coordinates: [[0, 10], [20, -5]] }, fits: [0, -5, 20, 10] },
    {
      name: 'a MultiLineString',
      geometry: { type: 'MultiLineString', coordinates: [[[0, 0], [10, 10]], [[-5, 5], [15, -15]]] },
      fits: [-5, -15, 15, 10],
    },
    {
      name: 'a Polygon',
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] },
      fits: [0, 0, 10, 10],
    },
    {
      name: 'a MultiPolygon',
      geometry: {
        type: 'MultiPolygon',
        coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]],
      },
      fits: [0, 0, 11, 11],
    },
    {
      name: 'a mixed GeometryCollection',
      geometry: {
        type: 'GeometryCollection',
        geometries: [
          { type: 'Point', coordinates: [2, 3] },
          { type: 'LineString', coordinates: [[-1, 8], [30, -2]] },
          { type: 'Polygon', coordinates: [[[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]] },
        ],
      },
      fits: [-1, -2, 30, 8],
    },
    {
      name: 'a nested GeometryCollection',
      geometry: {
        type: 'GeometryCollection',
        geometries: [
          { type: 'GeometryCollection', geometries: [{ type: 'Point', coordinates: [7, 8] }] },
          { type: 'LineString', coordinates: [[0, 0], [6, -1]] },
        ],
      },
      fits: [0, -1, 7, 8],
    },
    {
      name: 'a collection with an empty member next to a valid one',
      geometry: {
        type: 'GeometryCollection',
        geometries: [{ type: 'LineString', coordinates: [] }, { type: 'Point', coordinates: [3, 4] }],
      },
      fits: [3, 4, 3, 4],
    },
    {
      name: 'a collection with a non-finite member',
      geometry: {
        type: 'GeometryCollection',
        geometries: [{ type: 'Point', coordinates: [Infinity, 4] }, { type: 'Point', coordinates: [2, 3] }],
      },
      fits: [2, 3, 2, 3],
    },
    { name: 'the empty collection', geometry: { type: 'GeometryCollection', geometries: [] }, fits: null },
    {
      name: 'an all-non-finite collection',
      geometry: {
        type: 'GeometryCollection',
        geometries: [{ type: 'Point', coordinates: [Infinity, 4] }, { type: 'Point', coordinates: [5, NaN] }],
      },
      fits: null,
    },
  ];

  it.each(BOUNDS_CASES)('bounds of $name reach fitBounds as the exact envelope', async ({ geometry, fits }) => {
    vi.mocked(getFeature).mockResolvedValueOnce({
      type: 'Feature',
      id: 2,
      geometry: geometry as never,
      properties: {},
    });
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await act(async () => {});

    if (fits === null) {
      // No usable coordinate: no fit, no highlight.
      expect(map.fitBounds).not.toHaveBeenCalled();
      expect(map.addSource).not.toHaveBeenCalled();
      expect(map.addLayer).not.toHaveBeenCalled();
      return;
    }
    const [w, s, e, n] = fits;
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(map.fitBounds).toHaveBeenNthCalledWith(1, [[w, s], [e, n]], { padding: 40, maxZoom: 18 });
    // The highlight source carries the clicked geometry.
    expect(map.addSource).toHaveBeenCalledWith('attribute-table-highlight', {
      type: 'geojson',
      data: { type: 'Feature', geometry, properties: {} },
    });
  });

  it('a click without usable geometry leaves the first highlight in place', async () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 1 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));
    expect(map.getSource('attribute-table-highlight')).toBeTruthy();

    const noUsableKinds = [
      null,
      { type: 'GeometryCollection', geometries: [] },
      { type: 'GeometryCollection', geometries: [{ type: 'Point', coordinates: [] }] },
      { type: 'GeometryCollection', geometries: [{ type: 'Point', coordinates: [Infinity, 4] }] },
    ];
    for (const geometry of noUsableKinds) {
      vi.mocked(getFeature).mockResolvedValueOnce({
        type: 'Feature',
        id: 2,
        geometry: geometry as never,
        properties: {},
      });
      fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
      await waitFor(() => expect(vi.mocked(getFeature)).toHaveBeenCalledTimes(noUsableKinds.indexOf(geometry) + 2));
      await act(async () => {});
      // The first highlight's source and layers stay; nothing is removed or repainted.
      expect(map.removeLayer).not.toHaveBeenCalled();
      expect(map.removeSource).not.toHaveBeenCalled();
      expect(map.addSource).toHaveBeenCalledTimes(1);
      expect(map.addLayer).toHaveBeenCalledTimes(2);
      expect(map.fitBounds).toHaveBeenCalledTimes(1);
      expect(map.getSource('attribute-table-highlight')).toBeTruthy();
    }
  });

  it('a second valid click replaces the highlight: old layers removed before the new added', async () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 1 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));

    const lineGeometry = { type: 'LineString', coordinates: [[0, 0], [10, 20]] };
    vi.mocked(getFeature).mockResolvedValueOnce({
      type: 'Feature',
      id: 2,
      geometry: lineGeometry as never,
      properties: {},
    });
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(2));

    // Exactly one highlight, carrying the NEW geometry.
    expect(map.addSource).toHaveBeenCalledTimes(2);
    expect(map.addLayer).toHaveBeenCalledTimes(4);
    expect(map.addSource).toHaveBeenLastCalledWith('attribute-table-highlight', {
      type: 'geojson',
      data: { type: 'Feature', geometry: lineGeometry, properties: {} },
    });
    // The old layers were removed before the new ones were added.
    expect(invocationOrder(map.removeSource)[0]).toBeLessThan(invocationOrder(map.addSource)[1]);
    expect(invocationOrder(map.removeLayer).at(-1)!).toBeLessThan(
      invocationOrder(map.addLayer)[2],
    );
    expect(map.getLayer('attribute-table-highlight-line')).toBeTruthy();
    expect(map.getLayer('attribute-table-highlight-point')).toBeTruthy();
    expect(map.getSource('attribute-table-highlight')).toBeTruthy();
  });

  it('a stale response dropped by the token leaves the map unchanged', async () => {
    const map = makeFakeMap();
    const pending: Array<(value: Awaited<ReturnType<typeof getFeature>>) => void> = [];
    vi.mocked(getFeature).mockImplementation(
      () => new Promise((resolve) => { pending.push(resolve); }),
    );
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    fireEvent.click(screen.getByRole('row', { name: 'Show row 1 on the map' }));
    await act(async () => {
      pending[1]({
        type: 'Feature',
        id: 1,
        geometry: { type: 'Point', coordinates: [3, 3] },
        properties: {},
      });
    });
    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.addLayer).toHaveBeenCalledTimes(2);

    // The first click's late response is stale: the map stays exactly as the
    // second click painted it.
    await act(async () => {
      pending[0]({
        type: 'Feature',
        id: 2,
        geometry: { type: 'Point', coordinates: [12.5, 48.1] },
        properties: {},
      });
    });
    expect(map.removeLayer).not.toHaveBeenCalled();
    expect(map.removeSource).not.toHaveBeenCalled();
    expect(map.addSource).toHaveBeenCalledTimes(1);
    expect(map.addLayer).toHaveBeenCalledTimes(2);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Round 5: the rows filter never carries a literal the rows endpoint rejects
// (red until the round-5 guard lands). One incompatible literal anywhere makes
// the WHOLE filter unsupported: the drawer then requests every row and shows
// the notice, exactly as for a filter that has no CQL2 form at all.
// ---------------------------------------------------------------------------

describe('round 5: filter literal compatibility', () => {
  interface Column {
    name: string;
    type: string;
  }

  const GID: Column = { name: 'gid', type: 'integer' };

  function typedLayer(column: Column, extraColumns: Column[], filter: unknown) {
    return makeLayer({
      dataset_column_info: [GID, ...extraColumns, column],
      filter: filter as never,
    });
  }

  function expectAllRowsFallback() {
    // The unsupported path requests EVERY row: no `filter` param goes out, and
    // the notice tells the reader why the table disagrees with the map.
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBeUndefined();
    expect(screen.getByTestId('attribute-table-filter-unsupported')).toBeInTheDocument();
  }

  function expectFilterSent(filter: unknown) {
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[5]).toBe(JSON.stringify(filter));
    expect(screen.queryByTestId('attribute-table-filter-unsupported')).toBeNull();
  }

  const INT_WIDTHS = [
    { width: 'smallint', outOfRange: 32768, boundary: 32767 },
    { width: 'integer', outOfRange: 2147483648, boundary: 2147483647 },
    // 2**63 - 1 is not representable as a JS number, so the largest value the
    // guard must still send on bigint is the safe-integer boundary.
    { width: 'bigint', outOfRange: 2 ** 63, boundary: Number.MAX_SAFE_INTEGER },
  ];

  it.each(INT_WIDTHS)(
    'a fractional literal on a $width column makes the whole filter unsupported',
    ({ width }) => {
      render(
        <AttributeTableDrawer
          layer={typedLayer({ name: 'n', type: width }, [], ['>', ['get', 'n'], 1.5])}
          open
          onClose={vi.fn()}
          mapRef={{ current: makeFakeMap() }}
        />,
      );
      expectAllRowsFallback();
    },
  );

  it.each(INT_WIDTHS)(
    'a literal just out of the $width range drops the filter while the boundary value still converts',
    ({ width, outOfRange, boundary }) => {
      const view = render(
        <AttributeTableDrawer
          layer={typedLayer({ name: 'n', type: width }, [], ['>', ['get', 'n'], outOfRange])}
          open
          onClose={vi.fn()}
          mapRef={{ current: makeFakeMap() }}
        />,
      );
      expectAllRowsFallback();

      // The exact boundary is compatible: it goes out verbatim as CQL2.
      view.rerender(
        <AttributeTableDrawer
          layer={typedLayer({ name: 'n', type: width }, [], ['>', ['get', 'n'], boundary])}
          open
          onClose={vi.fn()}
          mapRef={{ current: makeFakeMap() }}
        />,
      );
      expectFilterSent({ op: '>', args: [{ property: 'n' }, boundary] });
    },
  );

  // The sign-asymmetric axis: the guard drops a literal below the lower bound
  // exactly as it drops one above the upper bound, and the negative boundary
  // still converts.
  const LOWER_INT_WIDTHS = [
    { width: 'smallint', outOfRange: -32769, boundary: -32768 },
    { width: 'integer', outOfRange: -2147483649, boundary: -2147483648 },
    // 2**63 is not representable as a JS number either, so the most negative
    // value the guard must still send on bigint is the negative safe-integer
    // boundary.
    { width: 'bigint', outOfRange: -(2 ** 63), boundary: -Number.MAX_SAFE_INTEGER },
  ];

  it.each(LOWER_INT_WIDTHS)(
    'a negative fractional literal on a $width column makes the whole filter unsupported',
    ({ width }) => {
      render(
        <AttributeTableDrawer
          layer={typedLayer({ name: 'n', type: width }, [], ['>', ['get', 'n'], -1.5])}
          open
          onClose={vi.fn()}
          mapRef={{ current: makeFakeMap() }}
        />,
      );
      expectAllRowsFallback();
    },
  );

  it.each(LOWER_INT_WIDTHS)(
    'a literal just under the $width lower bound drops the filter while the negative boundary still converts',
    ({ width, outOfRange, boundary }) => {
      const view = render(
        <AttributeTableDrawer
          layer={typedLayer({ name: 'n', type: width }, [], ['>', ['get', 'n'], outOfRange])}
          open
          onClose={vi.fn()}
          mapRef={{ current: makeFakeMap() }}
        />,
      );
      expectAllRowsFallback();

      // The exact negative boundary is compatible: it goes out verbatim as CQL2.
      view.rerender(
        <AttributeTableDrawer
          layer={typedLayer({ name: 'n', type: width }, [], ['>', ['get', 'n'], boundary])}
          open
          onClose={vi.fn()}
          mapRef={{ current: makeFakeMap() }}
        />,
      );
      expectFilterSent({ op: '>', args: [{ property: 'n' }, boundary] });
    },
  );

  it('one incompatible member of an in list drops the whole filter, never a partial one', () => {
    const view = render(
      <AttributeTableDrawer
        layer={typedLayer({ name: 'n', type: 'integer' }, [], ['in', ['get', 'n'], ['literal', [1, 2.5, 3]]])}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
      />,
    );
    expectAllRowsFallback();

    // The same list with every member compatible converts and is sent whole.
    view.rerender(
      <AttributeTableDrawer
        layer={typedLayer({ name: 'n', type: 'integer' }, [], ['in', ['get', 'n'], ['literal', [1, 3]]])}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
      />,
    );
    expectFilterSent({ op: 'in', args: [{ property: 'n' }, [1, 3]] });
  });

  it('one incompatible condition combined with a compatible one drops the whole filter', () => {
    const text: Column = { name: 'name', type: 'text' };
    const view = render(
      <AttributeTableDrawer
        layer={typedLayer(
          { name: 'n', type: 'integer' },
          [text],
          ['all', ['==', ['get', 'name'], 'a'], ['>', ['get', 'n'], 1.5]],
        )}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
      />,
    );
    expectAllRowsFallback();

    // Both conditions compatible: the full combined filter converts and goes
    // out as one CQL2 `and`, alongside the composed requireKnownFields guard.
    view.rerender(
      <AttributeTableDrawer
        layer={typedLayer(
          { name: 'n', type: 'integer' },
          [text],
          ['all', ['==', ['get', 'name'], 'a'], ['>', ['get', 'n'], 2]],
        )}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
      />,
    );
    expectFilterSent({
      op: 'and',
      args: [
        { op: '=', args: [{ property: 'name' }, 'a'] },
        { op: '>', args: [{ property: 'n' }, 2] },
      ],
    });
  });
});

// ---------------------------------------------------------------------------
// Round 5: the row selection mirrors the map highlight across style reloads
// (red until the drawer re-adds its highlight after 'style.load', the
// builder's repaint precedent — use-ephemeral-layers re-adds its overlay the
// same way). At every moment a row shows as selected iff the map draws the
// highlight.
// ---------------------------------------------------------------------------

describe('round 5: selection vs style reload', () => {
  const LINE_LAYER = 'attribute-table-highlight-line';
  const POINT_LAYER = 'attribute-table-highlight-point';
  const SOURCE = 'attribute-table-highlight';

  const highlightPainted = (map: ReturnType<typeof makeFakeMap>) =>
    Boolean(map.getLayer(LINE_LAYER) && map.getLayer(POINT_LAYER) && map.getSource(SOURCE));

  function selectedRows(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>('tr[data-index]')).filter(
      (row) => row.getAttribute('aria-selected') === 'true',
    );
  }

  async function highlightRow(map: ReturnType<typeof makeFakeMap>, rowName: string) {
    const row = screen.getByRole('row', { name: rowName });
    fireEvent.click(row);
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalled());
    return row;
  }

  it('a style reload repaints the highlight and the row stays selected', async () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    const row = await highlightRow(map, 'Show row 2 on the map');
    expect(highlightPainted(map)).toBe(true);
    expect(selectedRows()).toEqual([row]);

    act(() => {
      map.fireStyleLoad();
    });

    // Repaint-then-keep-selection: the highlight is back on the fresh style
    // and the same row still reads as selected — never one without the other.
    expect(highlightPainted(map)).toBe(true);
    expect(selectedRows()).toEqual([row]);
  });

  it('two consecutive style reloads keep the highlight and the selection aligned', async () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    const row = await highlightRow(map, 'Show row 2 on the map');
    for (let reload = 0; reload < 2; reload++) {
      act(() => {
        map.fireStyleLoad();
      });
      expect(highlightPainted(map)).toBe(true);
      expect(selectedRows()).toEqual([row]);
    }
  });

  it('a style reload while a row request is in flight still leaves the token in charge', async () => {
    const map = makeFakeMap();
    const pending: Array<(value: Awaited<ReturnType<typeof getFeature>>) => void> = [];
    vi.mocked(getFeature).mockImplementation(
      () => new Promise((resolve) => { pending.push(resolve); }),
    );
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);

    // Two clicks; the FIRST response is the stale one. The reload fires while
    // both are unresolved.
    const row2 = screen.getByRole('row', { name: 'Show row 2 on the map' });
    const row1 = screen.getByRole('row', { name: 'Show row 1 on the map' });
    fireEvent.click(row2);
    fireEvent.click(row1);
    act(() => {
      map.fireStyleLoad();
    });

    // The stale (first) response is dropped by the token: nothing paints and
    // nothing is selected.
    await act(async () => {
      pending[0]({
        type: 'Feature',
        id: 2,
        geometry: { type: 'Point', coordinates: [12.5, 48.1] },
        properties: {},
      });
    });
    expect(highlightPainted(map)).toBe(false);
    expect(selectedRows()).toEqual([]);

    // The fresh (second) response paints into the new style: highlight and
    // selection arrive together.
    await act(async () => {
      pending[1]({
        type: 'Feature',
        id: 1,
        geometry: { type: 'Point', coordinates: [3, 3] },
        properties: {},
      });
    });
    expect(highlightPainted(map)).toBe(true);
    expect(selectedRows()).toEqual([row1]);
  });

  it('a style reload after a layer switch or after close paints nothing and selects nothing', async () => {
    const map = makeFakeMap();
    const view = render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );
    await highlightRow(map, 'Show row 2 on the map');
    expect(highlightPainted(map)).toBe(true);

    // Switch the drawer to another layer: the old highlight is cleared.
    view.rerender(
      <AttributeTableDrawer
        layer={makeLayer({ id: 'layer-2', dataset_id: 'dataset-2' })}
        open
        onClose={vi.fn()}
        mapRef={{ current: map }}
      />,
    );
    expect(highlightPainted(map)).toBe(false);
    expect(selectedRows()).toEqual([]);
    const sourcesAtSwitch = vi.mocked(map.addSource).mock.calls.length;
    const layersAtSwitch = vi.mocked(map.addLayer).mock.calls.length;

    // A reload now must not resurrect the previous layer's highlight.
    act(() => {
      map.fireStyleLoad();
    });
    expect(vi.mocked(map.addSource).mock.calls.length).toBe(sourcesAtSwitch);
    expect(vi.mocked(map.addLayer).mock.calls.length).toBe(layersAtSwitch);
    expect(selectedRows()).toEqual([]);

    // After close the same reload paints nothing either.
    view.unmount();
    act(() => {
      map.fireStyleLoad();
    });
    expect(vi.mocked(map.addSource).mock.calls.length).toBe(sourcesAtSwitch);
    expect(vi.mocked(map.addLayer).mock.calls.length).toBe(layersAtSwitch);
    expect(selectedRows()).toEqual([]);
  });

  it('close deregisters the style.load listener: a reload after close paints nothing', async () => {
    const map = makeFakeMap();
    const view = render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );
    await highlightRow(map, 'Show row 2 on the map');
    expect(highlightPainted(map)).toBe(true);

    // Close without unmounting: the subscription and the kept feature end
    // with it, exactly as on unmount.
    view.rerender(
      <AttributeTableDrawer
        layer={makeLayer()}
        open={false}
        onClose={vi.fn()}
        mapRef={{ current: map }}
      />,
    );
    expect(map.styleLoadListenerCount()).toBe(0);

    // A reload now paints nothing and selects nothing new.
    const sourcesAtClose = vi.mocked(map.addSource).mock.calls.length;
    const layersAtClose = vi.mocked(map.addLayer).mock.calls.length;
    const selectedAtClose = selectedRows();
    act(() => {
      map.fireStyleLoad();
    });
    expect(vi.mocked(map.addSource).mock.calls.length).toBe(sourcesAtClose);
    expect(vi.mocked(map.addLayer).mock.calls.length).toBe(layersAtClose);
    expect(selectedRows()).toEqual(selectedAtClose);
  });

  it('the drawer unsubscribes its style.load listener on unmount', async () => {
    const map = makeFakeMap();
    const view = render(
      <AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />,
    );
    await highlightRow(map, 'Show row 2 on the map');
    // The drawer holds a style.load subscription while its highlight can come
    // back.
    expect(map.styleLoadListenerCount()).toBeGreaterThan(0);

    view.unmount();
    expect(map.styleLoadListenerCount()).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Round 5: the header shows the layer name exactly once in every state (red
// until the picker stops doubling the title).
// ---------------------------------------------------------------------------

describe('round 5: the layer name appears exactly once', () => {
  function rowsWithExactTotal() {
    const rows = makeRowsReturn();
    (rows.data as { total_kind?: string }).total_kind = 'exact';
    vi.mocked(useDatasetRows).mockReturnValue(rows as never);
  }

  function assertNameOnce(table: HTMLElement, name: string) {
    const header = table.querySelector('header');
    expect(header).not.toBeNull();
    // Once, counting BOTH the title element and the picker's rendered selected
    // option text: one of the two is enough.
    expect(within(header as HTMLElement).getAllByText(name)).toHaveLength(1);
    // The section's accessible name still resolves to the layer name.
    expect(screen.getByRole('region', { name })).toBe(table);
  }

  function assertSqueezeOrder(header: HTMLElement) {
    // Nothing that can squeeze the name away carries shrink-0.
    const count = within(header).getByText('attributes.showingExact');
    expect(count.className).not.toContain('shrink-0');
  }

  it.each([
    { label: 'picker hidden (no other table-capable layer)', withLayers: false },
    { label: 'picker shown', withLayers: true },
  ])('the name occurs exactly once: $label', ({ withLayers }) => {
    rowsWithExactTotal();
    const trails = makeLayer({ id: 'l-trails', display_name: 'Trails' });
    const parcels = makeLayer({ id: 'l-parcels', display_name: 'Parcels' });
    render(
      <AttributeTableDrawer
        layer={trails}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
        layers={withLayers ? [trails, parcels] : undefined}
        onLayerChange={withLayers ? vi.fn() : undefined}
      />,
    );

    const table = screen.getByRole('region', { name: 'Trails' });
    assertNameOnce(table, 'Trails');
    const header = table.querySelector('header')!;

    const picker = within(table).queryByRole('combobox');
    if (picker) {
      // The picker keeps its accessible name and its width cap while it
      // carries the name — plus the name carrier's min-width and truncation.
      expect(picker).toHaveAccessibleName();
      expect(picker.className).toMatch(/max-w-/);
      expect(picker).toHaveClass('truncate');
      expect(picker.className).toMatch(/min-w-/);
    } else {
      // Without the picker the title is the name carrier: min-width plus
      // truncation, exactly as the merged header has always pinned.
      const title = within(header).getByTestId('attribute-table-drawer-title');
      expect(title).toHaveClass('truncate');
      expect(title.className).toMatch(/min-w-/);
    }
    assertSqueezeOrder(header);
  });

  it('adding and removing the other table-capable layer flips the picker and the name stays single', () => {
    rowsWithExactTotal();
    const trails = makeLayer({ id: 'l-trails', display_name: 'Trails' });
    const parcels = makeLayer({ id: 'l-parcels', display_name: 'Parcels' });
    const view = render(
      <AttributeTableDrawer
        layer={trails}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
      />,
    );

    const table = () => screen.getByRole('region', { name: 'Trails' });
    const nameCount = () => within(table().querySelector('header')!).getAllByText('Trails').length;
    expect(within(table()).queryByRole('combobox')).toBeNull();
    expect(nameCount()).toBe(1);

    // A second eligible layer appears: the picker shows up and the name shows
    // only once — as the picker's selected value.
    view.rerender(
      <AttributeTableDrawer
        layer={trails}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
        layers={[trails, parcels]}
        onLayerChange={vi.fn()}
      />,
    );
    expect(within(table()).getByRole('combobox')).toBeInTheDocument();
    expect(nameCount()).toBe(1);

    // The other layer is removed again: the picker goes and the name is back
    // to the title alone.
    view.rerender(
      <AttributeTableDrawer
        layer={trails}
        open
        onClose={vi.fn()}
        mapRef={{ current: makeFakeMap() }}
      />,
    );
    expect(within(table()).queryByRole('combobox')).toBeNull();
    expect(nameCount()).toBe(1);
  });
});

// The real composition helpers need live paint and layer order, beyond the
// presence-only map used by the row/selection tests above.
function makeCompositionMap() {
  type Layer = {
    id: string;
    type: string;
    source?: string;
    paint?: Record<string, unknown>;
    layout?: Record<string, unknown>;
    filter?: unknown;
  };
  const layers: Layer[] = [];
  const sources = new Map<string, Record<string, unknown>>();
  const listeners = new Map<string, Set<() => void>>();
  const map = {
    ...makeFakeMap(),
    getLayer: vi.fn((id: string) => layers.find((layer) => layer.id === id)),
    getSource: vi.fn((id: string) => sources.get(id)),
    getStyle: vi.fn(() => ({ version: 8, sources: Object.fromEntries(sources), layers })),
    addSource: vi.fn((id: string, definition: Record<string, unknown>) => {
      sources.set(id, { ...definition, serialize: () => definition, setTiles: vi.fn() });
    }),
    removeSource: vi.fn((id: string) => sources.delete(id)),
    addLayer: vi.fn((definition: Layer, beforeId?: string) => {
      const before = layers.findIndex((layer) => layer.id === beforeId);
      layers.splice(before < 0 ? layers.length : before, 0, structuredClone(definition));
    }),
    removeLayer: vi.fn((id: string) => {
      const index = layers.findIndex((layer) => layer.id === id);
      if (index >= 0) layers.splice(index, 1);
    }),
    moveLayer: vi.fn((id: string, beforeId?: string) => {
      const index = layers.findIndex((layer) => layer.id === id);
      if (index < 0) throw new Error(`Missing layer: ${id}`);
      const [layer] = layers.splice(index, 1);
      const before = layers.findIndex((candidate) => candidate.id === beforeId);
      layers.splice(before < 0 ? layers.length : before, 0, layer);
    }),
    getPaintProperty: vi.fn((id: string, key: string) => layers.find((layer) => layer.id === id)?.paint?.[key]),
    setPaintProperty: vi.fn((id: string, key: string, value: unknown) => {
      const layer = layers.find((candidate) => candidate.id === id)!;
      layer.paint = { ...layer.paint, [key]: value };
    }),
    getLayoutProperty: vi.fn((id: string, key: string) => layers.find((layer) => layer.id === id)?.layout?.[key]),
    setLayoutProperty: vi.fn((id: string, key: string, value: unknown) => {
      const layer = layers.find((candidate) => candidate.id === id)!;
      layer.layout = { ...layer.layout, [key]: value };
    }),
    getFilter: vi.fn((id: string) => layers.find((layer) => layer.id === id)?.filter),
    setFilter: vi.fn((id: string, filter: unknown) => {
      layers.find((layer) => layer.id === id)!.filter = filter;
    }),
    setLayerZoomRange: vi.fn(),
    hasImage: vi.fn(() => true),
    on: vi.fn((event: string, handler: () => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(handler);
    }),
    off: vi.fn((event: string, handler: () => void) => listeners.get(event)?.delete(handler)),
    fire: vi.fn((event: string) => {
      for (const handler of [...(listeners.get(event) ?? [])]) handler();
    }),
  } as unknown as ReturnType<typeof makeFakeMap>;
  return map;
}

describe('attribute-table highlight across basemap and composition changes', () => {
  const SOURCE = 'attribute-table-highlight';
  const LINE = 'attribute-table-highlight-line';
  const POINT = 'attribute-table-highlight-point';

  it.each([SOURCE, LINE, POINT])('excludes %s from basemap ownership', (id) => {
    expect(isBasemapOwnedLayer({ id, source: SOURCE }, 'source-')).toBe(false);
    expect(isBasemapOwnedLayer({ id: 'water', source: 'basemap' }, 'source-')).toBe(true);
    expect(isBasemapOwnedLayer({ id: 'layer-1', source: 'source-data-population' }, 'source-')).toBe(false);
  });

  it.each([0, 0.4])('basemap opacity %s leaves the painted highlight untouched', async (opacity) => {
    const map = makeCompositionMap();
    map.addSource('basemap', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'water', type: 'fill', source: 'basemap', paint: { 'fill-opacity': 1 } });
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));
    const paintBefore = [LINE, POINT].map((id) => structuredClone(map.getLayer(id)?.paint));

    applyBasemapConfigToMap(map, { ...DEFAULT_BASEMAP_CONFIG, opacity });

    expect(map.getPaintProperty('water', 'fill-opacity')).toBe(opacity);
    expect([LINE, POINT].map((id) => map.getLayer(id)?.paint)).toEqual(paintBefore);
  });

  it('keeps both highlight layers above data after a direct basemap appearance update', async () => {
    const map = makeCompositionMap();
    const layers = [makeLayer(), makeLayer({ id: 'layer-2', dataset_id: 'dataset-2' })];
    syncMapComposition({
      map,
      layers: layers.map(toSyncInput),
      tokenMap: new Map(),
      managedSourcesRef: { current: new Set<string>() },
      orderKeyRef: { current: '' },
    });
    render(<AttributeTableDrawer layer={layers[0]} open onClose={vi.fn()} mapRef={{ current: map }} />);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));
    expect(map.getStyle()?.layers.slice(-2).map(({ id }) => id)).toEqual([LINE, POINT]);

    applyMapBasemapAppearance({
      map,
      basemapConfig: { ...DEFAULT_BASEMAP_CONFIG, opacity: 0.4 },
      showBasemapLabels: false,
      reorderDataLayerIds: layers.map(({ id }) => ({ id })),
    });

    const order = map.getStyle()!.layers.map(({ id }) => id);
    const dataPositions = order.flatMap((id, index) => id.startsWith('layer-') ? [index] : []);
    expect(dataPositions).toHaveLength(4);
    for (const id of [LINE, POINT]) {
      expect.soft(order.indexOf(id)).toBeGreaterThan(Math.max(...dataPositions));
    }
  });

  it.each(['composition', 'direct appearance'])('restacks highlights with pending sources via %s', async (path) => {
    const map = makeCompositionMap();
    const first = makeLayer();
    const layers = [first, makeLayer({ id: 'layer-2', dataset_id: 'dataset-2' })];
    const managedSourcesRef = { current: new Set<string>() };
    const orderKeyRef = { current: '' };
    const sync = (next: MapLayerResponse[]) => syncMapComposition({
      map,
      layers: next.map(toSyncInput),
      tokenMap: new Map(),
      managedSourcesRef,
      orderKeyRef,
    });
    sync([first]);
    render(<AttributeTableDrawer layer={first} open onClose={vi.fn()} mapRef={{ current: map }} />);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));
    expect(map.getStyle()?.layers.slice(-2).map(({ id }) => id)).toEqual([LINE, POINT]);
    vi.mocked(map.isStyleLoaded).mockReturnValue(false);
    expect(map.getStyle()).toBeDefined();

    if (path === 'composition') {
      sync(layers);
    } else {
      reorderDataLayers(map, [first]);
      applyMapBasemapAppearance({
        map,
        basemapConfig: { ...DEFAULT_BASEMAP_CONFIG, opacity: 0.4 },
        showBasemapLabels: false,
        reorderDataLayerIds: [first],
      });
    }

    const order = map.getStyle()!.layers.map(({ id }) => id);
    const dataPositions = order.flatMap((id, index) => id.startsWith('layer-') ? [index] : []);
    expect(dataPositions.length).toBeGreaterThan(0);
    for (const id of [LINE, POINT]) {
      expect.soft(order.indexOf(id)).toBeGreaterThan(Math.max(...dataPositions));
    }
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(vi.mocked(map.addSource).mock.calls.filter(([id]) => id === SOURCE)).toHaveLength(1);
  });

  it.each(['visibility toggle', 'added layer'])('keeps both highlight layers above data after a %s', async (change) => {
    const map = makeCompositionMap();
    const mapRef = { current: map };
    const managedSourcesRef = { current: new Set<string>() };
    const orderKeyRef = { current: '' };
    const sync = (layers: MapLayerResponse[]) => syncMapComposition({
      map,
      layers: layers.map(toSyncInput),
      tokenMap: new Map(),
      managedSourcesRef,
      orderKeyRef,
    });
    const first = makeLayer({ visible: change !== 'visibility toggle' });
    sync([first]);
    expect(map.getLayer('layer-layer-1')).toBeTruthy();
    const view = render(<AttributeTableDrawer layer={first} layers={[first]} open onClose={vi.fn()} mapRef={mapRef} />);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledTimes(1));
    expect(map.getStyle()?.layers.slice(-2).map(({ id }) => id)).toEqual([LINE, POINT]);
    const updated = change === 'visibility toggle'
      ? [makeLayer({ visible: true })]
      : [first, makeLayer({ id: 'layer-2', dataset_id: 'dataset-2', dataset_table_name: 'parcels' })];

    act(() => {
      sync(updated);
      view.rerender(<AttributeTableDrawer layer={updated[0]} layers={updated} open onClose={vi.fn()} mapRef={mapRef} />);
      map.fire('styledata');
      map.fire('idle');
    });

    expect(map.getLayoutProperty('layer-layer-1', 'visibility')).toBe('visible');
    if (change === 'added layer') expect(map.getLayer('layer-layer-2')).toBeTruthy();
    const order = map.getStyle()?.layers.map(({ id }) => id) ?? [];
    const dataPositions = order.flatMap((id, index) => id.startsWith('layer-') ? [index] : []);
    expect(dataPositions.length).toBeGreaterThan(0);
    for (const id of [LINE, POINT]) {
      expect(order.indexOf(id)).toBeGreaterThan(Math.max(...dataPositions));
    }
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(vi.mocked(map.addSource).mock.calls.filter(([id]) => id === SOURCE)).toHaveLength(1);
  });
});

describe('row response during a basemap style load', () => {
  it('waits for the style, then paints and fits without rejecting the row callback', async () => {
    const map = makeFakeMap();
    vi.mocked(map.isStyleLoaded).mockReturnValue(false);
    const addSource = vi.mocked(map.addSource).getMockImplementation()!;
    vi.mocked(map.addSource).mockImplementation((id, source) => {
      if (!map.isStyleLoaded()) throw new Error('Style is not done loading.');
      return addSource(id, source);
    });
    // Consume the actual row callback's promise so an early MapLibre throw is
    // reported by expect, rather than as an unhandled rejection from a click.
    const RealAttributeTable = attributeTableModule.AttributeTable;
    let rowError: unknown;
    const tableSpy = vi.spyOn(attributeTableModule, 'AttributeTable').mockImplementation((props) => (
      <RealAttributeTable {...props} onRowClick={(gid) => {
        void Promise.resolve(props.onRowClick?.(gid)).catch((error: unknown) => { rowError = error; });
      }} />
    ));
    try {
      render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
      await act(async () => {
        fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
      });
      expect(getFeature).toHaveBeenCalledWith('dataset-1', 2);
      expect.soft(rowError).toBeUndefined();
      expect.soft(map.addSource).not.toHaveBeenCalled();
      expect.soft(map.addLayer).not.toHaveBeenCalled();
      expect.soft(map.fitBounds).not.toHaveBeenCalled();

      await act(async () => {
        vi.mocked(map.isStyleLoaded).mockReturnValue(true);
        map.fireStyleLoad();
        map.fire?.('idle');
      });

      expect(map.getSource('attribute-table-highlight')).toBeTruthy();
      expect(map.getLayer('attribute-table-highlight-line')).toBeTruthy();
      expect(map.getLayer('attribute-table-highlight-point')).toBeTruthy();
      expect.soft(rowError).toBeUndefined();
      expect(map.fitBounds).toHaveBeenCalledTimes(1);
      expect(map.fitBounds).toHaveBeenCalledWith(
        [[12.5, 48.1], [12.5, 48.1]],
        { padding: 40, maxZoom: 18 },
      );
    } finally {
      tableSpy.mockRestore();
    }
  });
});

describe('style readiness after style.load', () => {
  it('paints and fits immediately after style.load while sources are loading', async () => {
    const map = makeFakeMap();
    vi.mocked(map.isStyleLoaded).mockReturnValue(false);
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    act(() => map.fireStyleLoad());
    vi.mocked(map.isStyleLoaded).mockReturnValue(false);

    await act(async () => {
      fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    });

    expect(map.getSource('attribute-table-highlight')).toBeTruthy();
    expect(map.getLayer('attribute-table-highlight-line')).toBeTruthy();
    expect(map.getLayer('attribute-table-highlight-point')).toBeTruthy();
    expect(map.fitBounds).toHaveBeenCalledExactlyOnceWith(
      [[12.5, 48.1], [12.5, 48.1]],
      { padding: 40, maxZoom: 18 },
    );
    expect(map.once).not.toHaveBeenCalled();
  });

  it('repaints a replacement map attached after style.load while sources are loading', async () => {
    const firstMap = makeFakeMap();
    const mapRef = { current: firstMap };
    const layer = makeLayer();
    const view = render(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={mapRef} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    });
    expect(firstMap.fitBounds).toHaveBeenCalledTimes(1);

    const replacement = makeFakeMap();
    replacement.fireStyleLoad();
    expect(replacement.styleLoadListenerCount()).toBe(0);
    vi.mocked(replacement.isStyleLoaded).mockReturnValue(false);
    expect(replacement.getStyle()).toBeTruthy();
    mapRef.current = replacement;
    view.rerender(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={mapRef} />);

    expect(replacement.getSource('attribute-table-highlight')).toBeTruthy();
    expect(replacement.getLayer('attribute-table-highlight-line')).toBeTruthy();
    expect(replacement.getLayer('attribute-table-highlight-point')).toBeTruthy();
    expect(replacement.addSource).toHaveBeenCalledTimes(1);
    expect(replacement.addLayer).toHaveBeenCalledTimes(2);
    expect(replacement.fitBounds).not.toHaveBeenCalled();
    expect(firstMap.styleLoadListenerCount()).toBe(0);
    expect(replacement.styleLoadListenerCount()).toBe(1);

    view.rerender(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={mapRef} />);
    expect(replacement.addSource).toHaveBeenCalledTimes(1);
    expect(replacement.addLayer).toHaveBeenCalledTimes(2);
    expect(replacement.styleLoadListenerCount()).toBe(1);
  });

  it('defers a row click while a replacement style on the same map is unparsed', async () => {
    const map = makeFakeMap();
    const mapRef = { current: map };
    const layer = makeLayer();
    const view = render(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={mapRef} />);
    act(() => map.fireStyleLoad());
    await act(async () => {
      fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    });
    expect(map.getSource('attribute-table-highlight')).toBeTruthy();
    expect(map.fitBounds).toHaveBeenCalledTimes(1);

    const parsedStyle = map.getStyle();
    // Replacing the style drops its custom layers/source before the next style.load.
    map.removeLayer('attribute-table-highlight-line');
    map.removeLayer('attribute-table-highlight-point');
    map.removeSource('attribute-table-highlight');
    vi.mocked(map.isStyleLoaded).mockReturnValue(false);
    vi.mocked(map.getStyle).mockReturnValue(undefined as never);
    vi.mocked(map.addSource).mockClear();
    vi.mocked(map.addLayer).mockClear();
    vi.mocked(map.fitBounds).mockClear();
    vi.mocked(getFeature).mockResolvedValueOnce({
      type: 'Feature', id: 1, geometry: { type: 'Point', coordinates: [3, 4] }, properties: {},
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('row', { name: 'Show row 1 on the map' }));
    });
    expect(getFeature).toHaveBeenLastCalledWith('dataset-1', 1);
    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
    expect(map.fitBounds).not.toHaveBeenCalled();

    view.rerender(<AttributeTableDrawer layer={layer} open onClose={vi.fn()} mapRef={mapRef} />);
    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
    expect(map.fitBounds).not.toHaveBeenCalled();

    await act(async () => {
      vi.mocked(map.getStyle).mockReturnValue(parsedStyle);
      map.fireStyleLoad();
    });
    expect(map.getSource('attribute-table-highlight')).toBeTruthy();
    expect(map.getLayer('attribute-table-highlight-line')).toBeTruthy();
    expect(map.getLayer('attribute-table-highlight-point')).toBeTruthy();
    expect(map.addSource).toHaveBeenLastCalledWith('attribute-table-highlight', {
      type: 'geojson',
      data: { type: 'Feature', geometry: { type: 'Point', coordinates: [3, 4] }, properties: {} },
    });
    expect(map.fitBounds).toHaveBeenCalledExactlyOnceWith([[3, 4], [3, 4]], { padding: 40, maxZoom: 18 });
  });
});

describe('fit padding across an in-flight breakpoint change', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ['dock to sheet', 'feature response', 900, 790],
    ['sheet to dock', 'feature response', 790, 900],
    ['dock to sheet', 'style.load', 900, 790],
    ['sheet to dock', 'style.load', 790, 900],
  ] as const)('fits the current layout for %s while awaiting %s', async (_direction, pendingAt, startWidth, endWidth) => {
    vi.stubGlobal('innerWidth', startWidth);
    vi.stubGlobal('innerHeight', 1000);
    const listeners = new Set<() => void>();
    const editorMql = {
      matches: startWidth < 800,
      addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
    };
    const fallbackMatchMedia = window.matchMedia;
    vi.stubGlobal('matchMedia', (query: string) => query === '(max-width: 799px)'
      ? editorMql : fallbackMatchMedia(query));
    const map = makeFakeMap();
    if (pendingAt === 'style.load') vi.mocked(map.isStyleLoaded).mockReturnValue(false);
    let resolveFeature!: (feature: Awaited<ReturnType<typeof getFeature>>) => void;
    vi.mocked(getFeature).mockImplementationOnce(() => new Promise((resolve) => { resolveFeature = resolve; }));
    const feature = {
      type: 'Feature' as const, id: 2,
      geometry: { type: 'Point' as const, coordinates: [12.5, 48.1] }, properties: {},
    };
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    expect(Boolean(document.querySelector('[data-slot="sheet-content"]'))).toBe(startWidth < 800);
    fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
    expect(getFeature).toHaveBeenCalledWith('dataset-1', 2);
    if (pendingAt === 'style.load') {
      await act(async () => { resolveFeature(feature); });
      expect(map.once).toHaveBeenCalledWith('style.load', expect.any(Function));
    }
    expect(map.fitBounds).not.toHaveBeenCalled();

    act(() => {
      vi.stubGlobal('innerWidth', endWidth);
      editorMql.matches = endWidth < 800;
      for (const listener of listeners) listener();
    });
    const sheet = document.querySelector<HTMLElement>('[data-slot="sheet-content"]');
    expect(Boolean(sheet)).toBe(endWidth < 800);
    const sheetHeight = sheet ? parseFloat(sheet.style.height) : 0;
    if (sheet) expect(sheetHeight).toBeGreaterThan(0);
    await act(async () => {
      if (pendingAt === 'style.load') {
        vi.mocked(map.isStyleLoaded).mockReturnValue(true);
        map.fireStyleLoad();
      } else resolveFeature(feature);
    });

    expect(map.fitBounds).toHaveBeenCalledExactlyOnceWith(
      [[12.5, 48.1], [12.5, 48.1]],
      {
        padding: sheet ? { top: 40, right: 40, left: 40, bottom: 40 + sheetHeight } : 40,
        maxZoom: 18,
      },
    );
  });
});

describe('below-800px attribute table height', () => {
  beforeEach(() => {
    vi.stubGlobal('innerWidth', 640);
    vi.stubGlobal('innerHeight', 1000);
  });

  afterEach(() => vi.unstubAllGlobals());

  // Tailwind is not laid out by jsdom: inspect the rendered height constraint,
  // accepting either an inline bound or an arbitrary-value height class.
  function heightBound(sheet: HTMLElement): number {
    const bounds = [sheet.style.height, sheet.style.maxHeight];
    for (const token of sheet.classList) {
      const match = /^(?:max-)?h-\[([\d.]+(?:px|d?vh))\]$/.exec(token);
      if (match) bounds.push(match[1]);
    }
    return Math.min(...bounds.flatMap((bound) => {
      const match = /^([\d.]+)(px|d?vh)$/.exec(bound);
      if (!match) return [];
      return [Number(match[1]) * (match[2] === 'px' ? 1 : window.innerHeight / 100)];
    }));
  }

  it('bounds the sheet height so at least thirty percent of the window remains for the map', () => {
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />);
    const sheet = document.querySelector<HTMLElement>('[data-slot="sheet-content"]');
    expect(sheet).not.toBeNull();
    expect(heightBound(sheet!)).toBeGreaterThan(0);
    expect(heightBound(sheet!)).toBeLessThanOrEqual(Math.round(window.innerHeight * 0.7));
  });

  it('adds the current sheet height to bottom fit padding before and after resize', async () => {
    const map = makeFakeMap();
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: map }} />);
    const sheet = document.querySelector<HTMLElement>('[data-slot="sheet-content"]')!;
    const handle = within(sheet).getByRole('separator');
    const expectSheetFit = async () => {
      const sheetHeight = parseFloat(sheet.style.height);
      expect(sheetHeight).toBeGreaterThan(0);
      expect(handle).toHaveAttribute('aria-valuenow', String(sheetHeight));
      await act(async () => {
        fireEvent.click(screen.getByRole('row', { name: 'Show row 2 on the map' }));
      });
      expect(map.fitBounds).toHaveBeenLastCalledWith(
        [[12.5, 48.1], [12.5, 48.1]],
        { padding: { top: 40, right: 40, left: 40, bottom: 40 + sheetHeight }, maxZoom: 18 },
      );
    };

    await expectSheetFit();
    const initialHeight = parseFloat(sheet.style.height);
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    expect(parseFloat(sheet.style.height)).toBeGreaterThan(initialHeight);
    await expectSheetFit();
    expect(map.fitBounds).toHaveBeenCalledTimes(2);
  });

  it('keeps the resize handle aria values and keyboard maximum within the sheet cap', () => {
    render(<AttributeTableDrawer layer={makeLayer()} open onClose={vi.fn()} mapRef={{ current: makeFakeMap() }} />);
    const sheet = document.querySelector<HTMLElement>('[data-slot="sheet-content"]');
    expect(sheet).not.toBeNull();
    const handle = within(sheet!).queryByRole('separator');
    expect(handle).not.toBeNull();
    expect(handle).toHaveAttribute('aria-valuemax');
    const max = Number(handle!.getAttribute('aria-valuemax'));
    expect(max).toBeGreaterThan(0);
    expect(max).toBeLessThanOrEqual(Math.round(window.innerHeight * 0.7));
    expect(heightBound(sheet!)).toBeLessThanOrEqual(max);
    fireEvent.keyDown(handle!, { key: 'Home' });
    expect(handle).toHaveAttribute('aria-valuenow', String(max));
    expect(heightBound(sheet!)).toBe(max);
    fireEvent.keyDown(handle!, { key: 'ArrowUp' });
    expect(handle).toHaveAttribute('aria-valuenow', String(max));
  });
});
