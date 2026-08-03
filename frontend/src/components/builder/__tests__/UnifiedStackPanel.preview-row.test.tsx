// fix(#1009): the ephemeral analysis/chat preview renders as a non-persisting
// row pinned at the top of the layer stack.
//
// The load-bearing tests here are the sortable-collection ones. A preview row
// wired through SortableStackRow with `dragDisabled` would LOOK right and still
// be a bug: a disabled sortable stays a member of the collection, so its id
// would sit in UnifiedStackPanel's `sortableIds` with no layer behind it, and
// MapBuilderPage's handleDragEnd maps those ids back to real layers by index to
// write sort_order. These pin that the row is structurally outside dnd-kit.

import { fireEvent, render, screen } from '@/test/test-utils';
import { UnifiedStackPanel } from '../UnifiedStackPanel';
import type { MapLayerResponse } from '@/types/api';

// Capture what UnifiedStackPanel actually hands SortableContext as `items`.
// `useSortable` and the strategy stay real (spread from the original module) so
// the rows still register with dnd-kit exactly as they do in production.
const { sortableItemsSpy } = vi.hoisted(() => ({ sortableItemsSpy: vi.fn() }));

vi.mock('@dnd-kit/sortable', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@dnd-kit/sortable')>();
  const { createElement } = await import('react');
  return {
    ...actual,
    SortableContext: (props: React.ComponentProps<typeof actual.SortableContext>) => {
      sortableItemsSpy(props.items);
      return createElement(actual.SortableContext, props);
    },
  };
});

// react-i18next is deliberately NOT mocked here (unlike the sibling
// UnifiedStackPanel suites): the count strings carry plural variants and
// locale-grouped numbers ({{count, number}} / {{total, number}}), which only
// the real i18n instance renders. Same reasoning as EphemeralBadge.test.tsx.

vi.mock('@/components/map/layer-icons', () => ({
  ColorizedGeometryIcon: ({ layerId }: { layerId: string }) => (
    <span data-testid={`type-icon-${layerId}`} />
  ),
  LayerTypeIcon: ({ iconId }: { iconId: string }) => <span data-testid={`type-icon-${iconId}`} />,
  getLayerColors: () => ({ fill: '#000', stroke: '#fff', outline: '#000' }),
  isDiscreteColorStyle: () => false,
  extractStyleHints: () => ({}),
}));

vi.mock('../EmptyStackState', () => ({
  eyebrowClassName: 'block text-2xs',
  EmptyStackState: () => <div data-testid="empty-stack-state" />,
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

beforeEach(() => {
  sortableItemsSpy.mockClear();
});

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Population',
    dataset_geometry_type: 'POLYGON',
    dataset_table_name: 'population',
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
    style_config: null,
    layer_type: null,
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
  } as MapLayerResponse;
}

const basemapGroup = {
  id: 'basemap-group',
  presetName: 'Positron',
  providerLabel: 'OpenFreeMap',
  visible: true,
  opacity: 1,
  sublayers: [],
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
    basemapGroup,
    onBulkVisibility: vi.fn(),
    onBulkOpacity: vi.fn(),
    onBulkGroup: vi.fn(),
    onBulkUngroup: vi.fn(),
    onBulkDelete: vi.fn(),
    ...overrides,
  };
}

function makePreview(overrides: Partial<React.ComponentProps<typeof UnifiedStackPanel>['preview'] & object> = {}) {
  return {
    featureCount: 240,
    onDismiss: vi.fn(),
    ...overrides,
  };
}

/** The `items` array from the most recent SortableContext render. */
function lastSortableItems(): string[] {
  const calls = sortableItemsSpy.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][0] as string[];
}

