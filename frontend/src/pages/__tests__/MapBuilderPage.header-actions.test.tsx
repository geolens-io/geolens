import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { useParams } from 'react-router';
import { toast } from 'sonner';
import { act, fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { MapBuilderPage } from '@/pages/MapBuilderPage';
import { AnalysisJobWatcher } from '@/components/analysis/AnalysisJobWatcher';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { ApiError } from '@/api/client';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useUpdateFeature } from '@/hooks/use-features';
import { getFeature } from '@/api/features';
import { useMapSelectionStore } from '@/stores/map-selection-store';
import type { MapLayerResponse } from '@/types/api';
import {
  ANALYSIS_JOB_STORAGE_KEY,
  registerAnalysisAddToMap,
  useAnalysisAddToMapStore,
  useAnalysisJobStore,
} from '@/stores/analysis-job-store';

const dialogsState = {
  showChat: false,
  setShowChat: vi.fn(),
  showAddData: false,
  setShowAddData: vi.fn(),
  showShare: false,
  setShowShare: vi.fn(),
  showInfo: false,
  setShowInfo: vi.fn(),
  sidebarCollapsed: false,
  setSidebarCollapsed: vi.fn(),
};
let mockIsEditorHidden = false;
let mockIsRail = false;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

// The builder map hands the test's fake map instance to the page via onMapRef
// (mockPageMap is null unless a test installs one), so the docked table's
// fit-and-highlight can be observed at page level.
// makeFakeMap's shape, so a test can hand the page a replacement map and
// fire style.load on it.
type FakeMap = ReturnType<typeof makeFakeMap>;
let mockPageMap: FakeMap | null = null;
// Round 5: set before a (re)render to make the BuilderMap module mock throw,
// exercising MapErrorBoundary's fallback.
let mockBuilderMapThrows = false;

const builderMapMounts = vi.hoisted(() => ({ count: 0 }));

vi.mock('@/components/builder/BuilderMap', async () => {
  const { useEffect } = await import('react');
  return {
    BuilderMap: ({ onMapRef }: { onMapRef?: (map: unknown) => void }) => {
      if (mockBuilderMapThrows) throw new Error('BuilderMap crashed for the round-5 test');
      useEffect(() => {
        builderMapMounts.count += 1;
        onMapRef?.(mockPageMap);
        return () => { onMapRef?.(null); };
      // eslint-disable-next-line react-hooks/exhaustive-deps -- hand the test's map once per mount
      }, []);
      return <div data-testid="builder-map" />;
    },
  };
});

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));

vi.mock('@/hooks/use-features', () => ({
  useUpdateFeature: vi.fn(),
  useDeleteFeatures: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/api/features', () => ({
  getFeature: vi.fn(),
}));

// jsdom computes no layout, so the real virtualizer renders a zero window of
// rows; render them all instead (same stub as
// AttributeTableDrawer.test.tsx).
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
    scrollToIndex: () => {},
  }),
}));

vi.mock('@/components/builder/LayerPanel', () => ({
  LayerPanel: () => <div data-testid="layer-panel" />,
}));

vi.mock('@/components/builder/DatasetSearchPanel', () => ({
  DatasetSearchPanel: () => <div data-testid="dataset-search-panel" />,
}));

vi.mock('@/components/builder/SharePanel', () => ({
  ShareDialog: () => <div data-testid="share-dialog" />,
}));

vi.mock('@/components/builder/SettingsEditorScene', () => ({
  SettingsEditorScene: () => <div data-testid="settings-editor-scene" />,
}));

// The round-5 boundary tests need the host's anchor slots in the DOM (the
// filter chips live in topLeftSlot on the real page) and count its mounts, so
// the host renders its topLeftSlot inside a testid div.
const pluginHostMounts = vi.fn();

vi.mock('@/components/map-plugins', async () => {
  const { useEffect } = await import('react');
  return {
    PluginHost: ({ topLeftSlot }: { topLeftSlot?: ReactNode }) => {
      useEffect(() => {
        pluginHostMounts();
      }, []);
      return <div data-testid="plugin-host">{topLeftSlot}</div>;
    },
    PluginSidebar: () => null,
    getPlugins: () => [],
    getEnabledPluginDefinitions: () => [],
    getDefaultPluginIds: () => [],
    resolveAvailablePluginIds: () => [],
    usePartitionedPlugins: () => ({ byAnchor: {} }),
  };
});

const loadedMapQuery = {
  data: {
    id: 'map-1',
    name: 'Operations Map',
    description: 'Map description',
    visibility: 'private',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-02T00:00:00Z',
    created_by_username: 'editor-user',
    layer_count: 0,
    thumbnail_url: null,
    layers: [],
  },
  isLoading: false,
  error: null,
};
let mockMapQuery: { data?: unknown; isLoading: boolean; error: unknown } = loadedMapQuery;
let mockLayersMapId: string | null = 'map-1';

vi.mock('@/hooks/use-maps', () => ({
  useMap: () => mockMapQuery,
  useAddLayer: () => ({}),
  useRemoveLayer: () => ({}),
  useExportMapStyleJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useImportMapStyleJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useLayersHiddenFromMapGroups: () => new Set(),
}));

vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: false }),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledPlugins: () => ({ data: null }),
  useBasemaps: () => ({ data: [] }),
}));

