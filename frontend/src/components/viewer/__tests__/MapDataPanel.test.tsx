/**
 * The viewer's Map data panel: the Table and List views, the columns a reader
 * starts with and may add, In view, the row-to-map fit and highlight, the
 * map-to-row selection and the phone layouts. `useVirtualizer` is stubbed
 * because jsdom computes no layout; the pane's height is stubbed per test.
 */
import { useRef } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { toast } from 'sonner';
import { makeFakeMap } from '@/test/fake-map';
import { ApiError } from '@/api/client';
import { getDatasetRows } from '@/api/datasets';
import { toFitBounds } from '@/lib/bbox';
import { useMapSelectionStore } from '@/stores/map-selection-store';
import type { DatasetRowsResponse, SharedLayerResponse } from '@/types/api';
import { MapDataPanel } from '../MapDataPanel';
import { createViewerLayerEntries } from '../layer-identity';
import { offersTable } from '../map-data-table';

vi.mock('@/api/datasets', () => ({ getDatasetRows: vi.fn() }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * estimateSize(), size: estimateSize() })),
    getTotalSize: () => count * estimateSize(),
    measure: () => {},
    scrollToIndex: () => {},
  }),
}));

const LAYER: SharedLayerResponse = {
  id: 'layer-1',
  dataset_id: 'dataset-1',
  dataset_name: 'Roads',
  display_name: 'Public roads',
  table_name: 'roads',
  geometry_type: 'LINESTRING',
  column_info: [
    { name: 'name', type: 'text', title: 'Street name' },
    { name: 'kind', type: 'text', value_labels: { r: 'Residential' } },
    { name: 'secret', type: 'text' },
  ],
  sort_order: 0,
  visible: true,
  show_in_legend: true,
  opacity: 1,
  paint: {},
  layout: {},
  filter: null,
  label_config: null,
  popup_config: { enabled: true, visible_fields: ['kind', 'name'] },
  style_config: null,
  tile_url: '',
  feature_count: 2,
  dataset_tile_columns: ['name', 'kind'],
};

const ROWS: DatasetRowsResponse = {
  columns: [
    { name: 'gid', type: 'integer' },
    { name: 'name', type: 'text' },
    { name: 'kind', type: 'text' },
    { name: 'secret', type: 'text' },
  ],
  rows: [
    { gid: 1, name: 'Main St', kind: 'r', secret: 'x' },
    { gid: 2, name: 'Oak Ave', kind: 'c', secret: 'y' },
  ],
  next_cursor: null,
  approximate_total: 2,
  total_kind: 'exact',
  sortable_columns: [],
  bboxes: [[-75, 39, -74, 40], null],
} as DatasetRowsResponse;

const STYLE_LAYERS = { 'viewer-layer-layer-1': { source: 'viewer-source-layer-1', sourceLayer: 'data.roads' } };
const fakeMap = () => makeFakeMap({ styleLayers: STYLE_LAYERS });

interface HarnessProps {
  map: MaplibreMap;
  tableEnabled?: boolean;
  embedToken?: string;
  datasetLinksAllowed?: boolean;
  layers?: SharedLayerResponse[];
  onClose?: () => void;
  onListShownChange?: (shown: boolean) => void;
}

function Harness({ map, tableEnabled = true, embedToken, datasetLinksAllowed = false, layers = [LAYER], onClose = vi.fn(), onListShownChange = vi.fn() }: HarnessProps) {
  const mapRef = useRef<MaplibreMap | null>(map);
  const paneRef = useRef<HTMLDivElement | null>(null);
  const tableEntries = tableEnabled ? createViewerLayerEntries(layers).filter(({ layer }) => offersTable(layer)) : [];
  return (
    <div ref={paneRef} data-pane="">
      <MapDataPanel
        id="panel"
        layers={layers}
        visibleLayers={new Set(layers.map((layer) => layer.id))}
        tableEntries={tableEntries}
        mapRef={mapRef}
        paneRef={paneRef}
        featureResult={{ features: [], total: 0, truncated: false }}
        onRefresh={vi.fn()}
        datasetLinksAllowed={datasetLinksAllowed}
        embedToken={embedToken}
        onClose={onClose}
        onListShownChange={onListShownChange}
      />
    </div>
  );
}