describe('#1009: the preview row stays out of the sortable collection', () => {
  const layers = [
    makeLayer({ id: 'data-1', dataset_name: 'Roads', sort_order: 0 }),
    makeLayer({ id: 'data-2', dataset_name: 'Parcels', sort_order: 1 }),
    makeLayer({ id: 'data-3', dataset_name: 'Zoning', sort_order: 2 }),
  ];

  it('the preview id never enters sortableIds', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);

    const items = lastSortableItems();
    // Exactly the real layers plus the basemap group — nothing else.
    expect(items).toEqual(['data-1', 'data-2', 'data-3', 'basemap-group']);
  });

  it('renders the same sortable collection with and without a preview', () => {
    const { rerender } = render(<UnifiedStackPanel {...defaultProps({ layers })} />);
    const withoutPreview = lastSortableItems();

    rerender(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);
    const withPreview = lastSortableItems();

    // Showing a preview must not perturb the collection at all — same ids, same
    // order, same length. Any difference is an index shift the sorting strategy
    // would apply to real rows.
    expect(withPreview).toEqual(withoutPreview);
  });

  // This is the sort_order criterion. handleDragEnd (MapBuilderPage) resolves
  // active.id and over.id back into localLayers by index and writes sort_order
  // from the resulting array; an id in the sortable collection with no layer
  // behind it is the whole corruption vector. Dragging a real layer to the top
  // of the stack drags it ACROSS the preview row (asserted below to be above
  // every sortable row) — and this pins that no id a drag can name is anything
  // other than a real layer or the basemap.
  it('every id a drag can name resolves to a real layer, so a drag across the preview cannot corrupt sort_order', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);

    const items = lastSortableItems();
    for (const id of items) {
      const resolves = id === basemapGroup.id || layers.some((l) => l.id === id);
      expect({ id, resolves }).toEqual({ id, resolves: true });
    }
    expect(items).toHaveLength(layers.length + 1);
  });

  it('the preview row registers nothing with dnd-kit', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);

    const row = screen.getByTestId('ephemeral-preview-row');
    // dnd-kit stamps its draggable attributes onto the activator element; the
    // sortable wrappers additionally stamp data-row-id (which the panel's
    // Shift+Arrow walker reads). The preview row carries neither, so it is
    // invisible to both the drag machinery and range selection.
    expect(row.querySelector('[aria-roledescription]')).toBeNull();
    expect(row.querySelector('[data-row-id]')).toBeNull();
    expect(row.closest('[data-row-id]')).toBeNull();
    // No grip: the row advertises no reorder affordance it cannot honour.
    expect(row.querySelector('svg.lucide-grip-vertical')).toBeNull();
  });

  it('pins the preview above every sortable row, matching the overlay drawing above every layer', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);

    const row = screen.getByTestId('ephemeral-preview-row');
    const sortableRows = [...document.querySelectorAll('[data-row-id]')];
    expect(sortableRows.length).toBeGreaterThan(0);
    for (const sortable of sortableRows) {
      expect(row.compareDocumentPosition(sortable) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it('stays above the basemap row even when the basemap is pinned to the top', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({ layers, preview: makePreview(), basemapPosition: 'top' })}
      />,
    );
    const row = screen.getByTestId('ephemeral-preview-row');
    const basemapRow = document.querySelector('[data-row-id="basemap-group"]')!;
    expect(row.compareDocumentPosition(basemapRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('#1009: the row carries everything the badge offered', () => {
  const layers = [makeLayer({ id: 'data-1' })];

  it('renders no row when there is no preview', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers })} />);
    expect(screen.queryByTestId('ephemeral-preview-row')).not.toBeInTheDocument();
  });

  it('marks the row as ephemeral and not saved', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);
    expect(screen.getByTestId('ephemeral-preview-tag')).toHaveTextContent('Ephemeral — not saved');
  });

  it('carries the truncation count (badge parity — #674/#1076)', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({
          layers,
          preview: makePreview({ featureCount: 500, totalCount: 10651, truncated: true }),
        })}
      />,
    );
    expect(screen.getByText('500 of 10,651 features')).toBeInTheDocument();
  });

  it('says a capped preview was capped when no total is known (#1076)', () => {
    render(
      <UnifiedStackPanel
        {...defaultProps({ layers, preview: makePreview({ featureCount: 500, truncated: true }) })}
      />,
    );
    expect(screen.getByText('first 500 features')).toBeInTheDocument();
  });

  it('carries the #675 "Save as dataset" hand-off', () => {
    const onSaveAsDataset = vi.fn();
    render(
      <UnifiedStackPanel {...defaultProps({ layers, preview: makePreview({ onSaveAsDataset }) })} />,
    );
    fireEvent.click(screen.getByTestId('ephemeral-preview-save'));
    expect(onSaveAsDataset).toHaveBeenCalledTimes(1);
  });

  it('omits "Save as dataset" for previews with no analysis behind them', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview() })} />);
    expect(screen.queryByTestId('ephemeral-preview-save')).not.toBeInTheDocument();
  });

  it('dismisses the preview from the row', () => {
    const onDismiss = vi.fn();
    render(<UnifiedStackPanel {...defaultProps({ layers, preview: makePreview({ onDismiss }) })} />);
    fireEvent.click(screen.getByTestId('ephemeral-preview-dismiss'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('still shows the row on a map with no layers', () => {
    render(<UnifiedStackPanel {...defaultProps({ layers: [], preview: makePreview() })} />);
    // The empty state renders too — a preview must never be stranded without a
    // dismiss affordance just because the map has no layers yet.
    expect(screen.getByTestId('empty-stack-state')).toBeInTheDocument();
    expect(screen.getByTestId('ephemeral-preview-row')).toBeInTheDocument();
  });
});