vi.mock('@/components/builder/hooks/use-builder-layout', () => ({
  useBuilderLayout: () => ({
    isRail: mockIsRail,
    isEditorHidden: mockIsEditorHidden,
    // Backward-compat aliases
    isCompact: mockIsRail,
    isMobile: mockIsEditorHidden,
    viewportWidth: mockIsEditorHidden ? 600 : mockIsRail ? 1024 : 1440,
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-dialogs', () => ({
  useBuilderDialogs: () => dialogsState,
}));

let mockExpandedLayerId: string | null = null;
const mockHandleToggleExpand = vi.fn();
// The layers the builder edits; the docked-table tests install real layers.
let mockLocalLayers: MapLayerResponse[] = [];
const mockHandleRemove = vi.fn();
// Stable identity so the analysis registration below can assert
// WHICH callback got registered, not just that something did.
const mockChatAddDataset = vi.fn();

vi.mock('@/components/builder/hooks/use-builder-layers', () => ({
  useBuilderLayers: () => ({
    dashboard: { panel: 'right', widgets: [] },
    localLayers: mockLocalLayers,
    savedLayerBaseline: mockLocalLayers,
    layersMapId: mockLayersMapId,
    localName: 'Operations Map',
    setLocalName: vi.fn(),
    localDescription: 'Map description',
    setLocalDescription: vi.fn(),
    localBasemap: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    localTerrainConfig: null,
    setLocalTerrainConfig: vi.fn(),
    setLocalBasemap: vi.fn(),
    setShowBasemapLabels: vi.fn(),
    setBasemapConfig: vi.fn(),
    setHasUnsavedChanges: vi.fn(),
    hasUnsavedChanges: false,
    expandedLayerId: mockExpandedLayerId,
    activeEditorTab: 'style',
    initialViewState: null,
    ephemeralResult: null,
    groupMeta: {},
    markDirty: vi.fn(),
    handleToggleExpand: mockHandleToggleExpand,
    handleTabChange: vi.fn(),
    handlePaintChange: vi.fn(),
    handleOpacityChange: vi.fn(),
    handleFilterChange: vi.fn(),
    handlePopupChange: vi.fn(),
    handleLabelChange: vi.fn(),
    handleStyleConfigChange: vi.fn(),
    handleLayoutChange: vi.fn(),
    handleToggleVisibility: vi.fn(),
    handleMoveUp: vi.fn(),
    handleMoveDown: vi.fn(),
    handleReorder: vi.fn(),
    handleDisplayNameChange: vi.fn(),
    handleRemove: mockHandleRemove,
    handleZoomToLayer: vi.fn(),
    handleToggleLegend: vi.fn(),
    handleAddDataset: vi.fn(),
    handleRenderAsChange: vi.fn(),
    handleDuplicateRendering: vi.fn(),
    dispatchLayerAction: vi.fn(),
    handleAiRemoveLayer: vi.fn(),
    handleQueryResult: vi.fn(),
    handleDismissEphemeral: vi.fn(),
    chatLayerActions: {
      onFilterChange: vi.fn(),
      onPaintChange: vi.fn(),
      onStyleConfigChange: vi.fn(),
      onLabelChange: vi.fn(),
      onToggleVisibility: vi.fn(),
      onAddDataset: mockChatAddDataset,
      onRemove: vi.fn(),
      onOpacityChange: vi.fn(),
    },
    handleToggleGroupExpand: vi.fn(),
    handleDEMTerrainBind: vi.fn(),
    handleCreateGroupWithLayer: vi.fn(),
    handleRenameGroup: vi.fn(),
    handleUngroup: vi.fn(),
    handleDeleteGroup: vi.fn(),
    handleAddLayerToExistingGroup: vi.fn(),
    handleMoveLayerOutOfGroup: vi.fn(),
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-save', () => ({
  useBuilderSave: () => ({
    handleSave: vi.fn(),
    isSaving: false,
    handleExportPNG: vi.fn(),
    handleFork: vi.fn(),
    isForkPending: false,
    saveStatus: 'saved',
    isSaveRetryable: false,
    maybeAutoCaptureThumbnail: vi.fn(),
    blocker: { state: 'unblocked', reset: vi.fn(), proceed: vi.fn() },
  }),
}));

vi.mock('sonner', async (importOriginal) => ({
  ...(await importOriginal<typeof import('sonner')>()),
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

vi.mock('@/components/import/hooks/use-ingest', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/components/import/hooks/use-ingest')>()),
  useJobStatus: vi.fn(),
}));

const mockUseParams = vi.mocked(useParams);

beforeEach(() => {
  mockMapQuery = loadedMapQuery;
  mockLayersMapId = 'map-1';
});

describe('MapBuilderPage header actions', () => {
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    mockIsEditorHidden = false;
    mockIsRail = false;
    mockExpandedLayerId = null;
    dialogsState.sidebarCollapsed = false;
    dialogsState.setShowShare.mockReset();
    mockHandleToggleExpand.mockReset();
    localStorage.clear();
  });

  it('mounts a fresh map canvas when the route moves to another map', async () => {
    const { rerender } = render(<MapBuilderPage />, { route: '/maps/map-1' });
    await screen.findByTestId('builder-map');
    const mountsOnOpen = builderMapMounts.count;

    rerender(<MapBuilderPage />);
    expect(builderMapMounts.count).toBe(mountsOnOpen);

    mockUseParams.mockReturnValue({ id: 'map-2' });
    rerender(<MapBuilderPage />);
    await waitFor(() => expect(builderMapMounts.count).toBeGreaterThan(mountsOnOpen));
  });

  it('surfaces share as a primary desktop action for existing maps', async () => {
    const user = userEvent.setup();

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const shareButton = screen.getByRole('button', { name: 'share.title' });
    expect(shareButton).toBeInTheDocument();

    await user.click(shareButton);

    expect(dialogsState.setShowShare).toHaveBeenCalledWith(true);
  });

  it('renders SidebarRail in column 1 and 44px rail buttons when isEditorHidden=true', () => {
    mockIsEditorHidden = true;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // The old sidebar Sheet is gone — the SidebarRail is in Column 1 of the grid
    const sidebar = screen.getByTestId('builder-sidebar');
    expect(sidebar).toBeInTheDocument();

    // No sidebar Sheet present (the sidebar Sheet no longer exists)
    // (only rail Sheet remains, but it needs railPanel != null to open)
    const sheetContents = document.body.querySelectorAll('[data-slot="sheet-content"]');
    expect(sheetContents.length).toBe(0);

    // Rail buttons rendered as 44px targets when isEditorHidden
    const notesRailButton = document.body.querySelector('button[title="dock.notes"]');
    expect(notesRailButton?.className).toContain('h-11');
    expect(notesRailButton?.className).toContain('w-11');
  });

  it('renders the three-column grid builder body on desktop (no resizable sidebar)', () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // Desktop: sidebar is present as a fixed-width grid column (no resize handle)
    const sidebar = screen.getByTestId('builder-sidebar');
    expect(sidebar).toBeInTheDocument();

    // No resize handle in the new layout
    const resizeHandle = document.body.querySelector('[data-testid="builder-sidebar-resize-handle"]');
    expect(resizeHandle).toBeNull();
  });

  it('renders sidebar at 64px rail class when isRail=true', () => {
    mockIsRail = true;
    mockIsEditorHidden = false;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // Sidebar is still present in the grid
    const sidebar = screen.getByTestId('builder-sidebar');
    expect(sidebar).toBeInTheDocument();

    // The builder body grid should include the 64px rail column class
    const builderBody = sidebar.parentElement;
    expect(builderBody?.className).toContain('grid-cols-[64px_1fr]');
  });

  it('clicking the settings cog calls handleToggleExpand with "settings"', async () => {
    const user = userEvent.setup();
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const cogBtn = document.querySelector('[data-testid="settings-cog-btn"]') as HTMLButtonElement;
    expect(cogBtn).toBeTruthy();
    await user.click(cogBtn);

    expect(mockHandleToggleExpand).toHaveBeenCalledWith('settings');
  });
});

// The watcher suite registers builders by hand, so these pin the real
// registration. The watcher offers "Add to map" only for a registered handler
// whose map id matches the finished job's.
describe('MapBuilderPage analysis Add-to-map registration', () => {
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    registerAnalysisAddToMap(null, null);
    mockChatAddDataset.mockReset();
  });

  it('registers the builder add-dataset callback and the open map id', () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    expect(useAnalysisAddToMapStore.getState().add).toBe(mockChatAddDataset);
    expect(useAnalysisAddToMapStore.getState().mapId).toBe('map-1');
  });

  it('clears the registration on unmount so the watcher falls back to View dataset', () => {
    const { unmount } = render(<MapBuilderPage />, { route: '/maps/map-1' });
    expect(useAnalysisAddToMapStore.getState().add).toBe(mockChatAddDataset);

    unmount();

    expect(useAnalysisAddToMapStore.getState().add).toBeNull();
    expect(useAnalysisAddToMapStore.getState().mapId).toBeNull();
  });

  // An open completion toast follows this registration, so clearing and
  // re-registering on a re-render would flip it to View dataset and back.
  it('leaves the registration untouched through a re-render', () => {
    const { rerender } = render(<MapBuilderPage />, { route: '/maps/map-1' });
    const listener = vi.fn();
    const unsubscribe = useAnalysisAddToMapStore.subscribe(listener);

    rerender(<MapBuilderPage />);
    unsubscribe();

    expect(listener).not.toHaveBeenCalled();
    expect(useAnalysisAddToMapStore.getState().add).toBe(mockChatAddDataset);
  });

  it('registers a null map id for an unsaved builder', () => {
    mockUseParams.mockReturnValue({});

    render(<MapBuilderPage />, { route: '/maps/new' });

    expect(useAnalysisAddToMapStore.getState().mapId).toBeNull();
  });

  it('withholds the add handler until the layers belong to this map', () => {
    mockLayersMapId = 'another-map';

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    expect(useAnalysisAddToMapStore.getState().add).toBeNull();
  });

  describe('with a completion toast open', () => {
    beforeEach(() => {
      vi.mocked(toast.success).mockClear();
      localStorage.removeItem(ANALYSIS_JOB_STORAGE_KEY);
      useAnalysisJobStore.setState({
        job: { jobId: 'j1', title: 'Buffered', mapId: 'map-1' },
        completedAt: null,
      });
      vi.mocked(useJobStatus).mockReturnValue({
        data: { status: 'complete', dataset_id: 'ds9' },
        error: null,
      } as unknown as ReturnType<typeof useJobStatus>);
    });

    // This file's i18n mock returns keys.
    const VIEW_DATASET = 'analysisTools.viewDataset';
    const ADD_TO_MAP = 'analysisTools.addToMap';

    function lastToastLabel() {
      const calls = vi.mocked(toast.success).mock.calls;
      const options = calls[calls.length - 1]?.[1] as
        | { action?: { label: string } }
        | undefined;
      return options?.action?.label;
    }

    /** Raise the job's toast with no builder mounted, so it offers View dataset. */
    async function openToast() {
      render(<AnalysisJobWatcher />);
      await waitFor(() => expect(lastToastLabel()).toBe(VIEW_DATASET));
    }

    it('switches it to Add to map once the map and its layers have loaded', async () => {
      await openToast();

      render(<MapBuilderPage />, { route: '/maps/map-1' });

      expect(lastToastLabel()).toBe(ADD_TO_MAP);
    });

    it('keeps it on View dataset while the map is loading', async () => {
      await openToast();
      mockMapQuery = { data: undefined, isLoading: true, error: null };

      render(<MapBuilderPage />, { route: '/maps/map-1' });

      expect(lastToastLabel()).toBe(VIEW_DATASET);
      expect(toast.success).toHaveBeenCalledTimes(1);
    });

    it('keeps it on View dataset when the map fails to load', async () => {
      await openToast();
      // A refetch that fails keeps the cached map, and the page still shows
      // its error screen.
      mockMapQuery = {
        data: loadedMapQuery.data,
        isLoading: false,
        error: new ApiError('Not Found', 404),
      };

      render(<MapBuilderPage />, { route: '/maps/map-1' });

      expect(lastToastLabel()).toBe(VIEW_DATASET);
      expect(toast.success).toHaveBeenCalledTimes(1);
    });
  });
});