function headerNames() {
  return within(screen.getAllByRole('row')[0]).getAllByRole('columnheader').map((header) => header.textContent ?? '');
}

const lastRowsRequest = () => vi.mocked(getDatasetRows).mock.calls.at(-1)!;

beforeAll(() => {
  // useIsMobile reads innerWidth and listens on matchMedia, which jsdom lacks.
  window.matchMedia = vi.fn(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});

let paneHeight = 800;

beforeEach(() => {
  paneHeight = 800;
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function clientHeight(this: HTMLElement) {
    return this.dataset.pane === undefined ? 0 : paneHeight;
  });
  vi.mocked(getDatasetRows).mockReset();
  vi.mocked(getDatasetRows).mockResolvedValue(ROWS);
  vi.mocked(toast.error).mockClear();
  useMapSelectionStore.getState().clear();
  window.innerWidth = 1280;
});

afterEach(() => {
  useMapSelectionStore.getState().clear();
  vi.restoreAllMocks();
});

describe('MapDataPanel', () => {
  it('offers only the List view when the map has the reader table off', () => {
    render(<Harness map={fakeMap()} tableEnabled={false} />);

    expect(screen.getByRole('region', { name: 'Map data' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Map layer and feature data' })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'Table' })).not.toBeInTheDocument();
    expect(getDatasetRows).not.toHaveBeenCalled();
  });

  it('offers no table for a layer whose popup lists no fields', () => {
    const layer = { ...LAYER, popup_config: { enabled: true, visible_fields: [] } };
    render(<Harness map={fakeMap()} layers={[layer]} />);

    expect(screen.queryByRole('radio', { name: 'Table' })).not.toBeInTheDocument();
    expect(getDatasetRows).not.toHaveBeenCalled();
  });

  it('switches between the Table and List views and keeps focus on the switch', async () => {
    const onListShownChange = vi.fn();
    render(<Harness map={fakeMap()} onListShownChange={onListShownChange} />);
    await screen.findByText('Main St');
    expect(onListShownChange).toHaveBeenLastCalledWith(false);

    fireEvent.click(screen.getByRole('radio', { name: 'List' }));
    expect(screen.getByRole('region', { name: 'Map layer and feature data' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'List' })).toHaveFocus();
    expect(onListShownChange).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole('radio', { name: 'Table' }));
    expect(await screen.findByText('Main St')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Table' })).toHaveAttribute('aria-checked', 'true');
  });

  it('starts from the popup fields in popup order, with titles and value labels', async () => {
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    // Titles where the attribute has one, and no SQL types.
    expect(headerNames()).toEqual(['kind', 'Street name']);
    expect(screen.getByRole('button', { name: 'Residential' })).toBeInTheDocument();
    expect(screen.queryByText('x')).not.toBeInTheDocument();
  });

  it('lets a reader add a column the popup leaves out', async () => {
    const user = userEvent.setup();
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    await user.click(screen.getByRole('button', { name: /columns/i }));
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'secret' }));
    await user.keyboard('{Escape}');

    expect(headerNames().some((name) => name.includes('secret'))).toBe(true);
  });

  it('limits an embed reader of a non-public dataset to the tile columns', async () => {
    const user = userEvent.setup();
    render(<Harness map={fakeMap()} embedToken="embed-tok" />);
    await screen.findByText('Main St');

    expect(lastRowsRequest()[1]).toMatchObject({ embedToken: 'embed-tok', withBbox: true });
    await user.click(screen.getByRole('button', { name: /columns/i }));
    expect(screen.queryByRole('menuitemcheckbox', { name: 'secret' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitemcheckbox', { name: 'gid' })).toBeInTheDocument();
  });

  it('leaves the columns open when every dataset on the map is public', async () => {
    const user = userEvent.setup();
    render(<Harness map={fakeMap()} embedToken="embed-tok" datasetLinksAllowed />);
    await screen.findByText('Main St');

    await user.click(screen.getByRole('button', { name: /columns/i }));
    expect(screen.getByRole('menuitemcheckbox', { name: 'secret' })).toBeInTheDocument();
  });

  it('narrows the rows by the layer filter and, with In view on, by the map view', async () => {
    const layer = { ...LAYER, filter: ['==', ['get', 'kind'], 'r'] } as SharedLayerResponse;
    render(<Harness map={fakeMap()} layers={[layer]} />);
    await screen.findByText('Main St');

    expect(screen.getByText('Filtered by map')).toBeInTheDocument();
    const before = JSON.parse(lastRowsRequest()[1]!.cql2Filter!);
    expect(JSON.stringify(before)).not.toContain('s_intersects');

    fireEvent.click(screen.getByRole('switch', { name: 'In view' }));

    await waitFor(() => expect(lastRowsRequest()[1]!.cql2Filter).toContain('s_intersects'));
    const after = JSON.parse(lastRowsRequest()[1]!.cql2Filter!);
    expect(after.op).toBe('and');
    expect(after.args).toContainEqual(before);
    expect(after.args).toContainEqual({
      op: 's_intersects',
      args: [
        { property: 'geometry' },
        { type: 'Polygon', coordinates: [[[-76, 38], [-73, 38], [-73, 41], [-76, 41], [-76, 38]]] },
      ],
    });
  });

  it('says why a view with In view on has no rows', async () => {
    vi.mocked(getDatasetRows).mockImplementation(async (_id, params) => (
      params?.cql2Filter?.includes('s_intersects') ? { ...ROWS, rows: [], bboxes: [], approximate_total: 0 } : ROWS
    ));
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    fireEvent.click(screen.getByRole('switch', { name: 'In view' }));

    expect(await screen.findByText('No rows in view. Pan the map or turn off In view.')).toBeInTheDocument();
  });

  it('fits the map to a clicked row and highlights the feature on its own source by id', async () => {
    const map = fakeMap();
    render(<Harness map={map} />);
    const row = (await screen.findByText('Main St')).closest('tr')!;

    fireEvent.click(row);

    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledWith(toFitBounds([-75, 39, -74, 40]), expect.anything()));
    const highlight = vi.mocked(map.addLayer).mock.calls.map(([def]) => def as unknown as Record<string, unknown>);
    expect(highlight).toHaveLength(2);
    for (const def of highlight) {
      expect(def).toMatchObject({ source: 'viewer-source-layer-1', 'source-layer': 'data.roads' });
      expect(JSON.stringify(def.filter)).toContain(JSON.stringify(['==', ['id'], 1]));
    }
    expect(row).toHaveAttribute('aria-selected', 'true');
  });

  it('leaves the map alone for a row without geometry', async () => {
    const map = fakeMap();
    render(<Harness map={map} />);
    const row = (await screen.findByText('Oak Ave')).closest('tr')!;

    fireEvent.keyDown(row, { key: 'Enter' });

    await act(async () => {});
    expect(map.fitBounds).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();
  });

  it('selects the row of a feature clicked on the map', async () => {
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    act(() => useMapSelectionStore.getState().select('layer-1', 2));

    expect(screen.getByText('Oak Ave').closest('tr')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Main St').closest('tr')).toHaveAttribute('aria-selected', 'false');
  });

  it('fetches a selected feature that is not on the page by its gid', async () => {
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    act(() => useMapSelectionStore.getState().select('layer-1', 99));
    fireEvent.click(await screen.findByRole('button', { name: 'Show selected' }));

    await waitFor(() => expect(lastRowsRequest()[1]).toMatchObject({ gid: 99 }));
  });

  it('explains a refused table and keeps the other layers selectable', async () => {
    const other = { ...LAYER, id: 'layer-2', dataset_id: 'dataset-2', display_name: 'Parcels' };
    vi.mocked(getDatasetRows).mockImplementation(async (id) => {
      if (id === 'dataset-1') throw new ApiError('Not found', 404);
      return ROWS;
    });
    render(<Harness map={fakeMap()} layers={[LAYER, other]} />);

    expect(await screen.findByText("This layer's table isn't available here.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Table layer' }), { target: { value: 'layer-2' } });
    expect(await screen.findByText('Main St')).toBeInTheDocument();
  });

  it('shows the embed-expired toast when the embed token is refused', async () => {
    vi.mocked(getDatasetRows).mockRejectedValue(new ApiError('Unauthorized', 401));
    render(<Harness map={fakeMap()} embedToken="embed-tok" />);

    expect(await screen.findByText("This layer's table isn't available here.")).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledWith(expect.any(String), { id: 'viewer-embed-auth-error' });
  });

  it('closes from its close button', async () => {
    const onClose = vi.fn();
    render(<Harness map={fakeMap()} onClose={onClose} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close map data' }));

    expect(onClose).toHaveBeenCalledOnce();
  });

  it('opens full screen on a phone and returns to the docked panel', async () => {
    window.innerWidth = 375;
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    fireEvent.click(screen.getByRole('button', { name: 'Expand map data' }));
    const dialog = await screen.findByRole('dialog', { name: 'Map data' });
    expect(await within(dialog).findByText('Main St')).toBeInTheDocument();
    expect(within(dialog).queryByRole('separator')).not.toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Expand map data' })).toHaveFocus());
  });

  it('keeps three rows on a phone, taking the height from the map', () => {
    window.innerWidth = 375;
    paneHeight = 380;
    render(<Harness map={fakeMap()} />);

    const separator = screen.getByRole('separator', { name: 'Resize map data' });
    expect(separator).toHaveAttribute('aria-valuenow', '240');
    expect(separator).toHaveAttribute('aria-valuemin', '240');
    expect(screen.getByRole('region', { name: 'Map data' })).toHaveStyle({ height: '240px' });
  });

  it('leaves the map 240px on wider screens', () => {
    paneHeight = 500;
    render(<Harness map={fakeMap()} />);

    expect(screen.getByRole('separator', { name: 'Resize map data' })).toHaveAttribute('aria-valuemax', '260');
  });

  it('resizes in whole pixels', () => {
    render(<Harness map={fakeMap()} />);
    const separator = screen.getByRole('separator', { name: 'Resize map data' });

    fireEvent.keyDown(separator, { key: 'ArrowUp' });
    fireEvent.keyDown(separator, { key: 'ArrowUp' });

    expect(separator).toHaveAttribute('aria-valuenow', '387');
  });

  it('drops the per-column filters from the docked phone table and keeps them full screen', async () => {
    window.innerWidth = 375;
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');
    expect(screen.queryByRole('textbox', { name: /^Filter / })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Expand map data' }));
    const dialog = await screen.findByRole('dialog', { name: 'Map data' });
    expect(await within(dialog).findAllByRole('textbox', { name: /^Filter / })).not.toHaveLength(0);
  });

  it('keeps the rows on screen as In view turns on and asks for the view at once', async () => {
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    fireEvent.click(screen.getByRole('switch', { name: 'In view' }));

    expect(screen.getByText('Main St')).toBeInTheDocument();
    await waitFor(() => expect(lastRowsRequest()[1]!.cql2Filter).toContain('s_intersects'), { timeout: 200 });
  });

  it('switches to the layer of a feature clicked on the map and selects its row', async () => {
    const other = { ...LAYER, id: 'layer-2', dataset_id: 'dataset-2', display_name: 'Parcels' };
    render(<Harness map={fakeMap()} layers={[LAYER, other]} />);
    await screen.findByText('Main St');

    act(() => useMapSelectionStore.getState().select('layer-2', 2));

    expect(screen.getByRole('combobox', { name: 'Table layer' })).toHaveValue('layer-2');
    await waitFor(() => expect(lastRowsRequest()[0]).toBe('dataset-2'));
    expect((await screen.findByText('Oak Ave')).closest('tr')).toHaveAttribute('aria-selected', 'true');
  });

  it('announces the row count once it settles', async () => {
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    expect(await screen.findByText('Showing 1-2 of 2 rows', { selector: '[aria-live="polite"]' }, { timeout: 2000 }))
      .toBeInTheDocument();
  });

  it('fits a point row at street level rather than the deepest zoom', async () => {
    vi.mocked(getDatasetRows).mockResolvedValue({ ...ROWS, bboxes: [[-75, 39, -75, 39], null] });
    const map = fakeMap();
    render(<Harness map={map} />);

    fireEvent.click((await screen.findByText('Main St')).closest('tr')!);

    await waitFor(() => expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 16 })));
  });

  it('offers no full-screen view on wider screens', async () => {
    render(<Harness map={fakeMap()} />);
    await screen.findByText('Main St');

    expect(screen.queryByRole('button', { name: 'Expand map data' })).not.toBeInTheDocument();
  });
});