// ---------------------------------------------------------------------------
// Round 4: the docked attribute table (red until round 4 lands)
// ---------------------------------------------------------------------------

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

function makeRowsReturn() {
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
      total_kind: 'exact',
      sortable_columns: ['name'],
      table_id: 't1',
    },
    isLoading: false,
    isFetching: false,
    isError: false,
    isPlaceholderData: false,
    error: null,
  };
}

// Stateful fake mirroring AttributeTableDrawer.test.tsx's makeFakeMap, plus
// the page's own on/off listeners and the resize contract.
function makeFakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  // Registered 'style.load' listeners, so a test can fire a style replacement
  // and assert what repainted (same recording fake as the drawer's).
  const styleLoadListeners = new Set<() => void>();
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
    getContainer: vi.fn(() => document.createElement('div')),
    isStyleLoaded: vi.fn(() => true),
    on: vi.fn((event: string, handler: () => void) => {
      if (event === 'style.load') styleLoadListeners.add(handler);
    }),
    off: vi.fn((event: string, handler: () => void) => {
      if (event === 'style.load') styleLoadListeners.delete(handler);
    }),
    fireStyleLoad: () => {
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

describe('MapBuilderPage docked attribute table (round 4)', () => {
  // Focus restore runs through requestAnimationFrame (the page's existing
  // close pattern); running frames synchronously keeps the focus assertions
  // deterministic in jsdom.
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    mockIsRail = false;
    mockIsEditorHidden = false;
    mockExpandedLayerId = null;
    mockHandleRemove.mockReset();
    mockLocalLayers = [
      makeLayer({ id: 'l-trails', display_name: 'Trails' }),
      makeLayer({ id: 'l-parcels', display_name: 'Parcels' }),
    ];
    mockPageMap = makeFakeMap();
    localStorage.clear();
    vi.mocked(useDatasetRows).mockReturnValue(makeRowsReturn() as never);
    vi.mocked(useUpdateFeature).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as never);
    vi.mocked(getFeature).mockResolvedValue({
      type: 'Feature',
      id: 2,
      geometry: { type: 'Point', coordinates: [3, 3] },
      properties: {},
    });
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(performance.now());
      return 0;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    mockPageMap = null;
  });

  const sheetContent = () => document.querySelector('[data-slot="sheet-content"]');
  const tableSectionCount = () =>
    screen.queryAllByRole('region').filter((el) => el.tagName === 'SECTION').length;

  function openTableViaKebab(layerId: string) {
    const row = document.getElementById(`stack-row-${layerId}`);
    if (!row) throw new Error(`missing stack row for ${layerId}`);
    fireEvent.pointerDown(row.querySelector<HTMLElement>('[data-kebab-trigger]')!, { button: 0 });
    fireEvent.click(screen.getByTestId('kebab-open-attribute-table'));
  }

  function kebabTrigger(layerId: string): HTMLElement {
    const row = document.getElementById(`stack-row-${layerId}`);
    if (!row) throw new Error(`missing stack row for ${layerId}`);
    return row.querySelector<HTMLElement>('[data-kebab-trigger]')!;
  }

  function dataRowsIn(scope: HTMLElement): HTMLElement[] {
    return Array.from(scope.querySelectorAll<HTMLElement>('tr[data-index]'));
  }

  // Contract (1): the table section lives inside the map column, the map's
  // wrapper takes flex-1 min-h-0, the section follows it, nothing between the
  // section and the column is fixed/absolute, no sheet/dialog renders at
  // >=800px, and every absolutely positioned column child sits inside the
  // map's wrapper.
  function expectDockedStructure(layerName: string) {
    const table = screen.getByRole('region', { name: layerName });
    expect(table.tagName).toBe('SECTION');
    const mapEl = screen.getByTestId('builder-map');
    // The map area's wrapper is the table's previous sibling: since round 5
    // the boundary wraps the map alone inside it, so the wrapper is the
    // map's ancestor, not its parent.
    const wrapper = table.previousElementSibling as HTMLElement;
    const column = mapEl.closest<HTMLElement>('.relative.min-h-0.min-w-0');
    expect(column).not.toBeNull();
    expect(column).toContainElement(table);
    expect(wrapper.parentElement).toBe(column);
    expect(wrapper).toContainElement(mapEl);
    expect(wrapper).toHaveClass('flex-1', 'min-h-0');
    expect(column!.className).toContain('flex');
    expect(column!.className).toContain('flex-col');

    // No fixed/absolute positioning between the section and the column.
    for (let el: HTMLElement | null = table; el && el !== column; el = el.parentElement) {
      expect(el.classList.contains('fixed')).toBe(false);
      expect(el.classList.contains('absolute')).toBe(false);
    }

    // No sheet or dialog role at 800px and wider.
    expect(sheetContent()).toBeNull();
    expect(screen.queryAllByRole('dialog')).toHaveLength(0);

    // Every absolutely positioned child of the column is a descendant of the
    // map's wrapper, not of the column or the section.
    for (const child of Array.from(column!.children)) {
      const positioned =
        child instanceof HTMLElement &&
        (child.classList.contains('absolute') || child.classList.contains('fixed'));
      if (positioned) expect(wrapper.contains(child)).toBe(true);
    }
    return table;
  }

  it.each([
    ['layer-stack menu', 'stack'],
    ['layer-editor button', 'editor'],
  ])('docks the table in the map column via the %s', (_label, entry) => {
    if (entry === 'editor') mockExpandedLayerId = 'l-trails';
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    if (entry === 'stack') openTableViaKebab('l-trails');
    else fireEvent.click(screen.getByTestId('layer-editor-open-attribute-table'));

    expectDockedStructure('Trails');
  });

  it('stack entry point: the ✕ and a second activation close it; focus returns to the opener', async () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // ✕ close returns focus to the layer's kebab trigger.
    openTableViaKebab('l-trails');
    fireEvent.click(screen.getByRole('button', { name: 'attributeTableDrawer.close' }));
    expect(document.activeElement).toBe(kebabTrigger('l-trails'));

    // A second activation of the same entry point closes it (toggle), and
    // focus lands back on the opener again. Radix's menu-close commit and its
    // close-autofocus restore run one task later than the toggle; drain that
    // deferred work inside act so the assertion observes the real sequence.
    openTableViaKebab('l-trails');
    openTableViaKebab('l-trails');
    expect(sheetContent()).toBeNull();
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeNull();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(document.activeElement).toBe(kebabTrigger('l-trails'));

    // Escape on the map container does not close the table.
    openTableViaKebab('l-trails');
    fireEvent.keyDown(screen.getByTestId('builder-map'), { key: 'Escape' });
    const stillThere = screen.queryByRole('region', { name: 'Trails' }) ?? sheetContent();
    expect(stillThere).not.toBeNull();
  });

  it('opening another layer’s table replaces the open one', () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');
    openTableViaKebab('l-parcels');

    expect(sheetContent()).toBeNull();
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeNull();
    expect(screen.getByRole('region', { name: 'Parcels' })).toBeInTheDocument();
    expect(tableSectionCount()).toBe(1);
  });

  it('editor entry point: a second activation closes it and the ✕ returns focus to the button', () => {
    mockExpandedLayerId = 'l-trails';
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    const opener = screen.getByTestId('layer-editor-open-attribute-table');
    fireEvent.click(opener);

    // Toggle: activating the entry point again closes the table.
    fireEvent.click(screen.getByTestId('layer-editor-open-attribute-table'));
    expect(sheetContent()).toBeNull();

    // Reopen, then close with the ✕: focus returns to the editor button.
    fireEvent.click(screen.getByTestId('layer-editor-open-attribute-table'));
    fireEvent.click(screen.getByRole('button', { name: 'attributeTableDrawer.close' }));
    expect(document.activeElement).toBe(opener);
  });

  it('deleting the open layer returns focus to the first stack row', () => {
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    // The layer disappears while its table is open.
    mockLocalLayers = [makeLayer({ id: 'l-parcels', display_name: 'Parcels' })];
    view.rerender(<MapBuilderPage />);

    const fallback = document.querySelector<HTMLElement>('[data-row-id]');
    expect(fallback).not.toBeNull();
    expect(document.activeElement).toBe(fallback);
  });

  it('restoring a removed layer with the same id keeps its attribute table closed', () => {
    const restoredLayers = mockLocalLayers;
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');
    expect(screen.getByRole('region', { name: 'Trails' })).toBeInTheDocument();

    mockLocalLayers = restoredLayers.filter((layer) => layer.id !== 'l-trails');
    view.rerender(<MapBuilderPage />);
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeNull();

    mockLocalLayers = restoredLayers;
    view.rerender(<MapBuilderPage />);
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeNull();
  });

  it('opens a restored layer attribute table on the first kebab activation after removal', () => {
    const restoredLayers = mockLocalLayers;
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');
    expect(screen.getByRole('region', { name: 'Trails' })).toBeInTheDocument();

    mockLocalLayers = restoredLayers.filter((layer) => layer.id !== 'l-trails');
    view.rerender(<MapBuilderPage />);
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeNull();

    mockLocalLayers = restoredLayers;
    view.rerender(<MapBuilderPage />);
    openTableViaKebab('l-trails');
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeInTheDocument();
  });

  it('deleting the open layer returns focus even when the first stack row is a folder row', () => {
    const folderLayer = () => makeLayer({ id: 'l-group', display_name: 'Folder', layer_type: 'group:folder-1' as never });
    mockLocalLayers = [folderLayer(), makeLayer({ id: 'l-trails', display_name: 'Trails' })];
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    // The layer disappears while its table is open and the first remaining
    // row is the folder-group row (its wrapper carries [data-row-id] too).
    mockLocalLayers = [folderLayer()];
    view.rerender(<MapBuilderPage />);

    const fallback = document.querySelector<HTMLElement>('[data-row-id]');
    expect(fallback).not.toBeNull();
    expect(fallback!.getAttribute('data-row-id')).toBe('l-group');
    expect(document.activeElement).toBe(fallback);
  });

  it('below 800px the table is a full-screen sheet and its close returns focus to the opener', () => {
    mockIsEditorHidden = true;
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    // A full-screen sheet instead of the docked section.
    expect(screen.queryByRole('region', { name: 'Trails' })).toBeNull();
    const sheet = sheetContent() as HTMLElement | null;
    expect(sheet).not.toBeNull();
    expect(sheet!.className).toContain('w-full');

    fireEvent.click(screen.getByRole('button', { name: 'attributeTableDrawer.close' }));
    expect(document.activeElement).toBe(kebabTrigger('l-trails'));
  });

  it('below 800px opening the table from the editor sheet closes the editor; close returns focus to the rail button', () => {
    // Below 800px the layout is also a rail: the stack rows are not rendered.
    mockIsRail = true;
    mockIsEditorHidden = true;
    mockExpandedLayerId = 'l-trails';
    mockHandleToggleExpand.mockClear();
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    fireEvent.click(screen.getByTestId('layer-editor-open-attribute-table'));

    // The editor sheet would cover the features the table fits to.
    expect(mockHandleToggleExpand).toHaveBeenCalledWith('');
    expect(sheetContent()).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'attributeTableDrawer.close' }));
    expect(document.activeElement).toBe(document.querySelector('[data-rail-layer-id="l-trails"]'));
  });

  it('the layer picker lists exactly the table-capable layers in map order and defaults to the opened layer', () => {
    mockLocalLayers = [
      makeLayer({ id: 'l-trails', display_name: 'Trails' }),
      makeLayer({ id: 'l-raster', display_name: 'Hillshade', dataset_record_type: 'raster_dataset' }),
      makeLayer({ id: 'l-rasterized', display_name: 'Rasterized', layer_type: 'raster_geolens' }),
      makeLayer({ id: 'l-dem', display_name: 'Terrain', is_dem: true }),
      makeLayer({ id: 'l-group', display_name: 'Folder', layer_type: 'group:folder-1' as never }),
      makeLayer({ id: 'l-nodataset', display_name: 'No dataset', dataset_id: null as never }),
      makeLayer({ id: 'l-parcels', display_name: 'Parcels' }),
    ];
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    const table = screen.getByRole('region', { name: 'Trails' });
    const picker = within(table).getByRole('combobox');
    expect(picker).toHaveAccessibleName();
    expect(within(picker).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Trails',
      'Parcels',
    ]);
    expect(picker).toHaveValue('l-trails');

    // The default follows the OPENED layer, not the first option: with a
    // later option open the picker must show that layer, not the first
    // eligible one.
    openTableViaKebab('l-parcels');
    const parcelsTable = screen.getByRole('region', { name: 'Parcels' });
    expect(within(parcelsTable).getByRole('combobox')).toHaveValue('l-parcels');
  });

  it('switching layers from the picker swaps the table, keeps its height, and keeps focus on the picker', () => {
    mockLocalLayers = [
      makeLayer({ id: 'l-trails', display_name: 'Trails', dataset_id: 'ds-trails' }),
      makeLayer({ id: 'l-parcels', display_name: 'Parcels', dataset_id: 'ds-parcels' }),
    ];
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    const table = screen.getByRole('region', { name: 'Trails' });
    const handle = within(table).getByRole('separator');
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    const height = handle.getAttribute('aria-valuenow');
    expect(height).not.toBeNull();

    // Opening the table does not move focus into the picker; the switch
    // below is what puts it there and keeps it there.
    expect(document.activeElement).not.toBe(within(table).getByRole('combobox'));
    fireEvent.change(within(table).getByRole('combobox'), { target: { value: 'l-parcels' } });
    expect(vi.mocked(useDatasetRows).mock.calls.at(-1)?.[0]).toBe('ds-parcels');

    const next = screen.getByRole('region', { name: 'Parcels' });
    expect(next).toBe(table);
    expect(within(next).getByRole('separator').getAttribute('aria-valuenow')).toBe(height);
    expect(document.activeElement).toBe(within(next).getByRole('combobox'));
    expect(tableSectionCount()).toBe(1);
  });

  it('switching layers clears the highlight and the selection; close returns focus to the original opener', async () => {
    mockLocalLayers = [
      makeLayer({ id: 'l-trails', display_name: 'Trails', dataset_id: 'ds-trails' }),
      makeLayer({ id: 'l-parcels', display_name: 'Parcels', dataset_id: 'ds-parcels' }),
    ];
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    const table = screen.getByRole('region', { name: 'Trails' });
    fireEvent.click(dataRowsIn(table)[1]);
    await waitFor(() => expect(mockPageMap!.fitBounds).toHaveBeenCalledTimes(1));
    expect(mockPageMap!.getSource('attribute-table-highlight')).toBeTruthy();

    fireEvent.change(within(table).getByRole('combobox'), { target: { value: 'l-parcels' } });

    // The old highlight is gone and no row is selected any more.
    expect(mockPageMap!.removeLayer).toHaveBeenCalledWith('attribute-table-highlight-line');
    expect(mockPageMap!.removeLayer).toHaveBeenCalledWith('attribute-table-highlight-point');
    expect(mockPageMap!.removeSource).toHaveBeenCalledWith('attribute-table-highlight');
    expect(mockPageMap!.getSource('attribute-table-highlight')).toBeFalsy();
    const next = screen.getByRole('region', { name: 'Parcels' });
    expect(
      dataRowsIn(next).find((row) => row.getAttribute('aria-selected') === 'true'),
    ).toBeUndefined();

    // A close after a switch returns focus to the ORIGINAL opener.
    fireEvent.click(screen.getByRole('button', { name: 'attributeTableDrawer.close' }));
    expect(document.activeElement).toBe(kebabTrigger('l-trails'));
  });

  it('a map selection on the open layer selects its row without moving the camera', () => {
    mockLocalLayers = [
      makeLayer({ id: 'l-trails', display_name: 'Trails', dataset_id: 'ds-trails' }),
      makeLayer({ id: 'l-parcels', display_name: 'Parcels', dataset_id: 'ds-parcels' }),
    ];
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');
    const table = screen.getByRole('region', { name: 'Trails' });
    const selectedRows = () =>
      dataRowsIn(table).filter((row) => row.getAttribute('aria-selected') === 'true');
    expect(selectedRows()).toHaveLength(0);

    act(() => useMapSelectionStore.getState().select('l-parcels', 1));
    expect(selectedRows()).toHaveLength(0);

    act(() => useMapSelectionStore.getState().select('l-trails', 2));
    expect(selectedRows()).toEqual([dataRowsIn(table)[1]]);
    expect(mockPageMap!.fitBounds).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Round 5: the map error boundary wraps BuilderMap alone (red until the
// overlays move out of MapErrorBoundary). When BuilderMap throws, the fallback
// replaces only the map; every other part of the map column stays mounted, and
// Retry remounts BuilderMap without touching PluginHost.
// ---------------------------------------------------------------------------

describe('MapBuilderPage round 5: the map error boundary wraps BuilderMap alone', () => {
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    mockIsRail = false;
    mockIsEditorHidden = false;
    mockExpandedLayerId = null;
    mockLocalLayers = [
      makeLayer({
        id: 'l-trails',
        display_name: 'Trails',
        filter: ['==', ['get', 'name'], 'b'] as never,
      }),
    ];
    mockPageMap = makeFakeMap();
    mockBuilderMapThrows = false;
    pluginHostMounts.mockClear();
    localStorage.clear();
    vi.mocked(useDatasetRows).mockReturnValue(makeRowsReturn() as never);
    vi.mocked(useUpdateFeature).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as never);
    vi.mocked(getFeature).mockResolvedValue({
      type: 'Feature',
      id: 2,
      geometry: { type: 'Point', coordinates: [3, 3] },
      properties: {},
    });
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(performance.now());
      return 0;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    mockBuilderMapThrows = false;
    mockPageMap = null;
  });

  const fallbackHeading = () => screen.getByRole('heading', { name: 'errorBoundary.mapTitle' });

  const LINE_LAYER = 'attribute-table-highlight-line';
  const POINT_LAYER = 'attribute-table-highlight-point';
  const HIGHLIGHT_SOURCE = 'attribute-table-highlight';
  const highlightPaintedOn = (map: ReturnType<typeof makeFakeMap>) =>
    Boolean(
      map.getLayer(LINE_LAYER) && map.getLayer(POINT_LAYER) && map.getSource(HIGHLIGHT_SOURCE),
    );
  const selectedRows = () =>
    Array.from(document.querySelectorAll<HTMLElement>('tr[data-index]')).filter(
      (row) => row.getAttribute('aria-selected') === 'true',
    );

  function openTableViaKebab(layerId: string) {
    const row = document.getElementById(`stack-row-${layerId}`);
    if (!row) throw new Error(`missing stack row for ${layerId}`);
    fireEvent.pointerDown(row.querySelector<HTMLElement>('[data-kebab-trigger]')!, { button: 0 });
    fireEvent.click(screen.getByTestId('kebab-open-attribute-table'));
  }

  it('when BuilderMap throws the fallback replaces only the map: toolbar, chips, plugin host and the open table stay mounted', () => {
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');
    expect(screen.getByRole('region', { name: 'Trails' })).toBeInTheDocument();

    mockBuilderMapThrows = true;
    view.rerender(<MapBuilderPage />);

    expect(fallbackHeading()).toBeInTheDocument();
    expect(screen.queryByTestId('builder-map')).toBeNull();
    // The overlays that used to sit inside the boundary stay mounted.
    expect(screen.getByRole('button', { name: 'toolbar.pan' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'filters.toggle' })).toBeInTheDocument();
    expect(screen.getByTestId('plugin-host')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Trails' })).toBeInTheDocument();
  });

  it('below 800px the panel buttons survive a BuilderMap crash', () => {
    mockIsEditorHidden = true;
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });

    mockBuilderMapThrows = true;
    view.rerender(<MapBuilderPage />);

    expect(fallbackHeading()).toBeInTheDocument();
    expect(document.body.querySelector('button[title="dock.notes"]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'toolbar.pan' })).toBeInTheDocument();
    expect(screen.getByTestId('plugin-host')).toBeInTheDocument();
  });

  it('retry remounts BuilderMap only: PluginHost stays mounted throughout', () => {
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    expect(pluginHostMounts).toHaveBeenCalledTimes(1);

    mockBuilderMapThrows = true;
    view.rerender(<MapBuilderPage />);
    expect(fallbackHeading()).toBeInTheDocument();
    // The host survived the crash: it sits outside the boundary.
    expect(pluginHostMounts).toHaveBeenCalledTimes(1);

    mockBuilderMapThrows = false;
    fireEvent.click(screen.getByRole('button', { name: 'errorBoundary.mapRetry' }));
    expect(screen.getByTestId('builder-map')).toBeInTheDocument();
    // The retry remounted BuilderMap, never the host.
    expect(pluginHostMounts).toHaveBeenCalledTimes(1);
  });

  it('retry after a crash hands the drawer a new map: a reload on it repaints and the row stays selected', async () => {
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    // The click paints the highlight on the first map and selects the row.
    const firstMap = mockPageMap!;
    const table = screen.getByRole('region', { name: 'Trails' });
    fireEvent.click(table.querySelectorAll('tr[data-index]')[1]);
    await waitFor(() => expect(firstMap.fitBounds).toHaveBeenCalledTimes(1));
    expect(selectedRows()).toHaveLength(1);
    expect(highlightPaintedOn(firstMap)).toBe(true);

    // The map crashes; Retry builds a NEW map instance and hands it over.
    mockBuilderMapThrows = true;
    view.rerender(<MapBuilderPage />);
    mockPageMap = makeFakeMap();
    mockBuilderMapThrows = false;
    fireEvent.click(screen.getByRole('button', { name: 'errorBoundary.mapRetry' }));
    expect(screen.getByTestId('builder-map')).toBeInTheDocument();
    const secondMap = mockPageMap!;
    expect(secondMap).not.toBe(firstMap);

    // A style reload on the new map repaints the kept highlight: the row
    // never reads selected without its map highlight.
    act(() => {
      secondMap.fireStyleLoad();
    });
    expect(highlightPaintedOn(secondMap)).toBe(true);
    expect(selectedRows()).toHaveLength(1);
  });

  it('retry repaints a replacement map whose style.load fired before attach, without duplicate sources', async () => {
    const view = render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');
    const firstMap = mockPageMap!;
    fireEvent.click(screen.getByRole('region', { name: 'Trails' }).querySelectorAll('tr[data-index]')[1]);
    await waitFor(() => expect(firstMap.fitBounds).toHaveBeenCalledTimes(1));
    expect(highlightPaintedOn(firstMap)).toBe(true);

    mockBuilderMapThrows = true;
    view.rerender(<MapBuilderPage />);
    const secondMap = makeFakeMap();
    secondMap.fireStyleLoad();
    expect(secondMap.styleLoadListenerCount()).toBe(0);
    expect(secondMap.isStyleLoaded()).toBe(true);
    mockPageMap = secondMap;
    mockBuilderMapThrows = false;
    fireEvent.click(screen.getByRole('button', { name: 'errorBoundary.mapRetry' }));

    expect(secondMap).not.toBe(firstMap);
    expect.soft(highlightPaintedOn(secondMap)).toBe(true);
    expect(selectedRows()).toHaveLength(1);
    expect.soft(secondMap.addSource).toHaveBeenCalledTimes(1);
    expect.soft(secondMap.addLayer).toHaveBeenCalledTimes(2);
    expect(secondMap.fitBounds).not.toHaveBeenCalled();

    view.rerender(<MapBuilderPage />);
    expect(highlightPaintedOn(secondMap)).toBe(true);
    expect(secondMap.addSource).toHaveBeenCalledTimes(1);
    expect(secondMap.addLayer).toHaveBeenCalledTimes(2);
    expect(secondMap.styleLoadListenerCount()).toBe(1);
  });

  it('the round-4 dock structure holds against the new map wrapper', () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });
    openTableViaKebab('l-trails');

    const table = screen.getByRole('region', { name: 'Trails' });
    const mapEl = screen.getByTestId('builder-map');
    // The plain wrapper carrying the map area's sizing hosts the map and every
    // round-4 overlay; the table docks as its following sibling.
    const wrap = table.previousElementSibling as HTMLElement;
    expect(wrap).not.toBeNull();
    expect(wrap).toHaveClass('relative', 'min-h-0', 'flex-1');
    expect(wrap).toContainElement(mapEl);
    expect(wrap).toContainElement(screen.getByTestId('plugin-host'));
    expect(wrap).toContainElement(screen.getByRole('button', { name: 'toolbar.pan' }));
    expect(wrap).toContainElement(screen.getByRole('button', { name: 'filters.toggle' }));

    const column = mapEl.closest<HTMLElement>('.relative.min-h-0.min-w-0');
    expect(column).not.toBeNull();
    expect(column!.className).toContain('flex-col');
    expect(column).toContainElement(table);
    // Every positioned child of the column is a descendant of the wrapper, so
    // the overlays keep their anchor when the boundary restructures.
    for (const child of Array.from(column!.children)) {
      const positioned = child instanceof HTMLElement
        && (child.classList.contains('absolute') || child.classList.contains('fixed'));
      if (positioned) expect(wrap.contains(child)).toBe(true);
    }
  });
});
